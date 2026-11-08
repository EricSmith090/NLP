"""Capture and validate the mandatory report screenshots.

The guideline requires appendix screenshots of PPOCRLabel (Nôm and Quốc ngữ),
the XLSX opened, and the CSV opened. Screenshots are evidence, so this tool
never generates placeholder images: it captures what is currently on screen
or fails.

Usage:
    # Open PPOCRLabel on a real Nôm page, then run:
    python tools/capture_screenshots.py capture \
        --output artifacts/screenshots/ppocrlabel_nom.png --delay 5

    # Check every path configured in configs/report.yaml:
    python tools/capture_screenshots.py check

    # Print the configured slots:
    python tools/capture_screenshots.py slots
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from PIL import Image, ImageGrab, ImageStat  # noqa: E402
import yaml  # noqa: E402

REQUIRED_CAPTION_TOKENS = ("PPOCRLabel", "Nôm", "XLSX", "CSV")
MIN_WIDTH = 800
MIN_HEIGHT = 500
MIN_STDDEV = 2.0
MIN_RANGE = 12


def _load_screenshots(config: Path) -> list[dict[str, Any]]:
    raw = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    return list(raw.get("screenshots", []) or [])


def check_image(path: Path) -> list[str]:
    issues: list[str] = []
    if not path.exists():
        return [f"missing: {path}"]
    try:
        with Image.open(path) as im:
            width, height = im.size
            grayscale = im.convert("L")
            stats = ImageStat.Stat(grayscale)
            stddev = float(stats.stddev[0])
            low, high = grayscale.getextrema()
    except Exception as exc:  # noqa: BLE001
        return [f"unreadable: {path}: {type(exc).__name__}: {exc}"]
    if width < MIN_WIDTH or height < MIN_HEIGHT:
        issues.append(
            f"too small: {path} is {width}x{height}; need at least "
            f"{MIN_WIDTH}x{MIN_HEIGHT}"
        )
    if stddev < MIN_STDDEV or (high - low) < MIN_RANGE:
        issues.append(
            f"looks blank: {path} stddev={stddev:.2f} range={high - low}; "
            "capture the actual application window"
        )
    return issues


def _resolve(path_value: str) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else (ROOT / path)


def cmd_slots(args: argparse.Namespace) -> int:
    screenshots = _load_screenshots(_resolve(args.config))
    if not screenshots:
        print(f"no screenshots configured in {args.config}")
        return 1
    for item in screenshots:
        required = "required" if item.get("required", True) else "optional"
        print(f"{item.get('caption', 'Screenshot')}\n  {item.get('path', '')} ({required})")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    config = _resolve(args.config)
    screenshots = _load_screenshots(config)
    issues: list[str] = []
    if not screenshots:
        issues.append(f"no screenshots configured in {config}")
    captions = " ".join(str(item.get("caption", "")) for item in screenshots)
    for token in REQUIRED_CAPTION_TOKENS:
        if token not in captions:
            issues.append(f"caption category missing: {token}")
    for item in screenshots:
        if not bool(item.get("required", True)):
            continue
        path = _resolve(str(item.get("path", "")))
        for problem in check_image(path):
            issues.append(f"{item.get('caption', 'Screenshot')}: {problem}")

    if issues:
        print(f"FAIL: {len(issues)} screenshot issue(s)")
        for issue in issues:
            print(f"  - {issue}")
        print("\nCapture the real windows with `capture`, then rerun `check`.")
        return 1
    print(f"PASS: {len(screenshots)} configured screenshot(s) look usable")
    for item in screenshots:
        path = _resolve(str(item.get("path", "")))
        with Image.open(path) as im:
            print(f"  {path} {im.size[0]}x{im.size[1]}")
    return 0


def cmd_capture(args: argparse.Namespace) -> int:
    output = _resolve(args.output)
    if output.exists() and not args.force:
        print(f"refusing to overwrite {output}; pass --force to replace it")
        return 1
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.delay > 0:
        print(f"capturing the full screen in {args.delay}s; switch to the target window now")
        for remaining in range(args.delay, 0, -1):
            print(f"  {remaining}...", flush=True)
            time.sleep(1)
    try:
        image = ImageGrab.grab(all_screens=True)
    except Exception as exc:  # noqa: BLE001
        print(f"full-screen capture failed ({exc}); trying the primary screen")
        image = ImageGrab.grab()
    image.save(output, format="PNG")
    issues = check_image(output)
    if issues:
        print(f"captured {output} but it failed validation:")
        for issue in issues:
            print(f"  - {issue}")
        return 1
    with Image.open(output) as im:
        print(f"captured {output} ({im.size[0]}x{im.size[1]})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    capture = sub.add_parser("capture", help="capture the current screen to a PNG")
    capture.add_argument("--output", required=True, help="destination PNG path")
    capture.add_argument("--delay", type=int, default=5, help="countdown seconds (default 5)")
    capture.add_argument("--force", action="store_true", help="overwrite an existing PNG")
    capture.set_defaults(func=cmd_capture)

    check = sub.add_parser("check", help="validate configured screenshots")
    check.add_argument("--config", default="configs/report.yaml")
    check.set_defaults(func=cmd_check)

    slots = sub.add_parser("slots", help="list configured screenshot slots")
    slots.add_argument("--config", default="configs/report.yaml")
    slots.set_defaults(func=cmd_slots)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
