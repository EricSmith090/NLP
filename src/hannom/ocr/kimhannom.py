"""Kim Hán Nôm API client.

Guardrails:
- token comes from the environment, never from source or logs;
- exact documented User-Agent;
- single-threaded, delayed, exponential backoff;
- every call is recorded in the quota ledger;
- responses are cached by image SHA-256 and parameter hash;
- the parser accepts the documented result_ocr_text/result_bbox shape and
  the guideline's details.details shape, but does not assume either.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import ProjectConfig
from ..labels import points_to_quad
from ..models import OCRLine, OCRResult, PageRecord
from ..state import State, utc_now
from .base import OCREngine, OCRUnavailable
from .quota import QuotaLedger


class KimHanNomError(RuntimeError):
    pass


class ApiBusinessError(KimHanNomError):
    """The API answered with a non-success business code.

    These are deterministic (bad token, invalid enum, stale file_name) and
    must not consume the retry budget. Uploading a file again is the one
    deliberate exception, handled explicitly in recognize_page().
    """


def _success_code(value: Any) -> bool:
    # The manual documents the string "000000"; accept the integer zero some
    # deployments return, but do not guess arbitrary success values.
    return value == "000000" or value == 0


@dataclass
class ApiResponse:
    endpoint: str
    data: dict[str, Any]
    raw: dict[str, Any]
    cached: bool = False


class KimHanNomClient(OCREngine):
    name = "kimhannom"

    def __init__(
        self,
        project: ProjectConfig,
        state: State,
        token: str | None = None,
        token_id: str | None = None,
    ):
        self.project = project
        self.state = state
        self.token = token or os.environ.get(project.api.token_env, "")
        self.token_id = token_id or (hashlib.sha256(self.token.encode()).hexdigest()[:8] if self.token else None)
        self.ledger = QuotaLedger(state, project.api.limits, project.api.min_delay_seconds)
        self.cache_dir = project.api.cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._session = None

    def is_available(self) -> bool:
        if not self.token:
            return False
        try:
            import requests  # noqa: F401
        except ImportError:
            return False
        return True

    def _get_session(self):
        if self._session is not None:
            return self._session
        if not self.token:
            raise OCRUnavailable(
                f"Kim Hán Nôm token is absent. Set {self.project.api.token_env} in .env."
            )
        import requests

        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self.token}",
                "User-Agent": self.project.api.user_agent,
                "Accept": "application/json",
            }
        )
        return self._session

    def _cache_key(self, endpoint: str, image_sha256: str, params: dict[str, Any]) -> str:
        payload = json.dumps({"endpoint": endpoint, "image": image_sha256, "params": params}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / key[:2] / f"{key}.json"

    def _load_cache(self, key: str) -> ApiResponse | None:
        path = self._cache_path(key)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return ApiResponse(
            endpoint=data["endpoint"],
            data=data["data"],
            raw=data.get("raw", {}),
            cached=True,
        )

    def _save_cache(self, key: str, response: ApiResponse) -> None:
        path = self._cache_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "endpoint": response.endpoint,
            "data": response.data,
            "raw": response.raw,
            "saved_at": utc_now().isoformat(),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _upload_cache_path(self, image_sha256: str) -> Path:
        return self.cache_dir / "uploads" / image_sha256[:2] / f"{image_sha256}.json"

    def _load_uploaded_name(self, image_sha256: str) -> str | None:
        path = self._upload_cache_path(image_sha256)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        name = data.get("file_name")
        return str(name) if name else None

    def _save_uploaded_name(self, image_sha256: str, file_name: str) -> None:
        path = self._upload_cache_path(image_sha256)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"file_name": file_name, "saved_at": utc_now().isoformat()}, ensure_ascii=False),
            encoding="utf-8",
        )

    def _request(
        self,
        endpoint: str,
        *,
        json_payload: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        image_sha256: str | None = None,
        cache_params: dict[str, Any] | None = None,
        use_cache: bool = True,
    ) -> ApiResponse:
        if use_cache and image_sha256 and cache_params is not None:
            key = self._cache_key(endpoint, image_sha256, cache_params)
            cached = self._load_cache(key)
            if cached is not None:
                return cached

        session = self._get_session()
        url = f"{self.project.api.base_url}/api/web/clc-sinonom/{endpoint}"
        last_error: Exception | None = None
        for attempt in range(1, self.project.api.max_retries + 1):
            self.ledger.check()
            wait = self.ledger.seconds_until_allowed()
            if wait > 0:
                time.sleep(min(wait, self.project.api.min_delay_seconds * 2))
            try:
                response = session.post(
                    url,
                    json=json_payload,
                    files=files,
                    timeout=self.project.api.timeout_seconds,
                )
                status = response.status_code
                if status in (429, 500, 502, 503, 504) and attempt < self.project.api.max_retries:
                    self.ledger.record(endpoint, image_sha256, f"http_{status}", note=f"attempt={attempt}")
                    time.sleep(min(60.0, 2.0**attempt))
                    continue
                # Do not retry authentication/validation failures. Retrying a
                # 401 or a bad enum only burns quota and hides the bug.
                if status >= 400:
                    self.ledger.record(endpoint, image_sha256, f"http_{status}", note="non_retryable")
                    raise KimHanNomError(
                        f"{endpoint}: HTTP {status}: {response.text[:300]!r}"
                    )
                raw = response.json()
                self.ledger.record(endpoint, image_sha256, f"http_{status}")
                if not isinstance(raw, dict):
                    raise KimHanNomError("API response is not a JSON object")
                if not _success_code(raw.get("code")):
                    message = raw.get("message")
                    raise ApiBusinessError(f"{endpoint}: {raw.get('code')}: {message}")
                data = raw.get("data") or {}
                if not isinstance(data, dict):
                    raise KimHanNomError(f"{endpoint}: data is not an object")
                result = ApiResponse(endpoint=endpoint, data=data, raw=raw)
                if use_cache and image_sha256 and cache_params is not None:
                    self._save_cache(self._cache_key(endpoint, image_sha256, cache_params), result)
                return result
            except ApiBusinessError:
                # Deterministic business error: no retry, no repeated quota.
                raise
            except KimHanNomError:
                raise
            except Exception as exc:  # noqa: BLE001 - transport/parse errors are retried
                last_error = exc
                if attempt >= self.project.api.max_retries:
                    break
                time.sleep(min(60.0, 2.0**attempt))
        raise KimHanNomError(f"{endpoint} failed after retries: {last_error}") from last_error

    def upload(
        self,
        image_path: str | Path,
        image_sha256: str,
        *,
        force: bool = False,
    ) -> str:
        path = Path(image_path)
        if not force:
            cached = self._load_uploaded_name(image_sha256)
            if cached:
                return cached
        # Read once as bytes. A file handle would be exhausted on retry.
        data = path.read_bytes()
        response = self._request(
            "image-upload",
            files={"image_file": (path.name, data, "image/jpeg")},
            image_sha256=image_sha256,
            use_cache=False,
        )
        file_name = response.data.get("file_name")
        if not file_name:
            raise KimHanNomError("image-upload returned no file_name")
        self._save_uploaded_name(image_sha256, str(file_name))
        return str(file_name)

    def classify(self, file_name: str, image_sha256: str) -> ApiResponse:
        return self._request(
            "structure-classification",
            json_payload={
                "file_name": file_name,
                # v2.1 guideline (p.4): 0 = server auto-detect. The API
                # manual's parameter table omits these; the server rejects
                # requests without them (code 000108, verified 2026-11-08).
                "ocr_id": 0,
                "lang_type": 0,
                "reading_direction": 0,
            },
            image_sha256=image_sha256,
            # Classification is a function of the image, not of the temporary
            # server-side file_name. Omitting it makes the cache reusable.
            cache_params={"ocr_id": 0, "lang_type": 0, "reading_direction": 0},
        )

    def ocr(
        self,
        file_name: str,
        image_sha256: str,
        *,
        ocr_id: int,
        lang_type: int,
        reading_direction: int = 1,
        epitaph: int = 0,
        tag: str | None = None,
    ) -> ApiResponse:
        payload: dict[str, Any] = {
            "ocr_id": int(ocr_id),
            "lang_type": int(lang_type),
            "reading_direction": int(reading_direction),
            "epitaph": int(epitaph),
            "file_name": file_name,
            "tag": tag,
        }
        cache_params = {
            "ocr_id": int(ocr_id),
            "lang_type": int(lang_type),
            "reading_direction": int(reading_direction),
            "epitaph": int(epitaph),
            "tag": tag,
        }
        return self._request(
            "image-ocr",
            json_payload=payload,
            image_sha256=image_sha256,
            cache_params=cache_params,
        )

    def recognize(
        self,
        file_name: str,
        image_sha256: str,
        *,
        ocr_id: int,
        lang_type: int,
        reading_direction: int = 1,
    ) -> ApiResponse:
        payload = {
            "ocr_id": int(ocr_id),
            "lang_type": int(lang_type),
            "reading_direction": int(reading_direction),
            "file_name": file_name,
        }
        cache_params = {
            "ocr_id": int(ocr_id),
            "lang_type": int(lang_type),
            "reading_direction": int(reading_direction),
        }
        return self._request(
            "image-rec",
            json_payload=payload,
            image_sha256=image_sha256,
            cache_params=cache_params,
        )

    @staticmethod
    def _extract_boxes(
        data: dict[str, Any],
    ) -> tuple[list[str], list[Any], list[float | None]]:
        """Split the image-ocr data into (texts, boxes, confidences).

        Documented shape (API manual v2026-10-10, ImageOcrData), verified
        live on 2026-11-08:

            result_ocr_text: list[str]
            result_bbox:     list of [points, [transcription, confidence]],
                             matched by index with result_ocr_text

        The guideline-mentioned shape (details.details, a list of
        {"transcription", "points", "difficult"}) is equally present on the
        live server. ``points`` and per-box confidence are taken from
        whichever shape is found; ``difficult`` is taken from
        details.details when available.
        """
        texts = data.get("result_ocr_text")
        boxes = data.get("result_bbox")
        details = data.get("details")
        details_list = None
        if isinstance(details, dict):
            details_list = details.get("details")
        if isinstance(details_list, list):
            difficult = [item.get("difficult") if isinstance(item, dict) else None for item in details_list]
        else:
            difficult = None

        if texts is not None or boxes is not None:
            text_list = [texts] if isinstance(texts, str) else list(texts or [])
            box_list = [boxes] if isinstance(boxes, dict) else list(boxes or [])
            points_out: list[Any] = []
            confidences: list[float | None] = []
            for item in box_list:
                points: Any = item
                confidence: float | None = None
                meta: Any = None
                # [points, [transcription, confidence]] nesting (live shape).
                if (
                    isinstance(item, (list, tuple))
                    and len(item) == 2
                    and isinstance(item[0], list)
                ):
                    points, meta = item
                if isinstance(meta, (list, tuple)):
                    if len(meta) >= 2 and isinstance(meta[1], (int, float)):
                        confidence = float(meta[1])
                elif isinstance(meta, dict):
                    raw_conf = meta.get("confidence") or meta.get("score")
                    if isinstance(raw_conf, (int, float)):
                        confidence = float(raw_conf)
                points_out.append(points)
                confidences.append(confidence)
            return list(text_list), points_out, confidences

        if isinstance(details_list, list):
            texts_out: list[str] = []
            points_out = []
            for item in details_list:
                if isinstance(item, dict):
                    texts_out.append(str(item.get("transcription", "")))
                    points_out.append(item.get("points"))
                else:
                    texts_out.append("")
                    points_out.append(None)
            return texts_out, points_out, [None] * len(texts_out)
        return [], [], []

    def recognize_page(self, page: PageRecord, script: str) -> OCRResult:
        if not self.is_available():
            raise OCRUnavailable(f"Kim Hán Nôm unavailable: set {self.project.api.token_env}")
        file_name = self.upload(page.path, page.sha256)
        try:
            classification = self.classify(file_name, page.sha256)
            cdata = classification.data
            ocr_id = int(cdata.get("ocr_id", 1) or 1)
            lang_type = 2 if script == "nom" else 1
            reading_direction = int(cdata.get("reading_direction", 1) or 1)
            response = self.ocr(
                file_name,
                page.sha256,
                ocr_id=ocr_id,
                lang_type=lang_type,
                reading_direction=reading_direction,
            )
        except ApiBusinessError:
            # A cached server-side file_name can expire. Re-upload exactly
            # once, then let a second business error surface unchanged.
            file_name = self.upload(page.path, page.sha256, force=True)
            classification = self.classify(file_name, page.sha256)
            cdata = classification.data
            ocr_id = int(cdata.get("ocr_id", 1) or 1)
            lang_type = 2 if script == "nom" else 1
            reading_direction = int(cdata.get("reading_direction", 1) or 1)
            response = self.ocr(
                file_name,
                page.sha256,
                ocr_id=ocr_id,
                lang_type=lang_type,
                reading_direction=reading_direction,
            )
        warnings: list[str] = []
        if script == "nom" and cdata.get("is_sino_nom") is False:
            warnings.append("API_CLASSIFIED_NOT_SINO_NOM")
        texts, boxes, confidences = self._extract_boxes(response.data)
        difficulty: list[Any] | None = None
        details = response.data.get("details")
        if isinstance(details, dict) and isinstance(details.get("details"), list):
            items = details["details"]
            if len(items) == len(texts):
                difficulty = [item.get("difficult") if isinstance(item, dict) else None for item in items]
        lines: list[OCRLine] = []
        if len(texts) != len(boxes):
            warnings.append(f"OCR_TEXT_BBOX_COUNT_MISMATCH:{len(texts)}:{len(boxes)}")
        for index, (text, box) in enumerate(zip(texts, boxes)):
            if not text:
                continue
            if box is None:
                warnings.append("OCR_LINE_WITHOUT_BBOX")
                continue
            try:
                quad = points_to_quad(box)
            except ValueError as exc:
                warnings.append(f"BBOX_INVALID:{exc}")
                continue
            confidence = confidences[index] if index < len(confidences) else None
            line_difficult = difficulty[index] if difficulty is not None else None
            lines.append(
                OCRLine(text=str(text), points=quad, confidence=confidence, script=script, difficult=line_difficult)
            )
        if not lines:
            warnings.append("OCR_EMPTY")
        return OCRResult(
            book_id=page.book_id,
            page_no=page.page_no,
            image_name=page.image_name,
            image_sha256=page.sha256,
            engine=self.name,
            lines=lines,
            raw=response.raw,
            warnings=sorted(set(warnings)),
        )
