"""The page gets the OCR result at once and the second reading afterwards.

`defer` must answer without calling the model and say whether a second
reading is worth asking for. `inline` must include it. The OCR is cached by
image, so the second request re-reads nothing.
"""

import io
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.assist.triage import HeuristicTriage

FORM = {"cola_id": "T-1", "brand_name": "Stone's Throw", "class_type": "Straight Rye Whiskey",
        "alcohol_content_pct": "50", "net_contents": "750 mL"}

GLARE = {  # what OCR reports for a glare-washed compliant label
    "brand_name": None, "class_type": "Straight Rye Whiskey",
    "alcohol_statement": "50% Alc./Vol. (100 Proof)", "net_contents": "750 mL",
    "warning_text": ("GOVERNMENT WARNING: (1) According to the Surgeon General, women should not "
                     "drink alcoholic beverages during pregnancy because of the risk of birth "
                     "defects. (2) Consumption of alcoholic beverages impairs your ability to "
                     "drive a car or operate machinery, and may cause health problems."),
    "warning_prefix_is_bold": True,
    "field_confidence": {"brand_name": 0.0},
}


class GlareExtractor:
    name = "glare"

    def __init__(self):
        self.calls = 0

    async def extract_raw(self, raw, prepared):
        self.calls += 1
        return dict(GLARE), {"engine": "glare"}


class Reader:
    name = "test-model"

    def __init__(self):
        self.calls = 0

    async def read(self, image, fields):
        self.calls += 1
        return {"brand_name": "STONE'S THROW"}


@pytest.fixture
def app_parts():
    from app import main
    from app.pipeline import ObservationCache
    extractor, reader = GlareExtractor(), Reader()
    main.settings = replace(main.settings, extractor="stub")
    main._extractor = extractor
    main._assist = (reader, HeuristicTriage())
    main.cache = ObservationCache()
    yield TestClient(main.app), extractor, reader
    main._extractor = None
    main._assist = None


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (80, 60), "white").save(buf, format="PNG")
    return buf.getvalue()


def _post(client, mode):
    return client.post(f"/api/review?second_opinion={mode}", data=FORM,
                       files={"image": ("l.png", _png(), "image/png")}).json()


def test_defer_answers_without_the_model_and_says_a_reading_is_pending(app_parts):
    client, _, reader = app_parts
    d = _post(client, "defer")
    assert d["verdict"] == "flag"
    assert d["second_opinion"] == {"pending": True, "model": "test-model"}
    assert reader.calls == 0


def test_inline_includes_the_reading_and_reuses_the_cached_ocr(app_parts):
    client, extractor, reader = app_parts
    _post(client, "defer")
    d = _post(client, "inline")
    assert d["verdict"] == "pass"
    assert d["second_opinion"]["cleared"] == ["brand_name"]
    assert reader.calls == 1
    assert extractor.calls == 1  # the second request did not re-run OCR


def test_off_never_consults_the_model(app_parts):
    client, _, reader = app_parts
    d = _post(client, "off")
    assert d["verdict"] == "flag" and d["second_opinion"] is None
    assert reader.calls == 0


def test_nothing_pending_when_nothing_is_unclear(app_parts):
    client, extractor, _ = app_parts
    clean = dict(GLARE, brand_name="STONE'S THROW", field_confidence={})

    async def clean_read(raw, prepared):
        return dict(clean), {"engine": "clean"}

    extractor.extract_raw = clean_read
    d = _post(client, "defer")
    assert d["verdict"] == "pass" and d["second_opinion"] is None


def test_an_unknown_mode_is_rejected(app_parts):
    client, _, _ = app_parts
    r = client.post("/api/review?second_opinion=always", data=FORM,
                    files={"image": ("l.png", _png(), "image/png")})
    assert r.status_code == 422


def test_a_cached_label_is_neither_prepared_nor_read_again(monkeypatch):
    """Preparing the image only to learn its digest cost 0.7 s on every repeat
    and on every second-reading request."""
    import asyncio
    import json
    from pathlib import Path

    from app import pipeline
    from app.extract.stub import StubExtractor
    from app.models import ApplicationRecord

    prepared_calls = []
    real = pipeline.prepare_for_ocr
    monkeypatch.setattr(pipeline, "prepare_for_ocr",
                        lambda raw: prepared_calls.append(1) or real(raw))
    labels = Path(__file__).resolve().parent.parent / "fixtures" / "labels"
    raw = (labels / "clean_01.png").read_bytes()
    record = ApplicationRecord(**json.loads((labels / "clean_01.truth.json").read_text())["record"])
    cache = pipeline.ObservationCache()

    first = asyncio.run(pipeline.review_label(raw, record, StubExtractor(), cache=cache))
    second = asyncio.run(pipeline.review_label(raw, record, StubExtractor(), cache=cache))
    assert len(prepared_calls) == 1
    assert second.telemetry["cache_hit"] and second.result.verdict == first.result.verdict
    assert second.prepared.image is None  # the cache keeps measurements, not pixels
    assert second.prepared.original_size == first.prepared.original_size
