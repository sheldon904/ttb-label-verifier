"""The batch surface and the form-tolerance fixes, against the stub extractor."""

import io
import os
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

os.environ["LABEL_EXTRACTOR"] = "stub"

CSV = (
    "TTB ID,Brand,Alc/Vol,Net Contents,Image\n"
    "24-001,Old Tom Distillery,45%,750 mL,clean_01.png\n"
    "24-020,Old Tom Distillery,45,750 mL,warning_title_case.png\n"
    "24-999,,45,750 mL,nothing.png\n"
)


@pytest.fixture(scope="module")
def client():
    from app import main
    from app.config import load_settings
    main.settings = replace(load_settings(), extractor="stub", max_batch_concurrency=2)
    main._extractor = None
    main._gate = None
    return TestClient(main.app)


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (60, 60), "white").save(buf, format="PNG")
    return buf.getvalue()


def test_batch_records_endpoint_parses_and_reports_row_errors(client):
    r = client.post("/api/batch/records", files={"records": ("batch.csv", CSV.encode(), "text/csv")})
    assert r.status_code == 200
    d = r.json()
    assert [rec["cola_id"] for rec in d["records"]] == ["24-001", "24-020"]
    assert d["records"][0]["alcohol_content_pct"] == 45.0
    assert d["images"] == {"24-001": "clean_01.png", "24-020": "warning_title_case.png"}
    assert len(d["errors"]) == 1 and "24-999" in d["errors"][0]


def test_batch_records_endpoint_rejects_an_unusable_file(client):
    r = client.post("/api/batch/records", files={"records": ("x.csv", b"", "text/csv")})
    assert r.status_code == 400
    assert "empty" in r.json()["detail"]


def test_sample_batch_is_served_for_reviewers(client):
    r = client.get("/examples/batch")
    assert r.status_code == 200
    d = r.json()
    assert len(d["records"]) >= 10
    # Rendered labels are PNG, the AI-generated ones JPEG.
    assert all(v.endswith((".png", ".jpg")) for v in d["images"].values())
    assert any(v.endswith(".jpg") for v in d["images"].values())
    # Every referenced image is one the image endpoint can serve, as its type.
    for filename in d["images"].values():
        r = client.get(f"/examples/{filename[:-4]}/image")
        assert r.status_code == 200
        assert r.headers["content-type"] == ("image/jpeg" if filename.endswith(".jpg") else "image/png")


def test_percent_sign_in_the_form_is_tolerated(client):
    r = client.post("/api/review",
                    files={"image": ("l.png", _png(), "image/png")},
                    data={"cola_id": "X", "brand_name": "Y", "alcohol_content_pct": "45 %"})
    # The stub has no observations for a blank image; what matters is that the
    # percent sign was not the reason for rejection.
    assert r.status_code == 400
    assert "must be a number" not in r.json()["detail"]


def test_blank_brand_name_is_a_clear_error(client):
    r = client.post("/api/review",
                    files={"image": ("l.png", _png(), "image/png")},
                    data={"cola_id": "X", "brand_name": "   "})
    assert r.status_code == 400
    assert "brand name" in r.json()["detail"].lower()


def test_example_ids_are_validated_before_touching_the_filesystem(client):
    assert client.get("/examples/..%2F..%2Fpyproject/image").status_code == 404
    assert client.post("/api/review/example/Clean_01").status_code == 404


def test_openapi_docs_are_available(client):
    assert client.get("/docs").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/review" in paths and "/api/batch/records" in paths


def test_index_advertises_the_sample_batch_and_concurrency(client):
    html = client.get("/").text
    assert 'id="batch-sample"' in html
    assert 'data-concurrency="2"' in html
