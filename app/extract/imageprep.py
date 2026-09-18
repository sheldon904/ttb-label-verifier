"""Image preparation for OCR.

Deliberately the inverse of what a vision model wants. A model prefers a small
image; Tesseract prefers a large, straight, high-contrast one. Measured on the
fixture set, two operations account for nearly all of the recoverable accuracy:

  deskew   a 7 degree rotation makes Tesseract miss the warning statement
           entirely -- not misread it, miss it
  upscale  6pt text is below Tesseract's reliable floor until it is enlarged

Both are deterministic, cheap, and explainable in an appeal, which is the whole
reason for choosing a classical pipeline here.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError

MIN_OCR_EDGE = 2200          # Tesseract is most reliable near 300 DPI equivalent
MAX_OCR_EDGE = 3400          # beyond this we pay time for no accuracy
SKEW_SEARCH_DEG = 12.0
SKEW_STEP_DEG = 0.25


class UnreadableImageError(ValueError):
    """Raised when bytes are not a decodable image. Surfaced to the agent as prose."""


@dataclass(frozen=True)
class PreparedImage:
    """The OCR-ready render, plus what we did to get there.

    The provenance fields are not decoration: when a check comes back FLAG the
    agent is owed an explanation, and "we rotated this 7 degrees and enlarged it
    3x to read it" is a materially different message from "the text was wrong".
    """

    image: Image.Image
    sha256: str
    original_size: tuple[int, int]
    final_size: tuple[int, int]
    original_bytes: int
    deskew_deg: float
    upscale_factor: float

    @property
    def was_deskewed(self) -> bool:
        return abs(self.deskew_deg) >= 0.5


def _to_grayscale_array(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("L"), dtype=np.uint8)


def _otsu_threshold(gray: np.ndarray) -> int:
    """Otsu's method: pick the threshold that minimises intra-class variance.

    Chosen over a fixed cutoff because label stock is cream, not white, and
    glare shifts the histogram unpredictably.
    """
    hist = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    total = hist.sum()
    if total == 0:
        return 128
    omega = np.cumsum(hist) / total
    mu = np.cumsum(hist * np.arange(256)) / total
    mu_t = mu[-1]
    denom = omega * (1.0 - omega)
    with np.errstate(divide="ignore", invalid="ignore"):
        sigma_b = np.where(denom > 0, (mu_t * omega - mu) ** 2 / denom, 0.0)
    return int(np.argmax(sigma_b))


def binarize(img: Image.Image) -> Image.Image:
    gray = _to_grayscale_array(img)
    t = _otsu_threshold(gray)
    return Image.fromarray(((gray > t) * 255).astype(np.uint8), mode="L")


def estimate_skew(img: Image.Image) -> float:
    """Projection-profile skew estimation over an edge map.

    Rotating text into alignment makes the horizontal ink profile spiky: level
    lines mean rows are either dense with glyphs or empty. Two details matter,
    both found by measuring rather than assuming:

    1. Project EDGES, not raw ink. A photograph of a tilted label has dark fill
       or background at the corners, and those flat triangles are enormous
       compared to the text. Projecting raw ink lets them dominate and the
       estimate collapses to zero. An edge map scores flat regions -- dark or
       light -- at nearly nothing, so only glyphs vote.

    2. Score the profile's squared gradient, not its variance. On the fixture
       set the gradient peak at the true angle is ~6x the neighbouring angles,
       where variance manages only ~1.4x. Sharper peak, less tie-breaking.

    Pure numpy and Pillow: no OpenCV, which keeps the container small.
    """
    work = img.convert("L")
    work.thumbnail((900, 900), Image.BILINEAR)

    # Edge magnitude via difference-of-blur: cheap, orientation-agnostic, and
    # zero on flat paper and flat background alike.
    arr = np.asarray(work, dtype=np.float64)
    blurred = np.asarray(work.filter(ImageFilter.GaussianBlur(2.0)), dtype=np.float64)
    edges = np.abs(arr - blurred)
    if edges.max() > 0:
        edges *= 255.0 / edges.max()

    base = Image.fromarray(edges.astype(np.uint8), mode="L")

    best_angle, best_score = 0.0, -1.0
    angle = -SKEW_SEARCH_DEG
    while angle <= SKEW_SEARCH_DEG + 1e-9:
        rotated = base.rotate(angle, resample=Image.BILINEAR, fillcolor=0)
        profile = np.asarray(rotated, dtype=np.float64).sum(axis=1)
        delta = np.diff(profile)
        score = float(np.dot(delta, delta))
        if score > best_score:
            best_angle, best_score = angle, score
        angle += SKEW_STEP_DEG
    return best_angle


def prepare_for_ocr(raw: bytes) -> PreparedImage:
    import hashlib

    if not raw:
        raise UnreadableImageError("The uploaded file is empty.")
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise UnreadableImageError(
            "That file could not be read as an image. Supported formats are "
            "JPEG, PNG, WEBP and TIFF."
        ) from exc

    original_size = img.size
    img = ImageOps.exif_transpose(img)

    # Flatten transparency onto white: dark text on a transparent background
    # would otherwise be composited onto black and disappear.
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        canvas = Image.new("RGB", img.size, (255, 255, 255))
        canvas.paste(img, mask=img.split()[-1])
        img = canvas
    else:
        img = img.convert("RGB")

    skew = estimate_skew(img)
    if abs(skew) >= 0.5:
        img = img.rotate(skew, resample=Image.BICUBIC, expand=True, fillcolor=(255, 255, 255))

    factor = 1.0
    longest = max(img.size)
    if longest < MIN_OCR_EDGE:
        factor = min(MIN_OCR_EDGE / longest, MAX_OCR_EDGE / longest)
        img = img.resize((round(img.width * factor), round(img.height * factor)), Image.LANCZOS)

    img = img.filter(ImageFilter.UnsharpMask(radius=1.4, percent=110, threshold=2))

    return PreparedImage(
        image=img,
        sha256=hashlib.sha256(raw).hexdigest(),
        original_size=original_size,
        final_size=img.size,
        original_bytes=len(raw),
        deskew_deg=round(skew, 2),
        upscale_factor=round(factor, 2),
    )
