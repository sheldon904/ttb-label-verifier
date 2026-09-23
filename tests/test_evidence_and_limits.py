"""Evidence boxes, checklist layers, rate limiting and the OCR rescue rules."""

import asyncio
import os
import shutil
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.extract.base import to_extraction
from app.extract.imageprep import prepare_for_ocr, rotation_inverse_matrix
from app.extract.layout import Line, Word, pick_bottler, pick_net_contents, rescue_units
from app.models import ApplicationRecord, LabelExtraction, Verdict
from app.ratelimit import RateLimitMiddleware, TokenBuckets, client_key
from app.rules.engine import review
from app.rules.fields import parse_net_contents_ml
from app.rules.warning import STATUTORY_WARNING

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "labels"


# --- evidence boxes -------------------------------------------------------

@pytest.mark.parametrize("angle", [7.0, -6.0, 3.25])
def test_rotation_inverse_matches_pillow(angle):
    img = Image.new("L", (600, 400), 255)
    ImageDraw.Draw(img).rectangle([400, 90, 410, 100], fill=0)
    m, size = rotation_inverse_matrix(600, 400, angle)
    rotated = img.rotate(angle, expand=True, fillcolor=255)
    assert rotated.size == size
    ys, xs = np.where(np.asarray(rotated) < 128)
    cx, cy = xs.mean(), ys.mean()
    x, y = m[0] * cx + m[1] * cy + m[2], m[3] * cx + m[4] * cy + m[5]
    assert abs(x - 405) < 1 and abs(y - 95) < 1


def test_display_quad_on_an_unrotated_image_is_the_box_scaled():
    buf = Image.new("RGB", (1000, 500), "white")
    import io
    b = io.BytesIO()
    buf.save(b, format="PNG")
    p = prepare_for_ocr(b.getvalue())
    assert p.display_size == (1000, 500) and p.rotation_matrix is None
    fx = p.final_size[0] / 1000
    quad = p.to_display_quad(100 * fx, 50 * fx, 300 * fx, 100 * fx)
    assert quad[0] == pytest.approx([0.1, 0.1], abs=0.01)
    assert quad[2] == pytest.approx([0.3, 0.2], abs=0.01)


def test_malformed_boxes_are_dropped():
    ext = to_extraction({"field_boxes": {
        "brand_name": [[0.1, 0.1], [0.5, 0.1], [0.5, 0.2], [0.1, 0.2]],
        "bad_shape": [[0.1, 0.1]],
        "out_of_range": [[2, 0], [0, 0], [0, 0], [0, 0]],
    }})
    assert list(ext.field_boxes) == ["brand_name"]


def _tesseract_available() -> bool:
    return bool(shutil.which("tesseract") or os.path.isfile(r"C:\Program Files\Tesseract-OCR\tesseract.exe"))


@pytest.mark.skipif(not _tesseract_available(), reason="Tesseract is not installed")
def test_boxes_land_where_the_fields_are_on_a_tilted_photo():
    from app.extract.ocr import OcrExtractor
    p = prepare_for_ocr((FIXTURES / "photo_skewed.png").read_bytes())
    obs, _ = OcrExtractor()._extract_sync(p)
    boxes = obs["field_boxes"]
    brand_y = max(y for _, y in boxes["brand_name"])
    warning_y = min(y for _, y in boxes["government_warning"])
    assert brand_y < 0.3
    assert warning_y > 0.6
    # A 7 degree tilt: the box's top edge is not level.
    (_, y0), (_, y1) = boxes["brand_name"][0], boxes["brand_name"][1]
    assert abs(y1 - y0) > 0.02


# --- layers --------------------------------------------------------------

def test_every_row_is_assigned_to_one_of_two_layers():
    result = review(ApplicationRecord(cola_id="X", brand_name="Old Tom Distillery",
                                      alcohol_content_pct=45.0, net_contents="750 mL"),
                    LabelExtraction(brand_name="OLD TOM DISTILLERY",
                                    alcohol_statement="45% Alc./Vol. (90 Proof)",
                                    net_contents="750 mL", warning_text=STATUTORY_WARNING,
                                    warning_prefix_is_bold=True))
    layers = {c.field: c.layer for c in result.checks}
    assert layers["brand_name"] == layers["net_contents"] == "application"
    assert layers["government_warning"] == layers["proof_consistency"] == "regulation"
    assert layers["alcohol_format"] == layers["warning_typography"] == "regulation"


# --- fluid ounces and the unit rescue -----------------------------------

def test_fluid_ounces_convert():
    assert parse_net_contents_ml("12 FL OZ") == pytest.approx(354.88, abs=0.01)
    assert parse_net_contents_ml("12 fl. oz.") == pytest.approx(354.88, abs=0.01)
    assert parse_net_contents_ml("16 fluid ounces") == pytest.approx(473.18, abs=0.01)
    assert parse_net_contents_ml("750 millilitres") == 750


