"""Runs every field policy and aggregates one overall verdict.

This module is the only place a ReviewResult is produced, it is pure, and it
never touches the network. That is what makes the decision auditable: an agent
can be shown exactly which rule fired and which regulation it came from.
"""

from __future__ import annotations

from app.models import ApplicationRecord, CheckResult, LabelExtraction, ReviewResult, Verdict
from app.rules.citations import Commodity, citation, commodity_of
from app.rules.fields import (
    BRAND_PASS_THRESHOLD,
    brand_similarity,
    check_alcohol_content,
    check_bottler,
    check_brand_name,
    check_class_type,
    check_country_of_origin,
    check_net_contents,
    parse_net_contents_ml,
)
from app.rules.warning import check_warning_text, check_warning_typography

# A field read below this confidence cannot support a rejection.
MIN_CONFIDENCE_TO_FAIL = 70.0

# Two questions, answered separately on the checklist. Label against its
# application: does the artwork say what the form says? Label against the
# regulation: does the artwork meet the rule whatever the form says? A label
# can match its application perfectly and still fail the second.
REGULATION_FIELDS = frozenset({
    "alcohol_format", "proof_consistency", "government_warning", "warning_typography",
})


def soften_unreliable_failures(
    checks: list[CheckResult], confidence: dict[str, float]
) -> list[CheckResult]:
    """Downgrade FAIL to FLAG where the underlying field was read poorly.

    The asymmetry is deliberate and is the core safety property of using OCR
    for this: a false rejection tells an applicant they broke the law, while a
    false flag costs an agent a minute. When the evidence is weak we pay the
    minute.

    Every row whose doubt comes from the read, softened or already a FLAG, is
    marked `read_uncertain`. That marker is what a second opinion is allowed
    to act on, and nothing else.
    """
    out: list[CheckResult] = []
    for check in checks:
        conf = confidence.get(check.field)
        low = conf is not None and conf < MIN_CONFIDENCE_TO_FAIL
        if check.verdict is Verdict.FAIL and low:
            out.append(check.model_copy(update={
                "verdict": Verdict.FLAG,
                "read_uncertain": True,
                "reason": (
                    f"{check.reason} This field was read with low confidence "
                    f"({conf:.0f}%), so it is referred for review rather than rejected."
                ),
            }))
        elif check.verdict is Verdict.FLAG and low and not check.read_uncertain:
            out.append(check.model_copy(update={"read_uncertain": True}))
        else:
            out.append(check)
    return out


def cite_for(checks: list[CheckResult], commodity: Commodity | None) -> list[CheckResult]:
    """Each row's citation from the part that governs this commodity."""
    out = []
    for check in checks:
        text = citation(check.field, commodity)
        out.append(check.model_copy(update={"citation": text}) if text else check)
    return out


def assign_layers(checks: list[CheckResult]) -> list[CheckResult]:
    return [c.model_copy(update={"layer": "regulation" if c.field in REGULATION_FIELDS
                                 else "application"}) for c in checks]


def aggregate(checks: list[CheckResult]) -> Verdict:
    """Worst non-advisory verdict wins; advisory checks can only raise to FLAG."""
    binding = [c for c in checks if not c.advisory]
    if any(c.verdict is Verdict.FAIL for c in binding):
        return Verdict.FAIL
    if any(c.verdict is Verdict.FLAG for c in checks):
        return Verdict.FLAG
    return Verdict.PASS


def container_volume_ml(record: ApplicationRecord, extraction: LabelExtraction) -> float | None:
    """The container size, from the application first and the artwork second.

    Used to state which 27 CFR 16.22(b) type-size minimum applies to the
    warning. The application is preferred because it is typed, not read.
    """
    for candidate in (record.net_contents, extraction.net_contents):
        if candidate:
            ml = parse_net_contents_ml(candidate)
            if ml is not None:
                return ml
    return None


def stacked_brand(record: ApplicationRecord,
                  extraction: LabelExtraction) -> tuple[str | None, str | None, bool]:
    """(brand, class/type, joined) with a two-line brand put back together.

    Extraction takes the largest line as the brand and the next smaller line
    as the class. A brand stacked over two sizes ("OLD TOM" over a smaller
    "DISTILLERY") is then split in two, and both checks fail on a compliant
    label. When the brand line alone does not match the application and the
    brand line plus the "class" line does, the two are one brand and the
    line after them is the class. Decided here, against the application,
    because extraction cannot know which it is.
    """
    brand, klass = extraction.brand_name, extraction.class_type
    if brand and klass and record.brand_name:
        joined = f"{brand} {klass}"
        if (brand_similarity(record.brand_name, brand) < BRAND_PASS_THRESHOLD
                <= brand_similarity(record.brand_name, joined)):
            return joined, extraction.class_type_next, True
    return brand, klass, False


def review(record: ApplicationRecord, extraction: LabelExtraction,
           elapsed_ms: int | None = None) -> ReviewResult:
    brand, klass, joined = stacked_brand(record, extraction)
    # The application's designation first: it is typed, not read.
    commodity = commodity_of(record.class_type, klass)
    brand_check = check_brand_name(record.brand_name, brand)
    if joined and brand_check.verdict is Verdict.PASS:
        brand_check = brand_check.model_copy(update={
            "reason": "The brand is set on two lines on the label; read together they match "
                      "the application. " + brand_check.reason})
    checks: list[CheckResult] = [
        brand_check,
        check_class_type(record.class_type, klass, record.brand_name),
        *check_alcohol_content(record.alcohol_content_pct, extraction.alcohol_statement,
                               commodity),
        check_net_contents(record.net_contents, extraction.net_contents),
        *check_bottler(record.bottler_name, record.bottler_address,
                       extraction.bottler_name, extraction.bottler_address),
        check_country_of_origin(record.country_of_origin, extraction.country_of_origin),
        check_warning_text(extraction.warning_text, extraction.warning_legibility),
        check_warning_typography(extraction.warning_prefix_is_bold,
                                 container_volume_ml(record, extraction),
                                 extraction.warning_small_type),
    ]
    checks = assign_layers(cite_for(
        soften_unreliable_failures(checks, extraction.field_confidence), commodity))
    return ReviewResult(
        cola_id=record.cola_id,
        verdict=aggregate(checks),
        checks=checks,
        elapsed_ms=elapsed_ms,
    )
