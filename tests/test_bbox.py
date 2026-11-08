from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from hannom.labels import (
    points_to_quad,
    validate_label_txt,
    write_file_state,
    write_label_txt,
)


def test_points_to_quad_accepts_flat_and_rotated():
    assert points_to_quad([1, 2, 10, 20]) == ((1, 2), (10, 2), (10, 20), (1, 20))
    rotated = points_to_quad([[1, 2], [3, 4], [5, 6], [7, 8]])
    assert len(rotated) == 4
    polygon = points_to_quad([[0, 0], [10, 0], [10, 10], [0, 10], [2, 2]])
    assert polygon == ((0, 0), (10, 0), (10, 10), (0, 10))


def _image(path: Path) -> None:
    Image.new("RGB", (100, 200), "white").save(path, "JPEG")


def test_label_validation_accepts_four_points_and_state_one(tmp_path: Path):
    image_dir = tmp_path / "ch"
    image_dir.mkdir()
    _image(image_dir / "Book.001.jpg")
    write_label_txt(
        ["Book.001.jpg"],
        {
            "Book.001.jpg": [
                {"transcription": "字", "points": [[1, 2], [30, 2], [30, 80], [1, 80]]}
            ]
        },
        image_dir / "Label.txt",
        "ch",
    )
    write_file_state(["Book.001.jpg"], image_dir / "fileState.txt", "ch", 1)
    result = validate_label_txt(image_dir / "Label.txt", image_dir, "ch", image_dir / "fileState.txt")
    assert result.ok, result.issues


def test_label_validation_rejects_three_points_and_missing_image(tmp_path: Path):
    image_dir = tmp_path / "ch"
    image_dir.mkdir()
    _image(image_dir / "Book.001.jpg")
    label = image_dir / "Label.txt"
    label.write_text(
        'ch/Book.001.jpg\t[{"transcription":"x","points":[[1,2],[3,4],[5,6]]}]\n',
        encoding="utf-8",
    )
    write_file_state(["Book.001.jpg"], image_dir / "fileState.txt", "ch", 1)
    result = validate_label_txt(label, image_dir, "ch", image_dir / "fileState.txt")
    assert not result.ok
    assert any("expected 4" in issue for issue in result.issues)


def test_file_state_zero_is_rejected(tmp_path: Path):
    image_dir = tmp_path / "ch"
    image_dir.mkdir()
    _image(image_dir / "Book.001.jpg")
    write_label_txt(["Book.001.jpg"], {"Book.001.jpg": []}, image_dir / "Label.txt", "ch")
    write_file_state(["Book.001.jpg"], image_dir / "fileState.txt", "ch", 0)
    result = validate_label_txt(image_dir / "Label.txt", image_dir, "ch", image_dir / "fileState.txt")
    assert not result.ok
    assert any("not 1" in issue for issue in result.issues)
