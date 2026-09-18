"""Image preparation for OCR.

Tesseract wants the opposite of what a vision model wants: bigger, straighter,
higher contrast. These are the two operations that recovered the most accuracy
on the fixture set, so they are pinned.
"""

import io

import pytest
from PIL import Image

from app.extract.imageprep import (
    MIN_OCR_EDGE,
    UnreadableImageError,
    binarize,
    estimate_skew,
    prepare_for_ocr,
)

LABEL = "fixtures/labels/clean_01.png"


def _png(size=(400, 300), color=(200, 30, 30), mode="RGB"):
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, format="PNG")
    return buf.getvalue()


# --- skew ------------------------------------------------------------------

@pytest.mark.parametrize("angle", [0, 3, -5, 7, -7, 10])
def test_skew_is_recovered_exactly(angle):
    """A 7 degree tilt made Tesseract miss the warning entirely, so this must
    hold to a fraction of a degree, not approximately."""
    src = Image.open(LABEL)
    tilted = src.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=(255, 255, 255))
    assert estimate_skew(tilted) == pytest.approx(-angle, abs=0.5)


@pytest.mark.parametrize("fill", [(255, 255, 255), (58, 55, 52), (120, 140, 160)])
def test_skew_survives_any_background(fill):
    """Regression: projecting raw ink let dark corner fill dominate the profile
    and the estimate collapsed to zero. Edges are projected instead."""
    src = Image.open(LABEL)
    tilted = src.rotate(7, resample=Image.BICUBIC, expand=True, fillcolor=fill)
    assert estimate_skew(tilted) == pytest.approx(-7, abs=0.5)


# --- scaling ---------------------------------------------------------------

def test_small_images_are_enlarged_for_ocr():
    p = prepare_for_ocr(_png((600, 800)))
    assert max(p.final_size) >= MIN_OCR_EDGE
    assert p.upscale_factor > 1.0


def test_large_images_are_not_enlarged():
    p = prepare_for_ocr(_png((2600, 3000)))
    assert p.upscale_factor == 1.0


# --- robustness ------------------------------------------------------------

def test_transparent_png_flattens_onto_white_not_black():
    buf = io.BytesIO()
    Image.new("RGBA", (100, 100), (0, 0, 0, 0)).save(buf, format="PNG")
    out = prepare_for_ocr(buf.getvalue()).image
    assert out.convert("RGB").getpixel((50, 50)) == pytest.approx((255, 255, 255), abs=4)


def test_binarize_separates_ink_from_cream_stock():
    """Otsu rather than a fixed cutoff: label stock is cream, not white."""
    img = Image.new("RGB", (100, 100), (247, 243, 233))
    for x in range(10, 40):
        for y in range(10, 40):
            img.putpixel((x, y), (26, 24, 22))
    arr = binarize(img)
    assert arr.getpixel((20, 20)) == 0      # ink
    assert arr.getpixel((80, 80)) == 255    # stock


def test_unreadable_bytes_raise_a_readable_error():
    with pytest.raises(UnreadableImageError, match="could not be read"):
        prepare_for_ocr(b"this is not an image")


def test_empty_upload_raises():
    with pytest.raises(UnreadableImageError, match="empty"):
        prepare_for_ocr(b"")
