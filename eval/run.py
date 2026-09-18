"""Runs every fixture through the real pipeline and scores the result.

Usage:
    make eval                                  # uses LABEL_EXTRACTOR from .env
    python -m eval.run --extractor stub        # offline, no cost
    python -m eval.run --model claude-sonnet-5 # bake-off against the default
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

from app.config import REPO_ROOT, load_settings  # noqa: E402
from app.extract.factory import build_extractor  # noqa: E402
from app.models import ApplicationRecord  # noqa: E402
from app.pipeline import review_label  # noqa: E402
from eval.report import EvalSummary, FixtureOutcome, render  # noqa: E402

FIXTURE_DIR = REPO_ROOT / "fixtures" / "labels"
OUT_DIR = REPO_ROOT / "eval" / "out"

# Fields scored for extraction accuracy. Compared case-sensitively: for the
# warning, case IS the defect under test.
SCORED_FIELDS = ("brand_name", "class_type", "alcohol_statement", "net_contents",
                 "warning_text", "warning_prefix_is_bold")


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


async def run_one(fx: dict, extractor, settings, sem: asyncio.Semaphore) -> FixtureOutcome:
    async with sem:
        raw = fx["_image"].read_bytes()
        record = ApplicationRecord(**fx["record"])
        try:
            bundle = await review_label(raw, record, extractor)
        except Exception as exc:  # noqa: BLE001 - the report records the failure
            return FixtureOutcome(
                id=fx["id"], description=fx["description"], expected=fx["expected_verdict"],
                actual="error", expected_fields=fx["expected_failing_fields"],
                actual_failing_fields=[], field_hits={}, total_ms=0,
                input_tokens=0, output_tokens=0, error=f"{type(exc).__name__}: {exc}",
            )

        observed = bundle.extraction.model_dump()
        failing = [c.field for c in bundle.result.checks if c.verdict.value != "pass"]
        return FixtureOutcome(
            id=fx["id"], description=fx["description"], expected=fx["expected_verdict"],
            actual=bundle.result.verdict.value,
            expected_fields=fx["expected_failing_fields"],
            actual_failing_fields=failing,
            field_hits=score_fields(fx["observations"], observed),
            total_ms=bundle.telemetry.get("total_ms", 0),
            input_tokens=bundle.telemetry.get("input_tokens", 0),
            output_tokens=bundle.telemetry.get("output_tokens", 0),
        )


async def main_async(args) -> int:
    settings = load_settings()
    if args.extractor:
        settings = replace(settings, extractor=args.extractor)

    fixtures = load_fixtures()
    if not fixtures:
        print("No fixtures found. Run `make fixtures` first.", file=sys.stderr)
        return 1

    extractor = build_extractor(settings)
    sem = asyncio.Semaphore(args.concurrency)

    print(f"Evaluating {len(fixtures)} fixtures via {extractor.name} "
          f"(concurrency {args.concurrency})...\n")
    started = time.perf_counter()
    outcomes = await asyncio.gather(*(run_one(f, extractor, settings, sem) for f in fixtures))
    wall_clock = time.perf_counter() - started

    for o in outcomes:
        mark = "ok  " if o.verdict_correct else "MISS"
        print(f"  {mark} {o.id:<28} {o.expected:>4} -> {o.actual:<5} {o.total_ms:>6} ms"
              + (f"  {o.error}" if o.error else ""))

    summary = EvalSummary(model=getattr(extractor, "name", "unknown"), outcomes=list(outcomes),
                          concurrency=args.concurrency, wall_clock_s=wall_clock)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report = render(summary)
    name = summary.model.replace(":", "_").replace("/", "_")
    (OUT_DIR / f"report-{name}.md").write_text(report, encoding="utf-8")
    (OUT_DIR / "report.md").write_text(report, encoding="utf-8")

    print(f"\n{summary.accuracy:.1%} verdict accuracy over {summary.n} fixtures")
    print(f"p50 {summary.pct(50)} ms · p95 {summary.pct(95)} ms"
          + (f" (interactive budget 5000 ms: {'MET' if summary.pct(95) < 5000 else 'MISSED'})"
             if args.concurrency == 1 else " (under load)"))
    print(f"throughput {summary.throughput_per_min:.0f} labels/min "
          f"-> a 300-label batch in ~{300 / max(summary.throughput_per_min, 1e-9):.1f} min")
    print(f"report -> {OUT_DIR / f'report-{name}.md'}")

    return 0 if summary.accuracy >= args.min_accuracy else 2


def main() -> int:
    p = argparse.ArgumentParser(description="Evaluate the label verifier against its fixture set.")
    p.add_argument("--extractor", choices=["ocr", "stub"])
    p.add_argument("--concurrency", type=int, default=6)
    p.add_argument("--min-accuracy", type=float, default=0.90,
                   help="Exit non-zero below this. Default 0.90.")
    return asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
