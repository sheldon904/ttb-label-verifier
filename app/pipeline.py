"""End-to-end: bytes in, ReviewResult out.

The only place preprocessing, extraction and the rule engine meet. Timing is
measured here -- across the whole user-visible operation, not just the API call
-- because Sarah's 5 second budget is wall clock from the agent's point of view.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import time
from dataclasses import dataclass, replace

from app.assist.second_opinion import SecondOpinionReader, apply_second_opinion
from app.assist.triage import TriageProvider
from app.extract.base import LabelExtractor, to_extraction
from app.extract.imageprep import PreparedImage, prepare_for_ocr
from app.models import ApplicationRecord, LabelExtraction, ReviewResult
from app.rules.engine import review


@dataclass
class ReviewBundle:
    """Everything the UI and the eval harness need from one label."""

    result: ReviewResult
    extraction: LabelExtraction
    prepared: PreparedImage
    telemetry: dict


class ObservationCache:
    """Content-addressed cache of raw observations.

    Keyed on the digest of the uploaded bytes, so re-reviewing the same
    artwork (an agent correcting an application record and retrying, or the
    page asking again for the second reading) skips preparation and OCR both.
    Each entry keeps the image's measurements without its pixels, so 512
    entries stay small. In-memory by design: nothing is persisted (Marcus's
    retention note).
    """

    def __init__(self, max_entries: int = 512) -> None:
        self._store: dict[str, tuple[dict, PreparedImage]] = {}
        self._max = max_entries

    def get(self, digest: str) -> tuple[dict, PreparedImage] | None:
        return self._store.get(digest)

    def put(self, digest: str, observations: dict, prepared: PreparedImage) -> None:
        if len(self._store) >= self._max:
            self._store.pop(next(iter(self._store)))
        self._store[digest] = (observations, replace(prepared, image=None))

    def __len__(self) -> int:
        return len(self._store)


async def review_label(
    raw: bytes,
    record: ApplicationRecord,
    extractor: LabelExtractor,
    cache: ObservationCache | None = None,
    second_opinion: SecondOpinionReader | None = None,
    triage: TriageProvider | None = None,
    ocr_gate: asyncio.Semaphore | None = None,
) -> ReviewBundle:
    """OCR, then the rules; then, only if configured, the two advisory steps.

    Neither advisory step can produce a FAIL. The second opinion can clear a
    referral the OCR could not read; triage only annotates a referral.

    `ocr_gate` bounds the CPU work only. Waiting on a model is not CPU work,
    and holding an OCR slot through it made a clean label queue behind a
    referred one.
    """
    started = time.perf_counter()

    # Looked up before any image work: preparing the image only to learn its
    # digest cost 0.7 s on every repeat and on every second-reading request.
    # "is not None": an empty cache has len 0 and is falsy, which once meant
    # nothing was ever stored and the cache never worked.
    digest = hashlib.sha256(raw).hexdigest()
    cached = cache.get(digest) if cache is not None else None
    if cached is not None:
        observations, prepared = cached
        telemetry = {"engine": "cache", "elapsed_ms": 0, "cache_hit": True}
    else:
        async with ocr_gate if ocr_gate is not None else contextlib.nullcontext():
            prepared = await asyncio.to_thread(prepare_for_ocr, raw)
            observations, telemetry = await extractor.extract_raw(raw, prepared)
        telemetry["cache_hit"] = False
        if cache is not None:
            cache.put(digest, observations, prepared)

    extraction = to_extraction(observations)
    result = review(record, extraction)

    if second_opinion is not None:
        result, telemetry["second_opinion"] = await apply_second_opinion(
            record, extraction, result, raw, second_opinion)
    if triage is not None:
        result = result.model_copy(update={"triage": await triage.score(result)})

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    telemetry["total_ms"] = elapsed_ms

    return ReviewBundle(
        result=result.model_copy(update={"elapsed_ms": elapsed_ms}),
        extraction=extraction,
        prepared=prepared,
        telemetry=telemetry,
    )
