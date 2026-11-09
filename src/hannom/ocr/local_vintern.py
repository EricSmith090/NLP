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
import time
from pathlib import Path

from ..models import OCRLine, OCRResult, PageRecord
from .base import OCREngine, OCRUnavailable

_IMAGENET_MEAN = (0.485, 0.456, 0.406)
_IMAGENET_STD = (0.229, 0.224, 0.225)
_PROMPT = (
    "<image>\nTrích xuất toàn bộ văn bản tiếng Việt có trong ảnh. "
    "Chỉ trả về phần văn bản, mỗi dòng một dòng, theo đúng thứ tự từ trên xuống dưới."
)


class VinternEngine(OCREngine):
    name = "vintern_1b_v2"

    def __init__(self, model_id: str = "5CD-AI/Vintern-1B-v2", max_num: int = 12, max_new_tokens: int = 2048):
        self.model_id = model_id
        self.max_num = max_num
        self.max_new_tokens = max_new_tokens
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
        self._model = AutoModel.from_pretrained(
            self.model_id,
            torch_dtype=torch.bfloat16,
            low_cpu_mem_usage=True,
            trust_remote_code=True,
        ).eval().cuda()
        self._tokenizer = AutoTokenizer.from_pretrained(
            self.model_id, trust_remote_code=True, use_fast=False
        )
        print(f"[{self.name}] model loaded in {time.time() - t0:.1f}s")
        return self._model, self._tokenizer

    @staticmethod
    def _load_image(page_path):
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
        min_num, max_num = 1, 12
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

    def _generate_on_image(self, image_path: str | Path, model, tokenizer):
        """Generate OCR text for one image file. Returns the raw stripped text."""
        import torch  # type: ignore

        pixel_values = self._load_image(str(image_path)).to(torch.bfloat16).cuda()
        generation_config = dict(
            max_new_tokens=self.max_new_tokens,
            do_sample=False,
            num_beams=1,
            repetition_penalty=1.2,
        )
        response, _ = model.chat(
            tokenizer, pixel_values, _PROMPT, generation_config, history=None, return_history=True
        )
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

        pixel_values = self._load_image(str(page.path)).to(torch.bfloat16).cuda()
        generation_config = dict(
            max_new_tokens=self.max_new_tokens,
            do_sample=False,
            num_beams=1,
            repetition_penalty=1.2,
        )
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
