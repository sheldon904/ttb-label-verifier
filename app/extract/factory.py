"""Selects an extractor from configuration, with a readable failure when the
chosen one cannot run."""

from __future__ import annotations

from app.config import Settings
from app.extract.base import LabelExtractor
from app.extract.ocr import OcrExtractor
from app.extract.stub import StubExtractor
from app.extract.vlm import VlmExtractor


def build_extractor(settings: Settings) -> LabelExtractor:
    match settings.extractor:
        case "vlm":
            return VlmExtractor(settings)
        case "stub":
            return StubExtractor()
        case "ocr":
            return OcrExtractor()
        case other:
            raise ValueError(
                f"Unknown LABEL_EXTRACTOR {other!r}. Expected one of: vlm, stub, ocr."
            )
