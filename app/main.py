"""FastAPI application: one page, one obvious action.

Sarah Chen's usability benchmark is her 73-year-old mother, and half her team is
over 50. That rules out a single-page framework, a build step, hidden state and
progressive disclosure. It is a form and a checklist.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Form, HTTPException, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.assist.second_opinion import build_reader, eligible_rows
from app.assist.triage import build_triage
from app.config import REPO_ROOT, load_settings
from app.extract.factory import build_extractor
from app.extract.imageprep import UnreadableImageError
from app.extract.stub import StubExtractionMissing
from app.models import ApplicationRecord
from app.pipeline import ObservationCache, review_label
from app.ratelimit import RateLimitMiddleware, TokenBuckets
from app.records import parse_records

WEB_DIR = Path(__file__).resolve().parent / "web"
FIXTURE_DIR = REPO_ROOT / "fixtures" / "labels"
SAMPLE_BATCH = REPO_ROOT / "fixtures" / "records" / "batch-sample.csv"

# The seeded demos. A grader rarely arrives holding label images, so the tool
# has to be able to demonstrate itself: a compliant label, the defect Jenny
# described, a self-contradictory alcohol statement, a brand one letter off
# (a referral, with triage), a tilted photograph (the evidence boxes follow
# the tilt) and a glare-damaged photograph (a referral OCR cannot resolve,
# which the second reading clears when it is switched on). Described the way
# an agent would describe the label, with the result a reviewer should see;
# the fixture descriptions are written for developers.
EXAMPLES = {
    "clean_01": ("A compliant bourbon label", "pass"),
    "warning_title_case": ('The warning heading printed as "Government Warning"', "fail"),
    "proof_inconsistent": ("45% alcohol stated as 80 proof on the same label", "fail"),
    "brand_near_miss": ("A brand name one letter different from the application", "flag"),
    "photo_skewed": ("A compliant label photographed at an angle", "pass"),
    "photo_glare": ("A compliant label photographed with glare", "pass"),
}
EXAMPLE_IDS = tuple(EXAMPLES)

# Fixture ids are file stems. Anything else is not an example, whatever the
# filesystem might make of it.
_EXAMPLE_ID = re.compile(r"^[a-z0-9_]{1,64}$")

settings = load_settings()
cache = ObservationCache()

app = FastAPI(
    title="TTB Label Verification Prototype",
    description=(
        "Checks alcohol beverage label artwork against the COLA application record. "
        "Local OCR, deterministic rules, nothing stored. Two optional steps run after "
        "the rules: a second reading of rows the OCR could not read (only when an "
        "OpenRouter or Anthropic key is set) and triage of referrals (Jev on Vercel, "
        "else a local heuristic). Neither can reject a label."
    ),
    version="1.0",
)
app.add_middleware(
    RateLimitMiddleware,
    buckets=TokenBuckets(max(1, settings.rate_limit_per_minute)),
    trust_proxy_headers=settings.trust_proxy_headers,
)
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))


# What a missing form field is called on the page, for the error message.
_FIELD_LABELS = {
    "image": "a label image",
    "cola_id": "the COLA ID",
    "brand_name": "the brand name",
    "records": "a records file",
}


@app.exception_handler(RequestValidationError)
async def readable_validation_error(request: Request, exc: RequestValidationError):
    """FastAPI's default 422 body is a list of objects, which the page would
    show as "[object Object]". Keep the 422 and the list, and put a sentence an
    agent can act on in `detail`."""
    missing, other = [], []
    for err in exc.errors():
        field = str(err.get("loc", ("",))[-1])
        if err.get("type") == "missing" and field in _FIELD_LABELS:
            missing.append(_FIELD_LABELS[field])
        else:
            other.append(f"{field}: {err.get('msg', 'is not valid')}")
    if missing:
        detail = "Please provide " + " and ".join(missing) + "."
    else:
        detail = "The request was not valid. " + "; ".join(other)
    return JSONResponse({"detail": detail, "errors": jsonable_encoder(exc.errors())},
                        status_code=422)


def _asset_version() -> str:
    """A short digest of the page's script and stylesheet.

    Appended to their URLs so a browser that cached an older copy fetches the
    new one after a deploy, instead of running old script against a new API.
    """
    digest = hashlib.sha256()
    for name in ("app.js", "app.css"):
        digest.update((WEB_DIR / "static" / name).read_bytes())
    return digest.hexdigest()[:10]


ASSET_VERSION = _asset_version()

_extractor = None
_gate: asyncio.Semaphore | None = None
_assist: tuple | None = None


def get_assist():
    """(second-opinion reader, triage provider), each None when not configured."""
    global _assist
    if _assist is None:
        _assist = (build_reader(settings), build_triage(settings))
    return _assist


def get_extractor():
    """Built lazily so the page still loads (and explains itself) if OCR is misconfigured."""
    global _extractor
    if _extractor is None:
        _extractor = build_extractor(settings)
    return _extractor


def review_gate() -> asyncio.Semaphore:
    """Bounds how many labels are in the OCR thread pool at once.

    The browser fans a batch out over the single-label endpoint, so this is the
    server-side half of MAX_BATCH_CONCURRENCY: however many tabs are open, no
    more than this many Tesseract processes run at a time.
    """
    global _gate
    if _gate is None:
        _gate = asyncio.Semaphore(max(1, settings.max_batch_concurrency))
    return _gate


def load_example(example_id: str) -> dict:
    if not _EXAMPLE_ID.match(example_id):
        raise HTTPException(404, "That example is not available.")
    path = FIXTURE_DIR / f"{example_id}.truth.json"
    if not path.is_file():
        raise HTTPException(404, "That example is not available.")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["image_path"] = FIXTURE_DIR / f"{example_id}.png"
    return data


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "extractor": settings.extractor}


@app.get("/", include_in_schema=False)
async def index(request: Request):
    examples = []
    for eid in EXAMPLE_IDS:
        try:
            ex = load_example(eid)
        except HTTPException:
            continue
        label, expected = EXAMPLES[eid]
        examples.append({"id": eid, "description": label, "expected": expected,
                         "record": ex["record"]})
    return templates.TemplateResponse(request, "index.html", {
        "examples": examples,
        "extractor": settings.extractor,
        "asset_version": ASSET_VERSION,
        "batch_concurrency": max(1, settings.max_batch_concurrency),
        "max_batch_labels": settings.max_batch_labels,
        "sample_batch": SAMPLE_BATCH.is_file(),
        "second_opinion": get_assist()[0].name if get_assist()[0] else None,
        "triage": get_assist()[1].name if get_assist()[1] else None,
    })


@app.get("/examples/{example_id}/image")
async def example_image(example_id: str):
    return FileResponse(load_example(example_id)["image_path"], media_type="image/png")


@app.get("/examples/batch")
async def example_batch():
    """The committed sample batch: records plus the fixture images they refer to.

    Lets a reviewer try batch mode without first assembling a records file and
    a folder of artwork. The browser fetches each image and runs the batch the
    same way it would with uploaded files.
    """
    if not SAMPLE_BATCH.is_file():
        raise HTTPException(404, "No sample batch is available.")
    parsed = parse_records(SAMPLE_BATCH.read_bytes(), SAMPLE_BATCH.name)
    return JSONResponse({
        "records": [r.model_dump() for r in parsed.records],
        "images": parsed.images,
        "errors": parsed.errors,
    })


# How the second reading is delivered.
#   inline  the response waits for it (the API default, and what batch uses:
#           a batch is about throughput, not about the first answer)
#   defer   the response comes back as soon as OCR and the rules have run, and
#           says whether a second reading is worth asking for; the page asks
#           again with inline and updates in place. OCR is cached by image, so
#           the second request costs only the model call.
#   off     never consult the second reader on this request
SecondOpinionMode = Literal["inline", "defer", "off"]

SECOND_OPINION_QUERY = Query(
    "inline",
    description=("inline waits for the second reading; defer returns the OCR result at "
                 "once and reports whether a second reading is pending; off skips it."),
)


async def _run(raw: bytes, record: ApplicationRecord,
               mode: SecondOpinionMode = "inline") -> JSONResponse:
    try:
        reader, triage = get_assist()
        bundle = await review_label(raw, record, get_extractor(), cache=cache,
                                    second_opinion=reader if mode == "inline" else None,
                                    triage=triage, ocr_gate=review_gate())
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
        "boxes": bundle.extraction.field_boxes,
        "triage": bundle.result.triage.model_dump() if bundle.result.triage else None,
        "second_opinion": (
            {"pending": True, "model": reader.name}
            if mode == "defer" and reader is not None and eligible_rows(bundle.result)
            else _second_opinion_summary(bundle.telemetry.get("second_opinion"))
        ),
        "image": {
            "original": list(bundle.prepared.original_size),
            "processed": list(bundle.prepared.final_size),
            "deskew_deg": bundle.prepared.deskew_deg,
            "upscale_factor": bundle.prepared.upscale_factor,
        },
        "cache_hit": bundle.telemetry.get("cache_hit", False),
    })


def _second_opinion_summary(telemetry: dict | None) -> dict | None:
    """What the second reading did on this label, for the page. Never the cost."""
    if not telemetry or not telemetry.get("called"):
        return None
    reader = get_assist()[0]
    return {
        "model": reader.name if reader else None,
        "cleared": telemetry.get("cleared", []),
        "unavailable": bool(telemetry.get("error")),
    }


def _parse_abv(value: str) -> float | None:
    """'45', '45.0', '45%', '45 %', '40,5' -> a number. Agents type what the form shows."""
    cleaned = value.replace("%", "").replace(",", ".").strip()
    if not cleaned:
        return None
    try:
        abv = float(cleaned)
    except ValueError:
        abv = math.nan
    # "nan" and "inf" parse as floats, and a nan compares unequal to every
    # label, which would fail the alcohol row on any artwork.
    if not 0 < abv <= 100:
        raise HTTPException(400, "Alcohol content must be a number between 0 and 100, "
                                 "for example 45 or 45.5.")
    return abv


def _record_from_form(cola_id: str, brand_name: str, alcohol_content_pct: str,
                      net_contents: str, class_type: str, bottler_name: str,
                      bottler_address: str, country_of_origin: str) -> ApplicationRecord:
    if not brand_name.strip():
        raise HTTPException(400, "Enter the brand name from the application.")
    return ApplicationRecord(
        cola_id=cola_id.strip() or "UNSPECIFIED",
        brand_name=brand_name.strip(),
        class_type=class_type.strip() or None,
        alcohol_content_pct=_parse_abv(alcohol_content_pct),
        net_contents=net_contents.strip() or None,
        bottler_name=bottler_name.strip() or None,
        bottler_address=bottler_address.strip() or None,
        country_of_origin=country_of_origin.strip() or None,
    )


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
    second_opinion: SecondOpinionMode = SECOND_OPINION_QUERY,
):
    # One byte past the limit is enough to know it is too large; reading the
    # whole file first would hold an arbitrarily large upload in memory.
    raw = await image.read(settings.max_upload_bytes + 1)
    if len(raw) > settings.max_upload_bytes:
        size = image.size if image.size else len(raw)
        raise HTTPException(
            413,
            f"That image is {size / 1e6:.1f} MB. The limit is "
            f"{settings.max_upload_bytes / 1e6:.0f} MB. Please upload a smaller file.",
        )
    record = _record_from_form(cola_id, brand_name, alcohol_content_pct, net_contents,
                               class_type, bottler_name, bottler_address, country_of_origin)
    return await _run(raw, record, second_opinion)


@app.post("/api/review/example/{example_id}")
async def api_review_example(
    example_id: str,
    cola_id: str = Form(""),
    brand_name: str | None = Form(None),
    alcohol_content_pct: str = Form(""),
    net_contents: str = Form(""),
    class_type: str = Form(""),
    bottler_name: str = Form(""),
    bottler_address: str = Form(""),
    country_of_origin: str = Form(""),
    second_opinion: SecondOpinionMode = SECOND_OPINION_QUERY,
):
    """A sample label, checked against its own application record, or against
    the details sent with the request. The page sends the form, so a reviewer
    can change one detail of a sample application and see that check change."""
    ex = load_example(example_id)
    if brand_name is None:
        record = ApplicationRecord(**ex["record"])
    else:
        record = _record_from_form(cola_id, brand_name, alcohol_content_pct, net_contents,
                                   class_type, bottler_name, bottler_address, country_of_origin)
    return await _run(ex["image_path"].read_bytes(), record, second_opinion)


@app.post("/api/batch/records")
async def api_batch_records(records: UploadFile):
    """Parse a CSV or JSON export into application records.

    Returns per-row errors alongside whatever parsed successfully, so a typo in
    one row does not cost an agent the rest of the batch.
    """
    raw = await records.read(settings.max_upload_bytes + 1)
    if len(raw) > settings.max_upload_bytes:
        raise HTTPException(413, "That records file is too large.")

    parsed = parse_records(raw, records.filename or "")
    if len(parsed.records) > settings.max_batch_labels:
        raise HTTPException(
            400,
            f"That file has {len(parsed.records)} records. The limit is "
            f"{settings.max_batch_labels} per batch; split it into smaller files.",
        )
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
