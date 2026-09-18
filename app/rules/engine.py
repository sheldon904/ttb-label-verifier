"""Runs every field policy and aggregates one overall verdict.

This module is the only place a ReviewResult is produced, it is pure, and it
never touches the network. That is what makes the decision auditable: an agent
can be shown exactly which rule fired and which regulation it came from.
"""

from __future__ import annotations

from app.models import ApplicationRecord, CheckResult, LabelExtraction, ReviewResult, Verdict
from app.rules.fields import check_alcohol_content, check_brand_name, check_net_contents
from app.rules.warning import check_warning_text, check_warning_typography


def aggregate(checks: list[CheckResult]) -> Verdict:
    """Worst non-advisory verdict wins; advisory checks can only raise to FLAG."""
    binding = [c for c in checks if not c.advisory]
    if any(c.verdict is Verdict.FAIL for c in binding):
        return Verdict.FAIL
    if any(c.verdict is Verdict.FLAG for c in checks):
        return Verdict.FLAG
    return Verdict.PASS


def review(record: ApplicationRecord, extraction: LabelExtraction,
           elapsed_ms: int | None = None) -> ReviewResult:
    checks: list[CheckResult] = [
        check_brand_name(record.brand_name, extraction.brand_name),
        *check_alcohol_content(record.alcohol_content_pct, extraction.alcohol_statement),
        check_net_contents(record.net_contents, extraction.net_contents),
        check_warning_text(extraction.warning_text),
        check_warning_typography(extraction.warning_prefix_is_bold),
    ]
    return ReviewResult(
        cola_id=record.cola_id,
        verdict=aggregate(checks),
        checks=checks,
        elapsed_ms=elapsed_ms,
    )
