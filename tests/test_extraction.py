from __future__ import annotations

from pathlib import Path

import pymupdf
from PIL import Image

from hannom.pages import extract_page, image_name


def _make_image(path: Path, color: str) -> None:
    Image.new("RGB", (200, 300), color).save(path, "JPEG")


def test_extract_page_uses_the_image_placed_on_the_page(tmp_path: Path):
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    _make_image(first, "red")
    _make_image(second, "blue")
    pdf = tmp_path / "book.pdf"
    doc = pymupdf.open()
    page1 = doc.new_page(width=200, height=300)
    page1.insert_image(page1.rect, filename=str(first))
    page2 = doc.new_page(width=200, height=300)
    page2.insert_image(page2.rect, filename=str(second))
    doc.save(pdf)
    doc.close()

    doc = pymupdf.open(pdf)
    try:
        out1 = tmp_path / "p1.jpg"
        out2 = tmp_path / "p2.jpg"
        w1, h1, method1, _ = extract_page(doc, 1, out1)
        w2, h2, method2, _ = extract_page(doc, 2, out2)
    finally:
        doc.close()
    assert (w1, h1) == (200, 300)
    assert (w2, h2) == (200, 300)
    assert "embedded" in method1
    assert "embedded" in method2
    with Image.open(out1) as im1, Image.open(out2) as im2:
        assert im1.getpixel((100, 150)) != im2.getpixel((100, 150))


def test_image_names_do_not_collide_at_three_digits():
    names = {image_name("Book", n) for n in range(1, 1000)}
    assert len(names) == 999


def test_unrotated_embedded_jpeg_is_copied_verbatim(tmp_path: Path):
    source = tmp_path / "source.jpg"
    image = Image.new("RGB", (200, 300))
    for y in range(300):
        for x in range(200):
            image.putpixel((x, y), (x % 256, y % 256, (x + y) % 256))
    image.save(source, "JPEG", quality=90)

    pdf = tmp_path / "plain.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=200, height=300)
    page.insert_image(page.rect, filename=str(source))
    doc.save(pdf)
    doc.close()

    doc = pymupdf.open(pdf)
    try:
        xref = int(doc[0].get_image_info(xrefs=True)[0]["xref"])
        embedded = doc.extract_image(xref)["image"]
        out = tmp_path / "out.jpg"
        width, height, method, rotation = extract_page(doc, 1, out)
    finally:
        doc.close()
    assert (width, height) == (200, 300)
    assert "embedded" in method
    assert rotation == 0
    assert out.read_bytes() == embedded


def test_rotated_page_preserves_native_pixels_instead_of_upscaling(tmp_path: Path):
    source = tmp_path / "rotated.jpg"
    image = Image.new("RGB", (200, 300), (255, 0, 0))
    for y in range(150, 300):
        for x in range(200):
            image.putpixel((x, y), (0, 0, 255))
    image.save(source, "JPEG", quality=95)

    pdf = tmp_path / "rotated.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=200, height=300)
    page.insert_image(page.rect, filename=str(source))
    page.set_rotation(180)
    doc.save(pdf)
    doc.close()

    doc = pymupdf.open(pdf)
    try:
        out = tmp_path / "out.jpg"
        width, height, method, rotation = extract_page(doc, 1, out)
    finally:
        doc.close()
    assert (width, height) == (200, 300)
    assert "embedded" in method
    assert rotation == 180
    with Image.open(out) as im:
        top = im.getpixel((100, 10))
        bottom = im.getpixel((100, 290))
    # After the display rotation the former bottom (blue) is at the top.
    assert top[2] > top[0]
    assert bottom[0] > bottom[2]
