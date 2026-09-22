"""Runs every fixture through the real pipeline and scores the result.

Usage:
    make eval                                  # full OCR pipeline, concurrency 1
    python -m eval.run --extractor stub        # rule engine only, no OCR
    python -m eval.run --concurrency 8         # throughput measurement

The exit code gates on what actually matters. A miss that refers a compliant
label to a human is a cost; a miss that rejects a compliant label, or passes
a defective one, is harm. The run fails on any harm, and on accuracy only
below a floor that is set well under the measured figure so that a slightly
different Tesseract build does not break the build.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.assist.second_opinion import build_reader
from app.assist.triage import build_triage
from app.config import REPO_ROOT, load_settings
from app.extract.factory import build_extractor
from app.models import ApplicationRecord
from app.pipeline import review_label
from eval.report import EvalSummary, FixtureOutcome, render

FIXTURE_DIR = REPO_ROOT / "fixtures" / "labels"
OUT_DIR = REPO_ROOT / "eval" / "out"

# Fields scored for extraction accuracy. Compared case-sensitively: for the
# warning, case IS the defect under test.
SCORED_FIELDS = ("brand_name", "class_type", "alcohol_statement", "net_contents",
                 "warning_text", "warning_prefix_is_bold")


def tesseract_version() -> str | None:
    try:
        import pytesseract
        return str(pytesseract.get_tesseract_version()).splitlines()[0]
    except Exception:  # noqa: BLE001 - the stub extractor has no engine
        return None


def load_fixtures() -> list[dict]:
    out = []
    for p in sorted(FIXTURE_DIR.glob("*.truth.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        d["_image"] = p.with_name(p.name.replace(".truth.json", ".png"))
        out.append(d)
    return out


def score_fields(truth: dict, observed: dict) -> dict[str, bool]:
    hits = {}
    for f in SCORED_FIELDS:
        exp, got = truth.get(f), observed.get(f)
        exp = exp.strip() if isinstance(exp, str) else exp
        got = got.strip() if isinstance(got, str) else got
        hits[f] = exp == got
    return hits


async def run_one(fx: dict, extractor, sem: asyncio.Semaphore, reader=None, triage=None) -> FixtureOutcome:
    async with sem:
        raw = fx["_image"].read_bytes()
        record = ApplicationRecord(**fx["record"])
        try:
            bundle = await review_label(raw, record, extractor, second_opinion=reader, triage=triage)
        except Exception as exc:  # noqa: BLE001 - the report records the failure
            return FixtureOutcome(
                id=fx["id"], description=fx["description"], expected=fx["expected_verdict"],
                actual="error", expected_fields=fx["expected_failing_fields"],
                actual_failing_fields=[], field_hits={}, total_ms=0,
                error=f"{type(exc).__name__}: {exc}",
            )

        observed = bundle.extraction.model_dump()
        failing = [c.field for c in bundle.result.checks if c.verdict.value != "pass"]
        # A row that FAILS without the fixture being built to fail it is a false
        # rejection of that element, even when the label fails for another
        # reason: the applicant is told something is wrong that is not.
        wrong_fails = [c.field for c in bundle.result.checks
                       if c.verdict.value == "fail" and c.field not in fx["expected_failing_fields"]]
        return FixtureOutcome(
            id=fx["id"], description=fx["description"], expected=fx["expected_verdict"],
            actual=bundle.result.verdict.value,
            expected_fields=fx["expected_failing_fields"],
            actual_failing_fields=failing,
            field_hits=score_fields(fx["observations"], observed),
            total_ms=bundle.telemetry.get("total_ms", 0),
            triage_p=bundle.result.triage.probability if bundle.result.triage else None,
            wrong_fails=wrong_fails,
            cleared=(bundle.telemetry.get("second_opinion") or {}).get("cleared", []),
            second_opinion_called=bool((bundle.telemetry.get("second_opinion") or {}).get("called")),
            cost_usd=(bundle.telemetry.get("second_opinion") or {}).get("cost_usd"),
        )


async def main_async(args) -> int:
    settings = load_settings()
    if args.extractor:
        settings = replace(settings, extractor=args.extractor)
    # The evaluation is offline and free unless asked otherwise: a model call
    # costs money and makes the numbers depend on a remote service.
    settings = replace(settings, triage=args.triage or "heuristic",
                       second_opinion=args.second_opinion or "off")
    reader, triage = build_reader(settings), build_triage(settings)
    if args.second_opinion not in (None, "off") and reader is None:
        print(f"--second-opinion {args.second_opinion} needs OPENROUTER_API_KEY or "
              "ANTHROPIC_API_KEY.", file=sys.stderr)
        return 1

    fixtures = load_fixtures()
    if not fixtures:
        print("No fixtures found. Run `make fixtures` first.", file=sys.stderr)
        return 1

    extractor = build_extractor(settings)
    sem = asyncio.Semaphore(args.concurrency)

    print(f"Evaluating {len(fixtures)} fixtures via {extractor.name} "
          f"(concurrency {args.concurrency})...\n")
    started = time.perf_counter()
    outcomes = await asyncio.gather(*(run_one(f, extractor, sem, reader, triage) for f in fixtures))
    wall_clock = time.perf_counter() - started

    for o in outcomes:
        mark = "ok  " if o.verdict_correct else "MISS"
        print(f"  {mark} {o.id:<28} {o.expected:>4} -> {o.actual:<5} {o.total_ms:>6} ms"
              + (f"  {o.error}" if o.error else ""))

    summary = EvalSummary(model=getattr(extractor, "name", "unknown"), outcomes=list(outcomes),
                          concurrency=args.concurrency, wall_clock_s=wall_clock,
                          triage=triage.name if triage else None,
                          second_opinion=reader.name if reader else None,
                          engine_version=tesseract_version())

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report = render(summary)
    # One report, overwritten each run. Per-build copies kept for comparison
    # (report-tesseract-*.md) are made by hand, so a run never adds files.
    (OUT_DIR / "report.md").write_text(report, encoding="utf-8")

    unsafe = len(summary.unsafe_misses)
    print(f"\n{summary.accuracy:.1%} verdict accuracy over {summary.n} fixtures; "
          f"{len(summary.cautious_misses)} referred unnecessarily; "
          f"{len(summary.referred_defects)} defect(s) referred not rejected; {unsafe} harmful")
    print(f"p50 {summary.pct(50)} ms · p95 {summary.pct(95)} ms"
          + (f" (interactive budget 5000 ms: {'MET' if summary.pct(95) < 5000 else 'MISSED'})"
             if args.concurrency == 1 else " (under load)"))
    print(f"throughput {summary.throughput_per_min:.0f} labels/min "
          f"-> a 300-label batch in ~{300 / max(summary.throughput_per_min, 1e-9):.1f} min")
    print(f"report -> {OUT_DIR / 'report.md'}")

    if unsafe > args.max_unsafe:
        print(f"\nFAIL: {unsafe} harmful outcome(s); the limit is {args.max_unsafe}.", file=sys.stderr)
        return 2
    if summary.accuracy < args.min_accuracy:
        print(f"\nFAIL: accuracy {summary.accuracy:.1%} is below the floor of "
              f"{args.min_accuracy:.0%}.", file=sys.stderr)
        return 2
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Evaluate the label verifier against its fixture set.")
    p.add_argument("--extractor", choices=["ocr", "stub"])
    p.add_argument("--triage", choices=["off", "heuristic", "jev"],
                   help="Referral triage provider. Default heuristic (local).")
    p.add_argument("--second-opinion", choices=["off", "auto", "openrouter", "anthropic"],
                   help="Second reading on referrals. Needs OPENROUTER_API_KEY or ANTHROPIC_API_KEY. "
                        "Default off.")
    p.add_argument("--concurrency", type=int, default=1,
                   help="1 measures interactive latency; higher measures throughput.")
    p.add_argument("--max-unsafe", type=int, default=0,
                   help="Exit non-zero above this many harmful outcomes. Default 0.")
    p.add_argument("--min-accuracy", type=float, default=0.80,
                   help="Exit non-zero below this verdict accuracy. Default 0.80.")
    return asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
