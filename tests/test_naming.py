from __future__ import annotations

from pathlib import Path

import pytest

from hannom.pages import image_name, page_number_str


def test_page_numbers_start_at_one():
    assert page_number_str(1) == "001"
    assert page_number_str(9) == "009"
    assert page_number_str(999) == "999"
    assert page_number_str(1000) == "1000"
    with pytest.raises(ValueError):
        page_number_str(0)


def test_image_name_is_book_stem_plus_page():
    name = image_name("T1_Sửa Lưỡi Quyển", 7)
    assert name == "T1_Sửa Lưỡi Quyển.007.jpg"
    assert name.endswith(".jpg")


def test_image_index_only_when_multiple():
    assert image_name("Book", 7, 1) == "Book.007_1.jpg"
    assert image_name("Book", 7) == "Book.007.jpg"
    with pytest.raises(ValueError):
        image_name("Book", 7, 0)
