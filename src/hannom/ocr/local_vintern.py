"""Lazy local Vintern-1B-v2 adapter for Quốc ngữ.

Integration decision (2026-11-08, based on the benchmark):

* PaddleOCR's `ch`/`latin` recognition models cannot read the archaic
  Catholic-press Quốc ngữ in these books; they systematically drop Vietnamese
  tone marks (128 distinct affected tokens in Book 3, e.g. ``dēn`` for
  ``đến``, ``muōn`` for ``muốn``).
* Full-page Vintern-1B-v2 transcription is near-perfect on this print
  (verified on pages 11 and 41: correct circumflexes, tildes, and archaic
  spellings) and is fast enough on an 8 GB RTX 4060 (~35 s/page).
* Vintern does not emit per-line boxes and cannot be relied on for line
  crops (it narrates/hallucinates outside its natural full-page mode), so
  per the guideline ("đánh 1 box cho toàn trang") this adapter emits a
  single full-page box per image. Labels are produced from these lines.

Care points:

* The adapter only claims GPU availability when torch+transformers import and
  ``torch.cuda.is_available()``; otherwise it reports itself unavailable.
* No per-line confidence is fabricated; lines carry ``confidence=None``.
* The Nôm (ch/) path is untouched: Kim Hán Nôm API.
"""

from __future__ import annotations

import importlib.util
import re
import time
from pathlib import Path

from ..models import OCRLine, OCRResult, PageRecord
from .base import OCREngine, OCRUnavailable

_IMAGENET_MEAN = (0.485, 0.456, 0.406)
_IMAGENET_STD = (0.229, 0.224, 0.225)
# Pinned to the exact snapshot the pipeline was benchmarked and run against
# (refs/main in the local HF cache, verified 2026-11-13). Update only with a
# fresh benchmark + review.
_VINTERN_REVISION = "c3f01cf5b55816c092fb493babc672b0dc33c8bc"
# Vintern-1B-v3.5 (InternViT-300M + Qwen2.5-0.5B), benchmarked 2026-11-19 on
# 25 QN pages of the 3 books against v2 (Doc/FIX_PLAN_v24.md T2.1): phonetic
# recall vs the Nôm partner 0.218 -> 0.707 on failing pages, 0.855 -> 0.897 on
# normal pages, with the model-card generation config below.
_VINTERN35_REVISION = "b98f263eab246eb5269ade64edbdca8a887dc44d"


def _max_time_criteria(budget: float):
    """StoppingCriteriaList enforcing a wall-clock budget for one generation.

    transformers 4.46 has no built-in wall-clock stopping criterion; this is
    the documented extension point (generate's ``stopping_criteria`` kwarg).
    Imported lazily so importing this module never pulls transformers.
    """
    from transformers.generation import StoppingCriteria, StoppingCriteriaList

    import time as _time

    class _MaxTime(StoppingCriteria):
        def __init__(self, max_time_seconds: float) -> None:
            super().__init__()
            self.start = _time.time()
            self.budget = float(max_time_seconds)

        def __call__(self, input_ids, scores=None, **_kwargs):  # noqa: ANN001
            return (_time.time() - self.start) > self.budget

    return StoppingCriteriaList([_MaxTime(budget)])
_PROMPT = (
    "<image>\nTrích xuất toàn bộ văn bản tiếng Việt có trong ảnh. "
    "Chỉ trả về phần văn bản, mỗi dòng một dòng, theo đúng thứ tự từ trên xuống dưới."
)


