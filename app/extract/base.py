"""The seam that answers Marcus Williams.

"Our network blocks outbound traffic to a lot of domains... During the scanning
vendor pilot, half their features didn't work because our firewall blocked
connections to their ML endpoints."

Extraction is therefore an interface, not a hard dependency on one vendor. A
cloud VLM is the default; a local OCR implementation is the air-gapped path; a
stub replays recorded fixtures for offline UI work. Every implementation speaks
the same raw-observation dict, and `to_extraction` is the single place that dict
becomes a typed LabelExtraction. The rule engine cannot tell them apart.
"""

from __future__ import annotations

from typing import Protocol

from app.extract.preprocess import PreparedImage
from app.models import LabelExtraction


class LabelExtractor(Protocol):
    name: str

    async def extract_raw(self, raw: bytes, prepared: PreparedImage) -> tuple[dict, dict]:
        """Return (observations, telemetry). Never returns a verdict.

        Takes both the original bytes and the preprocessed image: the cloud path
        sends `prepared`, while the stub identifies fixtures by hashing `raw`.
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

    Tolerant by design: a model that omits an optional key, or returns "" for a
    missing field, must not crash the pipeline.
    """
    bold = observations.get("warning_prefix_is_bold")
    notes = observations.get("legibility_notes") or []

    return LabelExtraction(
        brand_name=_clean(observations.get("brand_name")),
        class_type=_clean(observations.get("class_type")),
        alcohol_statement=_clean(observations.get("alcohol_statement")),
        net_contents=_clean(observations.get("net_contents")),
        bottler_name=_clean(observations.get("bottler_name")),
        bottler_address=_clean(observations.get("bottler_address")),
        country_of_origin=_clean(observations.get("country_of_origin")),
        # Note: warning_text is NOT passed through _clean's stripping of case or
        # punctuation -- only surrounding whitespace. Case is substantive here.
        warning_text=_clean(observations.get("warning_text")),
        warning_prefix_is_bold=bold if isinstance(bold, bool) else None,
        notes=[str(n) for n in notes if str(n).strip()],
    )
