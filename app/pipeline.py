"""End-to-end: bytes in, ReviewResult out.

The only place preprocessing, extraction and the rule engine meet. Timing is
measured here -- across the whole user-visible operation, not just the API call
-- because Sarah's 5 second budget is wall clock from the agent's point of view.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

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

    Keyed on the preprocessed image digest, so re-reviewing the same artwork --
    common when an agent corrects an application record and retries -- costs
    nothing. In-memory by design: nothing is persisted (Marcus's retention note).
    """

    def __init__(self, max_entries: int = 512) -> None:
        self._store: dict[str, dict] = {}
        self._max = max_entries

    def get(self, digest: str) -> dict | None:
        return self._store.get(digest)

    def put(self, digest: str, observations: dict) -> None:
        if len(self._store) >= self._max:
            self._store.pop(next(iter(self._store)))
        self._store[digest] = observations

    def __len__(self) -> int:
        return len(self._store)


async def review_label(
    raw: bytes,
    record: ApplicationRecord,
    extractor: LabelExtractor,
    cache: ObservationCache | None = None,
) -> ReviewBundle:
    started = time.perf_counter()

    prepared = prepare_for_ocr(raw)

    cached = cache.get(prepared.sha256) if cache else None
    if cached is not None:
        observations, telemetry = cached, {"engine": "cache", "elapsed_ms": 0,
                                           "cache_hit": True}
    else:
        observations, telemetry = await extractor.extract_raw(raw, prepared)
        telemetry["cache_hit"] = False
        if cache:
            cache.put(prepared.sha256, observations)

    extraction = to_extraction(observations)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    telemetry["total_ms"] = elapsed_ms

    return ReviewBundle(
        result=review(record, extraction, elapsed_ms=elapsed_ms),
        extraction=extraction,
        prepared=prepared,
        telemetry=telemetry,
    )