def _line(text, top, key, conf=95.0, height=28):
    return Line(words=[Word(t, 100 + i * 70, top, 60, height, conf, key)
                       for i, t in enumerate(text.split())])


def test_a_unit_scored_zero_is_reattached_to_its_number():
    lines = [_line("12", 600, (3, 1, 2))]
    weak = [Word("FL", 180, 600, 60, 38, 0.0, (3, 1, 2)), Word("OZ", 250, 600, 60, 38, 0.0, (3, 1, 2)),
            Word("noise", 900, 1200, 60, 38, 0.0, (9, 1, 1))]
    rescue_units(lines, weak)
    assert lines[0].text == "12 FL OZ"
    assert lines[0].conf < 70  # a rescued read can refer, never reject


def test_low_scored_words_that_are_not_a_unit_are_left_out():
    lines = [_line("12", 600, (3, 1, 2))]
    rescue_units(lines, [Word("Bourbon", 180, 600, 60, 38, 0.0, (3, 1, 2))])
    assert lines[0].text == "12"


def test_a_bare_number_is_a_half_read_volume_not_a_missing_one():
    lines = [_line("HARBOR LIGHT", 100, (1, 1, 1), height=70), _line("12", 600, (3, 1, 2))]
    assert pick_net_contents(lines, set()) == "12"
    check = next(c for c in review(
        ApplicationRecord(cola_id="X", brand_name="Harbor Light", net_contents="355 mL"),
        LabelExtraction(brand_name="HARBOR LIGHT", net_contents="12")).checks
        if c.field == "net_contents")
    assert check.verdict is Verdict.FLAG and check.read_uncertain


def test_a_number_is_never_a_bottler_name():
    lines = [_line("6.5% ALC/VOL", 500, (3, 1, 1)), _line("12", 600, (3, 1, 2)),
             _line("Harbor Light Brewing Co.", 700, (4, 1, 1)), _line("Portland, Maine", 750, (4, 1, 2))]
    assert pick_bottler(lines, set()) == ("Harbor Light Brewing Co.", "Portland, Maine")


# --- rate limiting --------------------------------------------------------

class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_bucket_refills_at_the_configured_rate():
    clock = Clock()
    b = TokenBuckets(per_minute=60, burst=2, clock=clock)
    assert b.take("a") == 0 and b.take("a") == 0
    assert b.take("a") == pytest.approx(1.0)
    assert b.take("b") == 0  # addresses are independent
    clock.t = 1.0
    assert b.take("a") == 0


def _limited_app(per_minute=2, trust=False):
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, buckets=TokenBuckets(per_minute),
                       trust_proxy_headers=trust)

    @app.post("/api/thing")
    async def thing():
        return {"ok": True}

    @app.get("/page")
    async def page():
        return {"ok": True}

    return TestClient(app)


def test_api_posts_over_the_limit_get_429_with_retry_after():
    c = _limited_app()
    assert [c.post("/api/thing").status_code for _ in range(2)] == [200, 200]
    r = c.post("/api/thing")
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1
    assert "Too many requests" in r.json()["detail"]


def test_pages_are_never_limited():
    c = _limited_app(per_minute=1)
    assert all(c.get("/page").status_code == 200 for _ in range(5))


def test_forwarded_for_is_used_only_when_trusted_and_only_its_last_hop():
    class R:
        def __init__(self):
            self.headers = {"x-forwarded-for": "6.6.6.6, 10.0.0.9"}
            self.client = type("C", (), {"host": "172.16.0.1"})()
    assert client_key(R(), trust_proxy_headers=False) == "172.16.0.1"
    assert client_key(R(), trust_proxy_headers=True) == "10.0.0.9"


# --- the API surface for all of this --------------------------------------

@pytest.fixture(scope="module")
def client():
    os.environ["LABEL_EXTRACTOR"] = "stub"
    from app import main
    from app.config import load_settings
    main.settings = replace(load_settings(), extractor="stub", triage="heuristic",
                            second_opinion="off")
    main._extractor = None
    main._assist = None
    return TestClient(main.app)


def test_review_response_carries_layers_boxes_and_triage(client):
    d = client.post("/api/review/example/clean_01").json()
    assert {c["layer"] for c in d["checks"]} == {"application", "regulation"}
    assert "boxes" in d and d["triage"] is None  # a pass is not triaged


def test_a_referral_is_triaged(client):
    d = client.post("/api/review/example/brand_near_miss").json()
    assert d["verdict"] == "flag"
    assert d["triage"]["provider"] == "heuristic" and d["triage"]["probability"] > 0.6


def test_index_says_what_is_switched_on(client):
    html = client.get("/").text
    assert "Second reading of referrals: <strong>off</strong>" in html
    assert "No outbound connection is made." in html