class VinternEngine(OCREngine):
    name = "vintern_1b_v2"

    def __init__(
        self,
        model_id: str = "5CD-AI/Vintern-1B-v2",
        max_num: int = 12,
        max_new_tokens: int = 2048,
        max_time_seconds: float = 300.0,
        *,
        revision: str = _VINTERN_REVISION,
        num_beams: int = 1,
        repetition_penalty: float = 1.2,
        use_flash_attn: bool | None = None,
    ):
        self.model_id = model_id
        self.revision = revision
        self.max_num = max_num
        self.max_new_tokens = max_new_tokens
        self.num_beams = int(num_beams)
        self.repetition_penalty = float(repetition_penalty)
        # None = do not pass the kwarg (v2 behaviour); False forces eager
        # attention (v3.5's config otherwise requests flash-attention-2, which
        # is not installed on the Windows target and crashes the load).
        self.use_flash_attn = use_flash_attn
        # Wall-clock budget per model.chat call; a hung CUDA generation must
        # not block the pipeline forever (operator-adjustable).
        self.max_time_seconds = float(max_time_seconds)
        self._model = None
        self._tokenizer = None

    def is_available(self) -> bool:
        if importlib.util.find_spec("torch") is None:
            return False
        if importlib.util.find_spec("transformers") is None:
            return False
        import torch  # type: ignore

        return bool(torch.cuda.is_available())

    def _load(self):
        if self._model is not None:
            return self._model, self._tokenizer
        if not self.is_available():
            raise OCRUnavailable(
                "Vintern-1B-v2 requires torch+transformers and a CUDA-capable GPU. "
                "Install the OCR extra (see pyproject.toml) and retry."
            )
        import os

        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        import torch  # type: ignore
        from transformers import AutoModel, AutoTokenizer  # type: ignore

        t0 = time.time()
        extra = {} if self.use_flash_attn is None else {"use_flash_attn": bool(self.use_flash_attn)}
        self._model = AutoModel.from_pretrained(
            self.model_id,
            revision=self.revision,
            torch_dtype=torch.bfloat16,
            low_cpu_mem_usage=True,
            trust_remote_code=True,
            **extra,
        ).eval().cuda()
        self._tokenizer = AutoTokenizer.from_pretrained(
            self.model_id, revision=self.revision, trust_remote_code=True, use_fast=False
        )
        print(f"[{self.name}] model loaded in {time.time() - t0:.1f}s")
        return self._model, self._tokenizer

    @staticmethod
    def _load_image(page_path, max_num: int = 12):
        import torch  # type: ignore
        import torchvision.transforms as T  # type: ignore
        from PIL import Image  # type: ignore
        from torchvision.transforms.functional import InterpolationMode  # type: ignore

        def build_transform(input_size):
            return T.Compose([
                T.Lambda(lambda img: img.convert("RGB") if img.mode != "RGB" else img),
                T.Resize((input_size, input_size), interpolation=InterpolationMode.BICUBIC),
                T.ToTensor(),
                T.Normalize(mean=_IMAGENET_MEAN, std=_IMAGENET_STD),
            ])

        def find_closest_aspect_ratio(aspect_ratio, target_ratios, width, height, image_size):
            best_ratio_diff = float("inf")
            best_ratio = (1, 1)
            area = width * height
            for ratio in target_ratios:
                target_aspect_ratio = ratio[0] / ratio[1]
                ratio_diff = abs(aspect_ratio - target_aspect_ratio)
                if ratio_diff < best_ratio_diff:
                    best_ratio_diff = ratio_diff
                    best_ratio = ratio
                elif ratio_diff == best_ratio_diff:
                    if area > 0.5 * image_size * image_size * ratio[0] * ratio[1]:
                        best_ratio = ratio
            return best_ratio

        image = Image.open(page_path).convert("RGB")
        image_size = 448
        min_num = 1
        max_num = max(1, int(max_num))
        orig_width, orig_height = image.size
        aspect_ratio = orig_width / orig_height
        target_ratios = set(
            (i, j)
            for n in range(min_num, max_num + 1)
            for i in range(1, n + 1)
            for j in range(1, n + 1)
            if i * j <= max_num and i * j >= min_num
        )
        target_ratios = sorted(target_ratios, key=lambda x: x[0] * x[1])
        target_aspect_ratio = find_closest_aspect_ratio(
            aspect_ratio, target_ratios, orig_width, orig_height, image_size
        )
        target_width = image_size * target_aspect_ratio[0]
        target_height = image_size * target_aspect_ratio[1]
        blocks = target_aspect_ratio[0] * target_aspect_ratio[1]
        resized = image.resize((target_width, target_height))
        processed = []
        for i in range(blocks):
            box = (
                (i % (target_width // image_size)) * image_size,
                (i // (target_width // image_size)) * image_size,
                ((i % (target_width // image_size)) + 1) * image_size,
                ((i // (target_width // image_size)) + 1) * image_size,
            )
            processed.append(resized.crop(box))
        if len(processed) != 1:
            processed.append(image.resize((image_size, image_size)))
        transform = build_transform(image_size)
        return torch.stack([transform(img) for img in processed])

    def _generation_config(self) -> dict:
        config = {
            "max_new_tokens": self.max_new_tokens,
            "do_sample": False,
            "num_beams": self.num_beams,
            "repetition_penalty": self.repetition_penalty,
        }
        try:
            config["stopping_criteria"] = _max_time_criteria(self.max_time_seconds)
        except Exception as exc:  # transformers API drift: degrade, never crash
            print(
                f"[{self.name}] time watchdog unavailable ({type(exc).__name__}: {exc}); continuing without it",
                flush=True,
            )
        return config

    def _generate_on_image(self, image_path: str | Path, model, tokenizer, max_num: int | None = None):
        """Generate OCR text for one image file. Returns the raw stripped text."""
        import torch  # type: ignore

        tiles = self.max_num if max_num is None else max_num
        pixel_values = self._load_image(str(image_path), tiles).to(torch.bfloat16).cuda()
        generation_config = self._generation_config()
        try:
            response, _ = model.chat(
                tokenizer, pixel_values, _PROMPT, generation_config, history=None, return_history=True
            )
        finally:
            # Release cached blocks after every call: with 3 beams and eager
            # attention the 13-tile halves fragment the allocator, and on
            # Windows a full 8 GB card silently spills to system RAM
            # (one Tap2 page took 907 s on 2026-11-19).
            del pixel_values
            torch.cuda.empty_cache()
        return (response or "").strip()

    def _band_retry(self, page: PageRecord) -> tuple[str, dict[str, str]]:
        """Re-transcribe a page as three horizontal bands + keep merge.

        Vintern fails silently on 4/60 Book 3 pages (see the 2026-11-09
        refresh: 0016, 0032, 0040, 0056 all output only a page marker).
        With the band fallback the full-page failure becomes recoverable
        text. The merged result is only used if it is decisively longer
        than the full-page one, so title pages stay untouched.
        """
        from PIL import Image

        parts: list[str] = []
        path = Path(str(page.path))
        img = Image.open(path).convert("RGB")
        w, h = img.size
        pieces = {"top": (0, 0, w, h // 3), "mid": (0, h // 3, w, 2 * h // 3), "bot": (0, 2 * h // 3, w, h)}
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            Model, Tokenizer = self._load()
            for label, box in pieces.items():
                crop = img.crop(box)
                crop_path = Path(tmp) / f"band_{label}.jpg"
                crop.save(crop_path, quality=95)
                try:
                    text = self._generate_on_image(crop_path, Model, Tokenizer)
                except Exception as exc:  # bands are best-effort recovery
                    print(f"[{self.name}] band {label} failed: {type(exc).__name__}: {exc}")
                    text = ""
                parts.append(text)
        # Drop band outputs that are nothing but the page marker the full
        # page already failed on (they carry no information).
        def useful(s: str) -> bool:
            import re

            s = s.strip()
            if not s:
                return False
            if len(s) <= 20 and re.fullmatch(r"[\W\d\s()\-]{1,20}", s):
                return False
            return True

        merged_parts = [t for t in parts if useful(t)]
        merged = "\n".join(dict.fromkeys(merged_parts)).strip()
        meta = dict(zip(
            ("top", "mid", "bot"),
            [p[:200] for p in parts],
        ))
        return merged, meta

    def recognize_page(self, page: PageRecord, script: str) -> OCRResult:
        model, tokenizer = self._load()
        import torch  # type: ignore

        pixel_values = self._load_image(str(page.path), self.max_num).to(torch.bfloat16).cuda()
        generation_config = self._generation_config()
        t0 = time.time()
        response, _ = model.chat(tokenizer, pixel_values, _PROMPT, generation_config, history=None, return_history=True)
        elapsed = time.time() - t0
        text = (response or "").strip()
        width = float(page.width)
        height = float(page.height)
        rect = ((0.0, 0.0), (width, 0.0), (width, height), (0.0, height))
        warnings: list[str] = []
        band_meta = None
        if len(text) < 40:
            merged, band_meta = self._band_retry(page)
            if len(merged) >= 2 * max(1, len(text)):
                text = merged
                warnings.append("BAND_RETRY_AFTER_FULLPAGE_FAILURE")
        lines: list[OCRLine] = []
        if text:
            lines.append(OCRLine(text=text, points=rect, confidence=None, script=script))
        if not lines:
            warnings.append("OCR_EMPTY")
        raw = {"prompt": _PROMPT, "page_size": [page.width, page.height], "seconds": round(elapsed, 2)}
        if band_meta:
            raw["band_retry"] = band_meta
        return OCRResult(
            book_id=page.book_id,
            page_no=page.page_no,
            image_name=page.image_name,
            image_sha256=page.sha256,
            engine=self.name,
            lines=lines,
            raw=raw,
            warnings=warnings,
        )


# --- Vintern-1B-v3.5 -------------------------------------------------------

_SYLLABLE_RE = re.compile(r"[^\W\d_]+")
# Whole-line model narration seen in v2/v3.5 output; never real book text.
_META_LINE_RE = re.compile(
    r"^\s*(?:```[\w-]*"
    r"|(?:phần |đoạn )?văn bản (?:được |đã được )?(?:nhận dạng|trích xuất)[^\n]{0,40}"
    r"|dưới đây là[^\n]{0,60}"
    r"|(?:và )?dòng cuối cùng là[^\n]{0,20})\s*$",
    re.IGNORECASE,
)
_MIN_SYLLABLES = 40
_REPEAT_8GRAM = 4


def qn_text_quality(text: str) -> dict:
    """Intrinsic quality signals of one QN transcription (no partner needed).

    ``effective`` counts syllables after skipping every word that starts an
    already-seen 8-gram, so a repetition loop scores low however long it is.
    """
    words = [w.lower() for w in _SYLLABLE_RE.findall(text or "")]
    grams: dict[tuple[str, ...], int] = {}
    for i in range(len(words) - 7):
        g = tuple(words[i : i + 8])
        grams[g] = grams.get(g, 0) + 1
    seen: set[tuple[str, ...]] = set()
    effective = 0
    for i in range(len(words)):
        g = tuple(words[i : i + 8])
        if len(g) == 8 and g in seen:
            continue
        if len(g) == 8:
            seen.add(g)
        effective += 1
    return {
        "syllables": len(words),
        "effective": effective,
        "rep8": max(grams.values()) if grams else 0,
    }


def strip_meta_lines(text: str) -> tuple[str, int]:
    kept, dropped = [], 0
    for line in (text or "").splitlines():
        if _META_LINE_RE.match(line):
            dropped += 1
            continue
        kept.append(line)
    return "\n".join(kept).strip(), dropped


def stitch_overlapping(parts: list[str]) -> str:
    """Join band transcriptions, removing the longest word overlap (≥3 words)."""
    out = (parts[0] if parts else "").split()
    for part in parts[1:]:
        words = part.split()
        best = 0
        for k in range(min(len(out), len(words), 60), 2, -1):
            if [x.lower() for x in out[-k:]] == [x.lower() for x in words[:k]]:
                best = k
                break
        out += words[best:]
    return " ".join(out)


def needs_retry(quality: dict, meta_dropped: int) -> bool:
    return (
        quality["syllables"] < _MIN_SYLLABLES
        or quality["rep8"] >= _REPEAT_8GRAM
        or meta_dropped > 0
    )


def prefer_retry(full: dict, halves: dict) -> bool:
    """Keep the halves candidate only when it is clearly better."""
    if halves["rep8"] >= _REPEAT_8GRAM and full["rep8"] < _REPEAT_8GRAM:
        return False
    return halves["effective"] >= 1.2 * max(1, full["effective"])


def trim_loop(text: str, repeats: int = 3) -> tuple[str, bool]:
    """Cut a repetition loop: keep the text up to the second occurrence of
    the first 8-gram that occurs ``repeats``+ times. The original characters
    (line breaks, hyphens) before the cut are kept as they were."""
    matches = list(_SYLLABLE_RE.finditer(text or ""))
    words = [m.group(0).lower() for m in matches]
    grams: dict[tuple[str, ...], int] = {}
    for i in range(len(words) - 7):
        g = tuple(words[i : i + 8])
        grams[g] = grams.get(g, 0) + 1
    seen: set[tuple[str, ...]] = set()
    for i in range(len(words) - 7):
        g = tuple(words[i : i + 8])
        if g in seen and grams[g] >= repeats:
            return text[: matches[i].start()].rstrip(), True
        seen.add(g)
    return text, False


def _loop_criteria(tokenizer, every: int = 24):
    """Stop generation once every beam is caught in a repetition loop.

    A looping page otherwise runs to max_new_tokens (≈80 s per call with 3
    beams) and returns garbage; the loop tail is trimmed afterwards anyway.
    """
    import torch  # type: ignore
    from transformers.generation import StoppingCriteria

    class _Loop(StoppingCriteria):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def __call__(self, input_ids, scores=None, **_kwargs):  # noqa: ANN001
            self.calls += 1
            done = torch.zeros(input_ids.shape[0], dtype=torch.bool, device=input_ids.device)
            if self.calls % every:
                return done
            for i, row in enumerate(input_ids):
                text = tokenizer.decode(row, skip_special_tokens=True)
                if qn_text_quality(text)["rep8"] >= _REPEAT_8GRAM:
                    done[i] = True
            return done

    return _Loop()


class Vintern35Engine(VinternEngine):
    """Vintern-1B-v3.5 with the model-card generation config.

    Full page first (6 tiles + thumbnail on the 800x1135 scans). When the
    output is short, loops, or narrates, retry on two horizontal halves that
    overlap 15 % and stitch them; keep the retry only if clearly better.
    Partner-aware checks (phonetic recall vs the Nôm page) run later in
    ``hannom.qnquality``.
    """

    name = "vintern_1b_v3_5"
    overlap = 0.15

    def __init__(self, max_time_seconds: float = 180.0):
        super().__init__(
            model_id="5CD-AI/Vintern-1B-v3_5",
            max_num=6,
            max_new_tokens=2048,
            max_time_seconds=max_time_seconds,
            revision=_VINTERN35_REVISION,
            num_beams=3,
            repetition_penalty=2.5,
            use_flash_attn=False,
        )

    def _generation_config(self) -> dict:
        config = super()._generation_config()
        if self._tokenizer is not None:
            try:
                from transformers.generation import StoppingCriteriaList

                criteria = list(config.get("stopping_criteria") or [])
                criteria.append(_loop_criteria(self._tokenizer))
                config["stopping_criteria"] = StoppingCriteriaList(criteria)
            except Exception as exc:  # transformers API drift: degrade, never crash
                print(f"[{self.name}] loop stopper unavailable ({type(exc).__name__}: {exc})", flush=True)
        return config

    def _read(self, image_path, model, tokenizer, max_num: int | None = None) -> tuple[str, dict]:
        """One generation -> (text without narration or loop tail, signals before trimming)."""
        text, meta = strip_meta_lines(self._generate_on_image(image_path, model, tokenizer, max_num=max_num))
        info = dict(qn_text_quality(text), meta_dropped=meta, loop_trimmed=False)
        if info["rep8"] >= _REPEAT_8GRAM:
            text, info["loop_trimmed"] = trim_loop(text)
        return text, info

    def _halves(self, page: PageRecord) -> tuple[list[str], list[dict]]:
        import tempfile

        from PIL import Image

        img = Image.open(Path(str(page.path))).convert("RGB")
        w, h = img.size
        band = h / (2 - self.overlap)
        stride = band * (1 - self.overlap)
        model, tokenizer = self._load()
        parts: list[str] = []
        infos: list[dict] = []
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(2):
                top = int(i * stride)
                crop = img.crop((0, top, w, min(h, int(top + band))))
                crop_path = Path(tmp) / f"half_{i}.png"
                crop.save(crop_path)
                try:
                    # 12 tiles per half (4x3 grid on a 800x613 crop), as benchmarked.
                    text, info = self._read(crop_path, model, tokenizer, max_num=12)
                except Exception as exc:  # retry is best-effort
                    print(f"[{self.name}] half {i} failed: {type(exc).__name__}: {exc}", flush=True)
                    text, info = "", {"error": f"{type(exc).__name__}: {exc}"}
                parts.append(text)
                infos.append(info)
        return parts, infos

    def recognize_page(self, page: PageRecord, script: str) -> OCRResult:
        model, tokenizer = self._load()
        t0 = time.time()
        text, full_info = self._read(page.path, model, tokenizer)
        warnings: list[str] = []
        raw: dict = {
            "model": self.model_id,
            "revision": self.revision,
            "prompt": _PROMPT,
            "generation": {"num_beams": self.num_beams, "repetition_penalty": self.repetition_penalty,
                           "max_new_tokens": self.max_new_tokens, "max_num": self.max_num},
            "page_size": [page.width, page.height],
            "full": full_info,
        }
        trimmed = full_info["loop_trimmed"]
        if full_info["meta_dropped"]:
            warnings.append("QN_META_STRIPPED")
        if needs_retry(full_info, full_info["meta_dropped"]):
            parts, infos = self._halves(page)
            merged = stitch_overlapping(parts)
            halves_q = qn_text_quality(merged)
            raw["halves"] = dict(halves_q, parts=[p[:200] for p in parts], part_info=infos)
            if prefer_retry(qn_text_quality(text), halves_q):
                text = merged
                trimmed = any(i.get("loop_trimmed") for i in infos)
                warnings.append("QN_HALVES_RETRY")
        if trimmed:
            warnings.append("QN_LOOP_TRIMMED")
        final_q = qn_text_quality(text)
        raw["final"] = final_q
        if final_q["rep8"] >= _REPEAT_8GRAM:
            warnings.append(f"QN_REPETITION:{final_q['rep8']}")
        raw["seconds"] = round(time.time() - t0, 2)
        width, height = float(page.width), float(page.height)
        rect = ((0.0, 0.0), (width, 0.0), (width, height), (0.0, height))
        lines = [OCRLine(text=text, points=rect, confidence=None, script=script)] if text else []
        if not lines:
            warnings.append("OCR_EMPTY")
        return OCRResult(
            book_id=page.book_id,
            page_no=page.page_no,
            image_name=page.image_name,
            image_sha256=page.sha256,
            engine=self.name,
            lines=lines,
            raw=raw,
            warnings=warnings,
        )
