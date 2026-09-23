"""The seam that answers Marcus Williams.

"Our network blocks outbound traffic to a lot of domains... During the scanning
vendor pilot, half their features didn't work because our firewall blocked
connections to their ML endpoints."

Extraction is therefore an interface. Local Tesseract OCR is the product and
the only extractor that reads an image; a stub replays recorded fixture
observations so the rule engine, the API and the UI can be tested with no OCR
at all. Every implementation speaks the same raw-observation dict, and
`to_extraction` is the single place that dict becomes a typed LabelExtraction.
The rule engine cannot tell them apart.
"""

from __future__ import annotations

from typing import Protocol

from app.extract.imageprep import PreparedImage
from app.models import LabelExtraction


class LabelExtractor(Protocol):
    name: str

    async def extract_raw(self, raw: bytes, prepared: PreparedImage) -> tuple[dict, dict]:
        """Return (observations, telemetry). Never returns a verdict.

        Takes both the original bytes and the preprocessed image: OCR reads
        `prepared`, while the stub identifies fixtures by hashing `raw`.
        """
        ...


def _clean(value: object) -> str | None:
    """Empty strings and whitespace are absence, not a value."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def to_extraction(observations: dict) -> LabelExtraction:
    """Map a raw observation dict onto the typed model.

    Tolerant by design: an extractor that omits an optional key, or returns ""
    for a missing field, must not crash the pipeline.
    """
    bold = observations.get("warning_prefix_is_bold")
    notes = observations.get("legibility_notes") or []

    return LabelExtraction(
        brand_name=_clean(observations.get("brand_name")),
        class_type=_clean(observations.get("class_type")),
        class_type_next=_clean(observations.get("class_type_next")),
        alcohol_statement=_clean(observations.get("alcohol_statement")),
        net_contents=_clean(observations.get("net_contents")),
        bottler_name=_clean(observations.get("bottler_name")),
        bottler_address=_clean(observations.get("bottler_address")),
        country_of_origin=_clean(observations.get("country_of_origin")),
        # Note: warning_text is NOT passed through _clean's stripping of case or
        # punctuation -- only surrounding whitespace. Case is substantive here.
        warning_text=_clean(observations.get("warning_text")),
        warning_unsure=[str(w) for w in observations.get("warning_unsure") or [] if str(w).strip()],
        warning_prefix_is_bold=bold if isinstance(bold, bool) else None,
        warning_small_type=observations.get("warning_small_type") is True,
        warning_legibility=(
            observations.get("warning_legibility")
            if observations.get("warning_legibility") in ("read", "illegible", "absent")
            else ("read" if _clean(observations.get("warning_text")) else "absent")
        ),
        notes=[str(n) for n in notes if str(n).strip()],
        unread_text=[str(t) for t in observations.get("unread_text") or [] if str(t).strip()],
        image_soft=observations.get("image_soft") is True,
        field_confidence={
            str(k): float(v)
            for k, v in (observations.get("field_confidence") or {}).items()
            if isinstance(v, (int, float))
        },
        field_boxes={
            str(k): [[float(x), float(y)] for x, y in v]
            for k, v in (observations.get("field_boxes") or {}).items()
            if _is_quad(v)
        },
    )


def _is_quad(value: object) -> bool:
    """Four [x, y] points, each a fraction of the image. Anything else is dropped."""
    if not isinstance(value, list) or len(value) != 4:
        return False
    return all(
        isinstance(p, list) and len(p) == 2
        and all(isinstance(c, (int, float)) and 0.0 <= c <= 1.0 for c in p)
        for p in value
    )
