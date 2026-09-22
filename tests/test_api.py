"""HTTP surface tests: the happy path, the seeded demos, and every error branch
an agent could plausibly hit.

Runs against the stub extractor, so no API key and no network.
"""

import io
import os

import pytest
from fastapi.testclient import TestClient
from PIL import Image

os.environ["LABEL_EXTRACTOR"] = "stub"


@pytest.fixture(scope="module")
def client():
    from dataclasses import replace

    from app import main
    from app.config import load_settings
    main.settings = replace(load_settings(), extractor="stub")
    main._extractor = None
    return TestClient(main.app)


def test_healthz(client):
    assert client.get("/healthz").json()["ok"] is True


def test_index_renders_with_examples(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Label Verification" in r.text
    assert "data-example=" in r.text


def test_example_pass(client):
    d = client.post("/api/review/example/clean_01").json()
    assert d["verdict"] == "pass"
    assert all(c["verdict"] == "pass" for c in d["checks"])


def test_example_reproduces_jennys_rejection(client):
    d = client.post("/api/review/example/warning_title_case").json()
    assert d["verdict"] == "fail"
    warning = next(c for c in d["checks"] if c["field"] == "government_warning")
    assert warning["verdict"] == "fail"
    assert "capital" in warning["reason"].lower()
    assert warning["citation"] == "27 CFR 16.22(a)(2)"


def test_example_catches_self_contradictory_proof(client):
    d = client.post("/api/review/example/proof_inconsistent").json()
    assert d["verdict"] == "fail"
    proof = next(c for c in d["checks"] if c["field"] == "proof_consistency")
    assert proof["verdict"] == "fail"


def test_unknown_example_is_404(client):
    assert client.post("/api/review/example/does_not_exist").status_code == 404


def test_unreadable_upload_gets_a_human_message(client):
    r = client.post("/api/review",
                    files={"image": ("bad.png", b"definitely not an image", "image/png")},
                    data={"cola_id": "X", "brand_name": "Y"})
    assert r.status_code == 400
    assert "could not be read" in r.json()["detail"]
    assert "Traceback" not in r.text


def test_non_numeric_abv_gets_a_human_message(client):
    buf = io.BytesIO()
    Image.new("RGB", (60, 60), "white").save(buf, format="PNG")
    r = client.post("/api/review",
                    files={"image": ("l.png", buf.getvalue(), "image/png")},
                    data={"cola_id": "X", "brand_name": "Y", "alcohol_content_pct": "forty"})
    assert r.status_code == 400
    assert "must be a number" in r.json()["detail"]


def test_unknown_image_reports_stub_limitation_not_a_crash(client):
    buf = io.BytesIO()
    Image.new("RGB", (60, 60), "white").save(buf, format="PNG")
    r = client.post("/api/review",
                    files={"image": ("l.png", buf.getvalue(), "image/png")},
                    data={"cola_id": "X", "brand_name": "Y"})
    assert r.status_code == 400
    assert "recorded observations" in r.json()["detail"]


def test_missing_required_field_is_422(client):
    buf = io.BytesIO()
    Image.new("RGB", (60, 60), "white").save(buf, format="PNG")
    r = client.post("/api/review", files={"image": ("l.png", buf.getvalue(), "image/png")},
                    data={"cola_id": "X"})
    assert r.status_code == 422


# --- a sample checked against edited details ----------------------------------

SAMPLE_FORM = {"cola_id": "24-001", "brand_name": "Old Tom Distillery",
               "class_type": "Kentucky Straight Bourbon Whiskey", "alcohol_content_pct": "45",
               "net_contents": "750 mL", "bottler_name": "Old Tom Distilling Co.",
               "bottler_address": "Bardstown, Kentucky",
               "country_of_origin": "Product of the United States"}


def test_a_sample_is_checked_against_the_details_sent_with_it(client):
    same = client.post("/api/review/example/clean_01", data=SAMPLE_FORM).json()
    assert same["verdict"] == "pass"
    changed = client.post("/api/review/example/clean_01",
                          data={**SAMPLE_FORM, "alcohol_content_pct": "40"}).json()
    assert changed["verdict"] == "fail"
    failing = [c["field"] for c in changed["checks"] if c["verdict"] == "fail"]
    assert failing == ["alcohol_content"]


def test_a_sample_without_details_uses_its_own_application(client):
    assert client.post("/api/review/example/clean_01").json()["verdict"] == "pass"


def test_the_index_carries_each_samples_application(client):
    html = client.get("/").text
    assert "data-record='{" in html and "A compliant bourbon label" in html
    assert "the rejection Jenny caught" not in html


@pytest.mark.parametrize("value", ["nan", "inf", "0", "450", "forty"])
def test_an_impossible_alcohol_content_is_refused(client, value):
    r = client.post("/api/review/example/clean_01",
                    data={**SAMPLE_FORM, "alcohol_content_pct": value})
    assert r.status_code == 400
    assert "between 0 and 100" in r.json()["detail"]


def test_a_decimal_comma_alcohol_content_is_read(client):
    r = client.post("/api/review/example/clean_01",
                    data={**SAMPLE_FORM, "alcohol_content_pct": "45,0"})
    assert r.json()["verdict"] == "pass"
