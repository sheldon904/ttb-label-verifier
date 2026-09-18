"""Local OCR extractor -- the air-gapped path for Marcus's firewall.

Intentionally not wired up yet. Its value on day one is the seam existing; a
partial implementation plus a paragraph in the README on Azure OpenAI in Azure
Government answers the constraint honestly.
"""

from __future__ import annotations

from app.models import LabelExtraction


class OcrExtractor:
    name = "ocr"

    async def extract(self, image_bytes: bytes) -> LabelExtraction:
        raise NotImplementedError("Local OCR path -- see README > Deployment constraints.")
