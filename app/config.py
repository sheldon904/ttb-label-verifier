"""Runtime configuration.

Deliberately dependency-free: a tiny .env reader plus os.environ. Adding
pydantic-settings for six values would be more machinery than the prototype
earns.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Latency-first default. Sarah Chen's hard requirement is ~5s; Haiku is the
# fastest vision-capable option. Phase 2 benchmarks it against Sonnet on the
# same fixture set and the winner is published in the README.
DEFAULT_VLM_MODEL = "claude-haiku-4-5-20251001"


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
        # Strip trailing inline comments from unquoted values.
        if "#" in value:
            value = value.split("#", 1)[0].strip()
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    extractor: str
    anthropic_api_key: str | None
    vlm_model: str
    max_image_edge_px: int
    max_batch_concurrency: int
    max_upload_bytes: int

    @property
    def vlm_available(self) -> bool:
        return bool(self.anthropic_api_key)


def load_settings() -> Settings:
    _load_dotenv(REPO_ROOT / ".env")
    return Settings(
        extractor=os.environ.get("LABEL_EXTRACTOR", "vlm").lower(),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        vlm_model=os.environ.get("VLM_MODEL", DEFAULT_VLM_MODEL),
        max_image_edge_px=int(os.environ.get("MAX_IMAGE_EDGE_PX", "1600")),
        max_batch_concurrency=int(os.environ.get("MAX_BATCH_CONCURRENCY", "10")),
        max_upload_bytes=int(os.environ.get("MAX_UPLOAD_BYTES", str(12 * 1024 * 1024))),
    )
