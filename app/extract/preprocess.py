"""Image preparation -- the single largest latency lever in this system.

A phone photo of a bottle is routinely 3-5 MB and 4000px on the long edge.
Uploading that to a vision model costs seconds of wall clock for no accuracy
gain: label text is legible well below 1600px. Downscaling before the call
typically buys more than switching models does.

Also handles the two things that silently corrupt label images:
  * EXIF orientation (a phone photo that renders upright in Preview but arrives
    rotated 90 degrees to the API)
  * alpha channels (a transparent PNG flattened onto black makes dark text
    vanish entirely -- we composite onto white)
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError


class UnreadableImageError(ValueError):
    """Raised when bytes are not a decodable image. Surfaced to the agent as prose."""


@dataclass(frozen=True)
class PreparedImage:
    data: bytes
    media_type: str
    sha256: str
    original_size: tuple[int, int]
    final_size: tuple[int, int]
    original_bytes: int
    final_bytes: int

    @property
    def reduction_pct(self) -> float:
        if not self.original_bytes:
            return 0.0
        return 100.0 * (1 - self.final_bytes / self.original_bytes)


def prepare_image(raw: bytes, max_edge: int = 1600, quality: int = 85) -> PreparedImage:
    if not raw:
        raise UnreadableImageError("The uploaded file is empty.")

    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise UnreadableImageError(
            "That file could not be read as an image. Supported formats are JPEG, PNG, WEBP and TIFF."
        ) from exc

    original_size = img.size

    # Respect the camera's rotation flag before any resizing.
    img = ImageOps.exif_transpose(img)

    # Flatten transparency onto white so dark label text survives JPEG encoding.
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        canvas = Image.new("RGB", img.size, (255, 255, 255))
        canvas.paste(img, mask=img.split()[-1])
        img = canvas
    elif img.mode != "RGB":
        img = img.convert("RGB")

    if max(img.size) > max_edge:
        img.thumbnail((max_edge, max_edge), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    data = buf.getvalue()

    return PreparedImage(
        data=data,
        media_type="image/jpeg",
        sha256=hashlib.sha256(data).hexdigest(),
        original_size=original_size,
        final_size=img.size,
        original_bytes=len(raw),
        final_bytes=len(data),
    )
