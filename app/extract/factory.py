"""Selects an extractor from configuration.

Two implementations: local OCR (the product) and a fixture replay used by the
tests and the seeded demos. The interface stays because it is what makes the
rule engine testable without an image, not because a third backend is planned.
"""

from __future__ import annotations

from app.config import Settings
from app.extract.base import LabelExtractor
from app.extract.ocr import OcrExtractor
from app.extract.stub import StubExtractor


def build_extractor(settings: Settings) -> LabelExtractor:
    match settings.extractor:
        case "ocr":
            return OcrExtractor()
        case "stub":
            return StubExtractor()
        case other:
            raise ValueError(f"Unknown LABEL_EXTRACTOR {other!r}. Expected 'ocr' or 'stub'.")
