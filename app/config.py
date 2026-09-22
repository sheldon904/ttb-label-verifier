"""Runtime configuration.

Deliberately dependency-free: a tiny .env reader plus os.environ. The default
configuration needs no credentials and makes no outbound call. The two
optional model features, a second opinion on referrals and referral triage,
each need a key and are off unless one is set.
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
    # Abuse limits for a public deployment.
    rate_limit_per_minute: int = 120
    trust_proxy_headers: bool = False
    max_batch_labels: int = 500
    # Optional: a vision model re-reads only the fields OCR could not read on a
    # referred label. It can clear a referral; it can never reject.
    second_opinion: str = "off"
    anthropic_api_key: str | None = None
    second_opinion_model: str = "claude-sonnet-5"
    # Optional: orders referrals by how likely each is to be a real defect.
    # "heuristic" is local and needs no key; "jev" calls TypeSafe's Jev
    # through Vercel AI Gateway.
    triage: str = "heuristic"
    ai_gateway_api_key: str | None = None
    triage_model: str = "typesafe-ai/jev"


def _flag(name: str, default: bool = False) -> bool:
    return os.environ.get(name, "1" if default else "0").strip().lower() in ("1", "true", "yes", "on")


def load_settings() -> Settings:
    _load_dotenv(REPO_ROOT / ".env")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY") or None
    gateway_key = os.environ.get("AI_GATEWAY_API_KEY") or None
    return Settings(
        extractor=os.environ.get("LABEL_EXTRACTOR", "ocr").lower(),
        max_batch_concurrency=int(os.environ.get("MAX_BATCH_CONCURRENCY", "8")),
        max_upload_bytes=int(os.environ.get("MAX_UPLOAD_BYTES", str(12 * 1024 * 1024))),
        tesseract_cmd=os.environ.get("TESSERACT_CMD") or None,
        rate_limit_per_minute=int(os.environ.get("RATE_LIMIT_PER_MINUTE", "120")),
        trust_proxy_headers=_flag("TRUST_PROXY_HEADERS"),
        max_batch_labels=int(os.environ.get("MAX_BATCH_LABELS", "500")),
        second_opinion=os.environ.get("SECOND_OPINION", "off").strip().lower(),
        anthropic_api_key=anthropic_key,
        second_opinion_model=os.environ.get("SECOND_OPINION_MODEL", "claude-sonnet-5"),
        triage=os.environ.get("TRIAGE", "heuristic").strip().lower(),
        ai_gateway_api_key=gateway_key,
        triage_model=os.environ.get("TRIAGE_MODEL", "typesafe-ai/jev"),
    )