def test_oversized_batch_is_refused(client):
    from app import main
    main.settings = replace(main.settings, max_batch_labels=2)
    try:
        rows = "cola_id,brand_name\n" + "".join(f"A-{i},Brand {i}\n" for i in range(3))
        r = client.post("/api/batch/records", files={"records": ("b.csv", rows.encode(), "text/csv")})
        assert r.status_code == 400 and "limit is 2" in r.json()["detail"]
    finally:
        main.settings = replace(main.settings, max_batch_labels=500)


def test_second_opinion_setting_needs_a_key():
    from app.assist.second_opinion import build_reader
    from app.config import load_settings
    s = replace(load_settings(), second_opinion="anthropic", anthropic_api_key=None,
                openrouter_api_key=None, second_opinion_model="")
    assert build_reader(s) is None
    assert build_reader(replace(s, anthropic_api_key="k")).name == "claude-sonnet-5"


def test_pipeline_runs_triage_and_second_opinion_in_order():
    from app.extract.stub import StubExtractor
    from app.pipeline import review_label

    class Reader:
        name = "r"
        async def read(self, image, fields):
            return {}

    raw = (FIXTURES / "brand_near_miss.png").read_bytes()
    import json
    rec = ApplicationRecord(**json.loads((FIXTURES / "brand_near_miss.truth.json").read_text())["record"])
    from app.assist.triage import HeuristicTriage
    b = asyncio.run(review_label(raw, rec, StubExtractor(), second_opinion=Reader(),
                                 triage=HeuristicTriage()))
    assert b.result.verdict is Verdict.FLAG
    assert b.result.triage is not None
    assert b.telemetry["second_opinion"] == {"called": False}


# --- limits that must hold under load ---------------------------------------

def test_a_flood_of_new_addresses_never_refills_a_throttled_one():
    """Clearing every bucket when the table filled handed a throttled client a
    full allowance. Eviction takes the least recently used instead."""
    clock = Clock()
    b = TokenBuckets(per_minute=60, burst=1, clock=clock, max_keys=100)
    assert b.take("abuser") == 0
    for i in range(99):
        clock.t += 0.001
        b.take(f"new-{i}")
    clock.t += 0.001
    assert b.take("abuser") > 0  # recently used, so still tracked and still empty
    for i in range(99, 150):
        clock.t += 0.001
        b.take(f"new-{i}")
    assert len(b._buckets) <= 100


def test_a_missing_field_is_named_in_plain_words(client):
    r = client.post("/api/review", data={"cola_id": "X", "brand_name": "Y"})
    assert r.status_code == 422
    assert r.json()["detail"] == "Please provide a label image."
    assert isinstance(r.json()["errors"], list)


def test_an_unknown_option_is_explained(client):
    r = client.post("/api/review/example/clean_01?second_opinion=always")
    assert r.status_code == 422
    assert r.json()["detail"].startswith("The request was not valid. second_opinion:")


def test_an_oversized_upload_is_refused_with_its_size(client):
    from app import main
    before = main.settings.max_upload_bytes
    main.settings = replace(main.settings, max_upload_bytes=1024 * 1024)
    try:
        r = client.post("/api/review", data={"cola_id": "X", "brand_name": "Y"},
                        files={"image": ("big.png", b"\0" * (1024 * 1024 * 3 // 2), "image/png")})
    finally:
        main.settings = replace(main.settings, max_upload_bytes=before)
    assert r.status_code == 413
    # The whole file's size, though only the first megabyte was read.
    assert r.json()["detail"].startswith("That image is 1.5 MB. The limit is 1 MB.")


def test_the_ocr_slot_is_released_before_the_model_is_asked():
    """Holding the OCR slot through a slow model call made clean labels queue
    behind a referred one."""
    from app.pipeline import review_label

    gate = asyncio.Semaphore(1)
    held_during_read = []

    class Reader:
        name = "r"

        async def read(self, image, fields):
            held_during_read.append(gate.locked())
            return {}

    class HalfRead:
        """The brand washed out, so the second reader is asked about it."""

        async def extract_raw(self, raw, prepared):
            return {"brand_name": None, "class_type": "Straight Rye Whiskey",
                    "alcohol_statement": "50% Alc./Vol.", "net_contents": "750 mL",
                    "warning_text": STATUTORY_WARNING, "warning_prefix_is_bold": True,
                    "warning_legibility": "read",
                    "field_confidence": {"brand_name": 0.0}}, {"engine": "fake"}

    raw = (FIXTURES / "clean_01.png").read_bytes()
    record = ApplicationRecord(cola_id="T", brand_name="Stone's Throw",
                               class_type="Straight Rye Whiskey")
    asyncio.run(review_label(raw, record, HalfRead(), second_opinion=Reader(), ocr_gate=gate))
    assert held_during_read == [False]
