"""Runtime configuration.

Deliberately dependency-free: a tiny .env reader plus os.environ. There are no
credentials to manage -- the pipeline runs entirely locally -- so this stays
small on purpose.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Populate os.environ from a .env file without clobbering real env vars."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if "#" in value:
            value = value.split("#", 1)[0].strip()
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    extractor: str
    max_batch_concurrency: int
    max_upload_bytes: int
    tesseract_cmd: str | None


def load_settings() -> Settings:
    _load_dotenv(REPO_ROOT / ".env")
    return Settings(
        extractor=os.environ.get("LABEL_EXTRACTOR", "ocr").lower(),
        max_batch_concurrency=int(os.environ.get("MAX_BATCH_CONCURRENCY", "8")),
        max_upload_bytes=int(os.environ.get("MAX_UPLOAD_BYTES", str(12 * 1024 * 1024))),
        tesseract_cmd=os.environ.get("TESSERACT_CMD") or None,
    )
