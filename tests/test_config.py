"""Settings as a hosting dashboard delivers them."""

import pytest

from app.config import load_settings

INTEGERS = ("MAX_BATCH_CONCURRENCY", "MAX_UPLOAD_BYTES", "RATE_LIMIT_PER_MINUTE",
            "MAX_BATCH_LABELS", "SECOND_OPINION_DAILY_LIMIT")


def test_a_blank_setting_means_its_default(monkeypatch):
    """A variable added in the Vercel dashboard with no value arrives as an
    empty string. The first deployment exited on int('') before it served a
    page."""
    for name in (*INTEGERS, "LABEL_EXTRACTOR", "SECOND_OPINION", "TRIAGE",
                 "OPENROUTER_DATA_COLLECTION", "TRUST_PROXY_HEADERS"):
        monkeypatch.setenv(name, "")
    s = load_settings()
    assert (s.max_batch_concurrency, s.max_upload_bytes, s.rate_limit_per_minute) == (
        8, 12 * 1024 * 1024, 600)
    assert (s.extractor, s.second_opinion, s.triage) == ("ocr", "auto", "jev")
    assert s.openrouter_data_collection == "deny"
    assert s.trust_proxy_headers is False


def test_a_setting_that_is_not_a_number_is_named(monkeypatch):
    monkeypatch.setenv("MAX_BATCH_CONCURRENCY", "four")
    with pytest.raises(ValueError, match="MAX_BATCH_CONCURRENCY"):
        load_settings()
