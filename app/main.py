"""FastAPI application: one page, one obvious action.

Sarah Chen's usability benchmark is her 73-year-old mother, and half her team is
over 50. That rules out a single-page framework, a build step, hidden state and
progressive disclosure. It is a form and a checklist.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import REPO_ROOT, load_settings
from app.extract.imageprep import UnreadableImageError
from app.extract.factory import build_extractor
from app.extract.stub import StubExtractionMissing
from app.models import ApplicationRecord
from app.pipeline import ObservationCache, review_label
from app.records import parse_records

WEB_DIR = Path(__file__).resolve().parent / "web"
FIXTURE_DIR = REPO_ROOT / "fixtures" / "labels"

# The three seeded demos. A grader rarely arrives holding label images, so the
# tool has to be able to demonstrate itself: one compliant label, one with the
# defect Jenny described, one with a self-contradictory alcohol statement.
EXAMPLE_IDS = ("clean_01", "warning_title_case", "proof_inconsistent")

settings = load_settings()
cache = ObservationCache()

app = FastAPI(title="TTB Label Verification Prototype", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

_extractor = None


def get_extractor():
    """Built lazily so the page still loads (and explains itself) without a key."""
    global _extractor
    if _extractor is None:
        _extractor = build_extractor(settings)
    return _extractor


def load_example(example_id: str) -> dict:
    path = FIXTURE_DIR / f"{example_id}.truth.json"
    if not path.is_file():
        raise HTTPException(404, "That example is not available.")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["image_path"] = FIXTURE_DIR / f"{example_id}.png"
    return data


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "extractor": settings.extractor}


@app.get("/")
async def index(request: Request):
    examples = []
    for eid in EXAMPLE_IDS:
        try:
            ex = load_example(eid)
        except HTTPException:
            continue
        examples.append({"id": eid, "description": ex["description"], "record": ex["record"]})
    return templates.TemplateResponse(request, "index.html", {
        "examples": examples,
        "extractor": settings.extractor,
    })


@app.get("/examples/{example_id}/image")
async def example_image(example_id: str):
    from fastapi.responses import FileResponse
    return FileResponse(load_example(example_id)["image_path"], media_type="image/png")


async def _run(raw: bytes, record: ApplicationRecord) -> JSONResponse:
    try:
        bundle = await review_label(raw, record, get_extractor(), cache=cache)
    except UnreadableImageError as exc:
        raise HTTPException(400, str(exc)) from exc
    except StubExtractionMissing as exc:
        raise HTTPException(400, str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(501, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc

    return JSONResponse({
        "cola_id": bundle.result.cola_id,
        "verdict": bundle.result.verdict.value,
        "elapsed_ms": bundle.result.elapsed_ms,
        "checks": [c.model_dump() for c in bundle.result.checks],
        "notes": bundle.extraction.notes,
        "image": {
            "original": list(bundle.prepared.original_size),
            "processed": list(bundle.prepared.final_size),
            "deskew_deg": bundle.prepared.deskew_deg,
            "upscale_factor": bundle.prepared.upscale_factor,
        },
        "cache_hit": bundle.telemetry.get("cache_hit", False),
    })


@app.post("/api/review")
async def api_review(
    image: UploadFile,
    cola_id: str = Form(...),
    brand_name: str = Form(...),
    alcohol_content_pct: str = Form(""),
    net_contents: str = Form(""),
    class_type: str = Form(""),
    bottler_name: str = Form(""),
    bottler_address: str = Form(""),
    country_of_origin: str = Form(""),
):
    raw = await image.read()
    if len(raw) > settings.max_upload_bytes:
        raise HTTPException(
            413,
            f"That image is {len(raw) / 1e6:.1f} MB. The limit is "
            f"{settings.max_upload_bytes / 1e6:.0f} MB — please upload a smaller file.",
        )
    try:
        abv = float(alcohol_content_pct) if alcohol_content_pct.strip() else None
    except ValueError:
        raise HTTPException(400, "Alcohol content must be a number, for example 45 or 45.5.") from None

    record = ApplicationRecord(
        cola_id=cola_id.strip() or "UNSPECIFIED",
        brand_name=brand_name.strip(),
        class_type=class_type.strip() or None,
        alcohol_content_pct=abv,
        net_contents=net_contents.strip() or None,
        bottler_name=bottler_name.strip() or None,
        bottler_address=bottler_address.strip() or None,
        country_of_origin=country_of_origin.strip() or None,
    )
    return await _run(raw, record)


@app.post("/api/review/example/{example_id}")
async def api_review_example(example_id: str):
    ex = load_example(example_id)
    return await _run(ex["image_path"].read_bytes(), ApplicationRecord(**ex["record"]))


@app.post("/api/batch/records")
async def api_batch_records(records: UploadFile):
    """Parse a CSV or JSON export into application records.

    Returns per-row errors alongside whatever parsed successfully, so a typo in
    one row does not cost an agent the rest of the batch.
    """
    raw = await records.read()
    if len(raw) > settings.max_upload_bytes:
        raise HTTPException(413, "That records file is too large.")

    parsed = parse_records(raw, records.filename or "")
    if not parsed.ok:
        raise HTTPException(
            400,
            parsed.errors[0] if parsed.errors else "No application records were found in that file.",
        )
    return JSONResponse({
        "records": [r.model_dump() for r in parsed.records],
        "images": parsed.images,
        "errors": parsed.errors,
    })
