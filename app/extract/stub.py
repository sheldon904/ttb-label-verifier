"""Replays recorded observations for a known fixture image.

Lets the UI, the batch path and the rule engine be built, demoed and tested with
zero API spend and zero network. Keyed on the SHA-256 of the raw file so it is
unaffected by changes to preprocessing.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.config import REPO_ROOT
from app.extract.imageprep import PreparedImage

FIXTURE_DIR = REPO_ROOT / "fixtures" / "labels"


class StubExtractionMissing(KeyError):
    """Raised when an image has no recorded observations."""


class StubExtractor:
    name = "stub"

    def __init__(self, fixture_dir: Path | None = None) -> None:
        self._index: dict[str, dict] = {}
        directory = fixture_dir or FIXTURE_DIR
        for truth_path in sorted(directory.glob("*.truth.json")):
            image_path = truth_path.with_name(truth_path.name.replace(".truth.json", ".png"))
            if not image_path.is_file():
                continue
            digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
            self._index[digest] = json.loads(truth_path.read_text(encoding="utf-8"))["observations"]

    def __len__(self) -> int:
        return len(self._index)

    async def extract_raw(self, raw: bytes, prepared: PreparedImage) -> tuple[dict, dict]:
        digest = hashlib.sha256(raw).hexdigest()
        if digest not in self._index:
            raise StubExtractionMissing(
                "No recorded observations for this image. The stub extractor only serves "
                "generated fixtures -- run `make fixtures`, or set LABEL_EXTRACTOR=vlm."
            )
        telemetry = {"engine": "stub", "elapsed_ms": 0,
                     "deskew_deg": prepared.deskew_deg,
                     "upscale_factor": prepared.upscale_factor}
        return self._index[digest], telemetry
