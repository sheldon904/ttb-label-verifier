"""Preprocessing tests -- the latency lever and the two silent-corruption traps."""

import io

import pytest
from PIL import Image

from app.extract.preprocess import UnreadableImageError, prepare_image


def _png(size=(400, 300), color=(200, 30, 30), mode="RGB"):
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, format="PNG")
    return buf.getvalue()


def test_downscales_to_max_edge():
    p = prepare_image(_png((4000, 3000)), max_edge=1600)
    assert max(p.final_size) == 1600
    assert p.final_size == (1600, 1200)  # aspect ratio preserved


def test_small_images_are_not_upscaled():
    p = prepare_image(_png((320, 240)), max_edge=1600)
    assert p.final_size == (320, 240)


def test_large_photo_shrinks_substantially():
    """The latency lever: a phone-sized image should lose most of its bytes."""
    p = prepare_image(_png((4000, 3000)), max_edge=1600)
    assert p.reduction_pct > 50


def test_transparent_png_flattens_onto_white_not_black():
    """Dark label text on a transparent background must survive, not vanish."""
    buf = io.BytesIO()
    Image.new("RGBA", (100, 100), (0, 0, 0, 0)).save(buf, format="PNG")
    p = prepare_image(buf.getvalue())
    out = Image.open(io.BytesIO(p.data))
    assert out.getpixel((50, 50)) == pytest.approx((255, 255, 255), abs=3)


def test_output_is_jpeg_with_a_stable_digest():
    raw = _png()
    a, b = prepare_image(raw), prepare_image(raw)
    assert a.media_type == "image/jpeg"
    assert a.sha256 == b.sha256


def test_unreadable_bytes_raise_a_readable_error():
    with pytest.raises(UnreadableImageError, match="could not be read"):
        prepare_image(b"this is not an image")


def test_empty_upload_raises():
    with pytest.raises(UnreadableImageError, match="empty"):
        prepare_image(b"")
