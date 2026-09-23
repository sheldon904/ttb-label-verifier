"""Runtime configuration.

Deliberately dependency-free: a tiny .env reader plus os.environ. With no
credentials the app makes no outbound call. The second opinion on referrals
switches on when an OpenRouter or Anthropic credential is present. Triage
defaults to Jev, which needs an AI Gateway credential (or Vercel's OIDC
token), and uses the local heuristic without one.
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
    # Abuse limits for a public deployment. 600 a minute is above what the OCR
    # pool can do (about 270), so one agent's batch never waits on it.
    rate_limit_per_minute: int = 600
    trust_proxy_headers: bool = False
    max_batch_labels: int = 500
    # A vision model re-reads only the fields OCR could not read on a referred
    # label. It can clear a referral; it can never reject. "auto" turns it on
    # when a provider credential is present (OpenRouter first, then Anthropic).
    second_opinion: str = "auto"
    openrouter_api_key: str | None = None
    anthropic_api_key: str | None = None
    second_opinion_model: str = ""          # empty: the provider's default
    second_opinion_daily_limit: int = 300
    openrouter_data_collection: str = "deny"
    # Orders referrals by how likely each is to be a real defect. "jev" calls
    # TypeSafe's Jev through Vercel AI Gateway and falls back to the local
    # heuristic without a credential or when the call fails.
    triage: str = "jev"
    ai_gateway_api_key: str | None = None
    triage_model: str = "typesafe-ai/jev"


def _flag(name: str, default: bool = False) -> bool:
    return os.environ.get(name, "1" if default else "0").strip().lower() in ("1", "true", "yes", "on")


def load_settings() -> Settings:
    _load_dotenv(REPO_ROOT / ".env")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY") or None
    openrouter_key = os.environ.get("OPENROUTER_API_KEY") or None
    # On a Vercel deployment the platform's OIDC token authenticates to AI
    # Gateway without a created key; an explicit key takes precedence.
    gateway_key = os.environ.get("AI_GATEWAY_API_KEY") or os.environ.get("VERCEL_OIDC_TOKEN") or None
    return Settings(
        extractor=os.environ.get("LABEL_EXTRACTOR", "ocr").lower(),
        max_batch_concurrency=int(os.environ.get("MAX_BATCH_CONCURRENCY", "8")),
        max_upload_bytes=int(os.environ.get("MAX_UPLOAD_BYTES", str(12 * 1024 * 1024))),
        tesseract_cmd=os.environ.get("TESSERACT_CMD") or None,
        rate_limit_per_minute=int(os.environ.get("RATE_LIMIT_PER_MINUTE", "600")),
        trust_proxy_headers=_flag("TRUST_PROXY_HEADERS"),
        max_batch_labels=int(os.environ.get("MAX_BATCH_LABELS", "500")),
        second_opinion=os.environ.get("SECOND_OPINION", "auto").strip().lower(),
        openrouter_api_key=openrouter_key,
        anthropic_api_key=anthropic_key,
        second_opinion_model=os.environ.get("SECOND_OPINION_MODEL", "").strip(),
        second_opinion_daily_limit=int(os.environ.get("SECOND_OPINION_DAILY_LIMIT", "300")),
        openrouter_data_collection=os.environ.get("OPENROUTER_DATA_COLLECTION", "deny").strip(),
        triage=os.environ.get("TRIAGE", "jev").strip().lower(),
        ai_gateway_api_key=gateway_key,
        triage_model=os.environ.get("TRIAGE_MODEL", "typesafe-ai/jev"),
    )
