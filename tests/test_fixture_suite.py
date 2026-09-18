"""Guards the fixture set against drift.

With the stub extractor the observations are perfect by construction, so this
isolates the rule engine: every fixture's expected verdict must be reproduced
exactly. If someone retunes BRAND_PASS_THRESHOLD or an ABV tolerance and breaks
a stakeholder case, this fails rather than the change landing silently.

It does NOT measure extraction accuracy -- that requires the VLM and lives in
eval/out/report.md.
"""

import asyncio
import json
from pathlib import Path

import pytest

from app.config import REPO_ROOT
from app.extract.stub import StubExtractor
from app.models import ApplicationRecord
from app.pipeline import review_label

FIXTURE_DIR = REPO_ROOT / "fixtures" / "labels"


def _fixtures() -> list[tuple[str, Path]]:
    return [(p.name.replace(".truth.json", ""), p)
            for p in sorted(FIXTURE_DIR.glob("*.truth.json"))]


def test_fixture_set_is_present_and_balanced():
    ids = [i for i, _ in _fixtures()]
    assert len(ids) >= 20, "fixture set has shrunk -- run `make fixtures`"
    verdicts = {json.loads(p.read_text())["expected_verdict"] for _, p in _fixtures()}
    assert verdicts == {"pass", "flag", "fail"}, "every verdict class must be represented"


@pytest.mark.parametrize("fixture_id,truth_path", _fixtures(), ids=lambda v: v if isinstance(v, str) else "")
def test_rule_engine_reproduces_expected_verdict(fixture_id, truth_path):
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    image = truth_path.with_name(truth_path.name.replace(".truth.json", ".png"))
    bundle = asyncio.run(review_label(
        image.read_bytes(),
        ApplicationRecord(**truth["record"]),
        StubExtractor(),
    ))
    assert bundle.result.verdict.value == truth["expected_verdict"], (
        f"{fixture_id}: {truth['description']}\n"
        + "\n".join(f"  {c.field}: {c.verdict.value} — {c.reason}" for c in bundle.result.checks)
    )


@pytest.mark.parametrize("fixture_id,truth_path", _fixtures(), ids=lambda v: v if isinstance(v, str) else "")
def test_expected_failing_fields_are_the_ones_that_fire(fixture_id, truth_path):
    """A right verdict for the wrong reason is still a defect."""
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    expected = set(truth["expected_failing_fields"])
    if not expected:
        return
    image = truth_path.with_name(truth_path.name.replace(".truth.json", ".png"))
    bundle = asyncio.run(review_label(
        image.read_bytes(),
        ApplicationRecord(**truth["record"]),
        StubExtractor(),
    ))
    fired = {c.field for c in bundle.result.checks if c.verdict.value != "pass"}
    assert expected <= fired, f"{fixture_id}: expected {expected} to fire, got {fired}"
