"""Replays recorded observations for a known fixture image.

Lets the UI, the batch path and the rule engine be built, demoed and tested
without Tesseract installed. Keyed on the SHA-256 of the raw file so it is
unaffected by changes to preprocessing.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.config import REPO_ROOT
from app.extract.imageprep import PreparedImage

FIXTURE_DIR = REPO_ROOT / "fixtures" / "labels"
# The AI-generated set: JPEG artwork with the same truth files.
AI_FIXTURE_DIR = REPO_ROOT / "fixtures" / "ai"


class StubExtractionMissing(KeyError):
    """Raised when an image has no recorded observations."""


class StubExtractor:
    name = "stub"

    def __init__(self, fixture_dir: Path | None = None) -> None:
        self._index: dict[str, dict] = {}
        directories = (fixture_dir,) if fixture_dir else (FIXTURE_DIR, AI_FIXTURE_DIR)
        for truth_path in (p for d in directories for p in sorted(d.glob("*.truth.json"))):
            stem = truth_path.name.replace(".truth.json", "")
            for image_path in (truth_path.with_name(stem + ext) for ext in (".png", ".jpg")):
                if image_path.is_file():
                    digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
                    truth = json.loads(truth_path.read_text(encoding="utf-8"))
                    self._index[digest] = truth["observations"]

    def __len__(self) -> int:
        return len(self._index)

    async def extract_raw(self, raw: bytes, prepared: PreparedImage) -> tuple[dict, dict]:
        digest = hashlib.sha256(raw).hexdigest()
        if digest not in self._index:
            raise StubExtractionMissing(
                "No recorded observations for this image. The stub extractor only serves "
                "the generated fixtures; set LABEL_EXTRACTOR=ocr to read other images."
            )
        telemetry = {"engine": "stub", "elapsed_ms": 0,
                     "deskew_deg": prepared.deskew_deg,
                     "upscale_factor": prepared.upscale_factor}
        return self._index[digest], telemetry
