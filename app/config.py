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


def _text(name: str, default: str) -> str:
    """A setting, where a blank value means the default.

    A hosting dashboard keeps a variable added with no value as an empty
    string. On the first Vercel deployment a blank MAX_BATCH_CONCURRENCY
    reached int() and the app exited before it served a page.
    """
    return os.environ.get(name, "").strip() or default


def _number(name: str, default: int) -> int:
    raw = _text(name, str(default))
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name} must be a whole number, not {raw!r}") from None


def _flag(name: str, default: bool = False) -> bool:
    return _text(name, "1" if default else "0").lower() in ("1", "true", "yes", "on")


def load_settings() -> Settings:
    _load_dotenv(REPO_ROOT / ".env")
    anthropic_key = _text("ANTHROPIC_API_KEY", "") or None
    openrouter_key = _text("OPENROUTER_API_KEY", "") or None
    # An explicit key first. VERCEL_OIDC_TOKEN is present in local development
    # after `vercel env pull`; a running deployment sends its token with each
    # request instead (app.assist.triage.OIDC_HEADER).
    gateway_key = _text("AI_GATEWAY_API_KEY", "") or _text("VERCEL_OIDC_TOKEN", "") or None
    return Settings(
        extractor=_text("LABEL_EXTRACTOR", "ocr").lower(),
        max_batch_concurrency=_number("MAX_BATCH_CONCURRENCY", 8),
        max_upload_bytes=_number("MAX_UPLOAD_BYTES", 12 * 1024 * 1024),
        tesseract_cmd=_text("TESSERACT_CMD", "") or None,
        rate_limit_per_minute=_number("RATE_LIMIT_PER_MINUTE", 600),
        trust_proxy_headers=_flag("TRUST_PROXY_HEADERS"),
        max_batch_labels=_number("MAX_BATCH_LABELS", 500),
        second_opinion=_text("SECOND_OPINION", "auto").lower(),
        openrouter_api_key=openrouter_key,
        anthropic_api_key=anthropic_key,
        second_opinion_model=_text("SECOND_OPINION_MODEL", ""),
        second_opinion_daily_limit=_number("SECOND_OPINION_DAILY_LIMIT", 300),
        openrouter_data_collection=_text("OPENROUTER_DATA_COLLECTION", "deny"),
        triage=_text("TRIAGE", "jev").lower(),
        ai_gateway_api_key=gateway_key,
        triage_model=_text("TRIAGE_MODEL", "typesafe-ai/jev"),
    )
