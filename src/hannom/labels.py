"""PPOCRLabel Label.txt / fileState.txt generation and validation.

The guideline requires exactly four points per box and a one-line-per-image
mapping. This module is intentionally strict: a label folder either passes
or produces a blocking issue.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from PIL import Image

from .models import OCRLine, OCRResult


@dataclass
class LabelValidation:
    label_path: Path
    state_path: Path | None
    image_count: int = 0
    box_count: int = 0
    issues: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues


def _as_point(value: Any) -> tuple[float, float]:
    if isinstance(value, dict):
        value = [value.get("x"), value.get("y")]
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"point must be [x,y], got {value!r}")
    return float(value[0]), float(value[1])


def points_to_quad(points: Any) -> tuple[tuple[float, float], ...]:
    """Normalise common bbox encodings to exactly four corner points.

    Accepted: four polygon points, a flat [x1,y1,x2,y2], a dict with
    x/y/w/h, or a longer polygon (axis-aligned min/max is used).
    """
    if isinstance(points, dict):
        if {"x", "y", "w", "h"} <= set(points):
            x, y, w, h = float(points["x"]), float(points["y"]), float(points["w"]), float(points["h"])
            points = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
        elif {"x1", "y1", "x2", "y2"} <= set(points):
            points = [points["x1"], points["y1"], points["x2"], points["y2"]]
        else:
            raise ValueError(f"unsupported bbox dict: {points!r}")
    if not isinstance(points, (list, tuple)):
        raise ValueError(f"unsupported points: {points!r}")
    if len(points) == 4 and all(isinstance(p, (int, float)) for p in points):
        x1, y1, x2, y2 = (float(p) for p in points)
        return ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
    pts = [_as_point(p) for p in points]
    if len(pts) == 4:
        return tuple(pts)
    if len(pts) > 4:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x1, x2 = min(xs), max(xs)
        y1, y2 = min(ys), max(ys)
        return ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
    raise ValueError(f"a box needs exactly 4 points, got {len(pts)}")


def clamp_quad(
    points: tuple[tuple[float, float], ...],
    width: int,
    height: int,
) -> tuple[tuple[float, float], ...]:
    out: list[tuple[float, float]] = []
    for x, y in points:
        out.append((min(max(0.0, x), float(max(1, width - 1))), min(max(0.0, y), float(max(1, height - 1)))))
    return tuple(out)


def line_to_box(line: OCRLine, width: int, height: int) -> dict[str, Any]:
    quad = clamp_quad(points_to_quad(line.points), width, height)
    box: dict[str, Any] = {
        "transcription": line.text,
        "points": [[x, y] for x, y in quad],
    }
    if line.difficult is not None:
        box["difficult"] = bool(line.difficult)
    if line.confidence is not None:
        box["confidence"] = float(line.confidence)
    return box


def write_label_txt(
    image_names: Iterable[str],
    boxes_by_image: dict[str, list[dict[str, Any]]],
    path: str | Path,
    folder: str,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for name in image_names:
            boxes = boxes_by_image.get(name, [])
            payload = json.dumps(boxes, ensure_ascii=False, separators=(",", ":"))
            fh.write(f"{folder}/{name}\t{payload}\n")
    return path


def write_file_state(
    image_names: Iterable[str],
    path: str | Path,
    folder: str,
    completed: int = 1,
) -> Path:
    if completed not in (0, 1):
        raise ValueError("fileState values must be 0 or 1")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for name in image_names:
            fh.write(f"{folder}/{name}\t{completed}\n")
    return path


def write_result_labels(
    result: OCRResult,
    image_dir: str | Path,
    label_path: str | Path,
    state_path: str | Path,
    folder: str,
    image_names: list[str] | None = None,
) -> tuple[Path, Path]:
    image_dir = Path(image_dir)
    names = image_names or [p.name for p in sorted(image_dir.glob("*.jpg"))]
    with Image.open(image_dir / result.image_name) as im:
        width, height = im.size
    boxes: dict[str, list[dict[str, Any]]] = {result.image_name: []}
    for line in result.lines:
        if not line.text:
            continue
        boxes[result.image_name].append(line_to_box(line, width, height))
    label = write_label_txt(names, boxes, label_path, folder)
    state = write_file_state(names, state_path, folder, 1)
    return label, state


def parse_label_line(line: str) -> tuple[str, list[dict[str, Any]]]:
    if "\t" not in line:
        raise ValueError("label line is missing a TAB")
    image_path, payload = line.split("\t", 1)
    try:
        boxes = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON box payload: {exc}") from exc
    if not isinstance(boxes, list):
        raise ValueError("box payload must be a JSON array")
    return image_path.strip(), boxes


def read_label_txt(path: str | Path) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    with Path(path).open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            if not line.strip():
                continue
            image_path, boxes = parse_label_line(line.rstrip("\n"))
            if image_path in out:
                raise ValueError(f"{path}:{line_no}: duplicate image path {image_path}")
            out[image_path] = boxes
    return out


def _check_box(box: Any, width: int, height: int, strict_points: bool = True) -> list[str]:
    issues: list[str] = []
    if not isinstance(box, dict):
        return ["box is not an object"]
    transcription = box.get("transcription")
    if not isinstance(transcription, str):
        issues.append("transcription is not a string")
    elif "\n" in transcription or "\r" in transcription:
        issues.append("transcription contains a newline")
    if "points" not in box:
        issues.append("box has no points")
        return issues
    points = box["points"]
    if not isinstance(points, list):
        issues.append("points is not a list")
        return issues
    if strict_points and len(points) != 4:
        issues.append(f"box has {len(points)} points, expected 4")
    for pt in points:
        if not isinstance(pt, (list, tuple)) or len(pt) != 2:
            issues.append(f"invalid point {pt!r}")
            continue
        try:
            x, y = float(pt[0]), float(pt[1])
        except (TypeError, ValueError):
            issues.append(f"non-numeric point {pt!r}")
            continue
        if not (0 <= x <= width and 0 <= y <= height):
            issues.append(f"point ({x},{y}) outside {width}x{height}")
    return issues


def validate_label_txt(
    label_path: str | Path,
    image_dir: str | Path,
    folder: str,
    state_path: str | Path | None = None,
    require_all_images: bool = True,
    strict_points: bool = True,
) -> LabelValidation:
    label_path = Path(label_path)
    image_dir = Path(image_dir)
    state_path = Path(state_path) if state_path else None
    result = LabelValidation(label_path=label_path, state_path=state_path)
    if not label_path.exists():
        result.issues.append(f"missing label file: {label_path}")
        return result
    try:
        boxes_by_image = read_label_txt(label_path)
    except ValueError as exc:
        result.issues.append(str(exc))
        return result

    result.image_count = len(boxes_by_image)
    image_files = {p.name for p in image_dir.glob("*.jpg")}
    expected_prefix = folder.rstrip("/") + "/"
    labelled_names = {
        path[len(expected_prefix) :] if path.startswith(expected_prefix) else path
        for path in boxes_by_image
    }
    if require_all_images:
        missing = sorted(image_files - labelled_names)
        if missing:
            result.issues.append(f"{len(missing)} images have no Label.txt row (e.g. {missing[:3]})")
    for image_path, boxes in boxes_by_image.items():
        if not image_path.startswith(expected_prefix):
            result.issues.append(f"image path does not start with {expected_prefix}: {image_path}")
        name = image_path[len(expected_prefix) :] if image_path.startswith(expected_prefix) else image_path
        image_file = image_dir / name
        if not image_file.exists():
            result.issues.append(f"image does not exist: {image_file}")
            continue
        try:
            with Image.open(image_file) as im:
                width, height = im.size
        except Exception as exc:  # pragma: no cover - defensive
            result.issues.append(f"cannot open image {image_file}: {exc}")
            continue
        for idx, box in enumerate(boxes):
            result.box_count += 1
            for issue in _check_box(box, width, height, strict_points=strict_points):
                result.issues.append(f"{name} box {idx}: {issue}")

    if state_path is not None:
        if not state_path.exists():
            result.issues.append(f"missing fileState file: {state_path}")
        else:
            state_rows: dict[str, str] = {}
            with state_path.open("r", encoding="utf-8") as fh:
                for line_no, line in enumerate(fh, 1):
                    if not line.strip():
                        continue
                    if "\t" not in line:
                        result.issues.append(f"{state_path}:{line_no}: missing TAB")
                        continue
                    path, value = line.rstrip("\n").split("\t", 1)
                    state_rows[path.strip()] = value.strip()
            if set(state_rows) != set(boxes_by_image):
                result.issues.append("fileState image set does not match Label.txt image set")
            bad = [p for p, v in state_rows.items() if v != "1"]
            if bad:
                result.issues.append(f"{len(bad)} fileState rows are not 1 (e.g. {bad[:3]})")
    return result


def filter_boxes_by_script(
    boxes: list[dict[str, Any]],
    script: str,
) -> list[dict[str, Any]]:
    """Keep only boxes tagged with the requested script for mixed pages."""
    tagged = [b for b in boxes if b.get("script") in (script, None)]
    if any(b.get("script") is not None for b in boxes):
        return [b for b in boxes if b.get("script") == script]
    return tagged


def folder_image_names(folder: str | Path) -> list[str]:
    return [p.name for p in sorted(Path(folder).glob("*.jpg"))]
