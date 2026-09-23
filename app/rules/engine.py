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
    normalize_brand,
    parse_net_contents_ml,
    same_words,
)
from app.rules.warning import check_warning_text, check_warning_typography

# A field read below this confidence cannot support a rejection. Printed
# text reads at 90% and up; on AI-generated photographs, garbage lines read
# at 72-79% ("TL" for "1 L", "Ganned DY" for "Canned by").
MIN_CONFIDENCE_TO_FAIL = 80.0

# Two questions, answered separately on the checklist. Label against its
# application: does the artwork say what the form says? Label against the
# regulation: does the artwork meet the rule whatever the form says? A label
# can match its application perfectly and still fail the second.
REGULATION_FIELDS = frozenset({
    "alcohol_format", "proof_consistency", "government_warning", "warning_typography",
})


def soften_unreliable_failures(
    checks: list[CheckResult], confidence: dict[str, float], soft: bool = False
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
        if check.verdict is Verdict.FAIL and soft:
            # An out-of-focus picture misreads with confidence: "750" as "790"
            # at 90%. Nothing read from it rejects, whatever OCR's score.
            out.append(check.model_copy(update={
                "verdict": Verdict.FLAG,
                "read_uncertain": True,
                "reason": (f"{check.reason} The image is out of focus or too small to read "
                           "reliably, so this is referred for review rather than rejected."),
            }))
        elif check.verdict is Verdict.FAIL and low:
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


# Fields whose absence is a finding only when the whole label was read.
ABSENCE_FIELDS = frozenset({
    "brand_name", "class_type", "alcohol_content", "net_contents", "bottler_name",
    "country_of_origin",
})


def soften_unconfirmed_absence(checks: list[CheckResult], unread: list[str],
                               small_print_unread: bool = False) -> list[CheckResult]:
    """Refer a field reported missing while part of the label went unread.

    "No net contents statement" is a finding only if every line was read. On
    an AI-generated vodka label "1 L" came back as "TL"; the statement was
    there, in the line OCR could not make sense of. Small print detected and
    not read (the warning's, usually) counts the same way: a slightly blurred
    wine label lost its bottler line along with it.
    """
    if not unread and not small_print_unread:
        return checks
    where = (f"Part of the label could not be read ({', '.join(repr(t) for t in unread[:3])})"
             if unread else "The small print on this image could not be read")
    return [_unconfirmed(c, f"{where}, so it may be there", ABSENCE_FIELDS | {"bottler_address"})
            for c in checks]


def _unconfirmed(check: CheckResult, why: str, fields: frozenset[str]) -> CheckResult:
    """A statement reported missing on an image that was not read in full.

    A rejection becomes a referral. A referral already made for an absence (a
    missing address only ever flags) is marked as a reading problem too, so
    triage ranks it with reading problems and a second reading may look again.
    """
    if check.observed is not None or check.field not in fields:
        return check
    if check.verdict is Verdict.FAIL:
        return check.model_copy(update={
            "verdict": Verdict.FLAG, "read_uncertain": True,
            "reason": f"{check.reason} {why}; it is referred for review rather than rejected."})
    if check.verdict is Verdict.FLAG and not check.read_uncertain:
        return check.model_copy(update={"read_uncertain": True,
                                        "reason": f"{check.reason} {why}."})
    return check


# A label that leaves out one required statement is defective. An image on
# which this many are not found was more likely not read in full: a close-up
# phone photograph of a compliant bourbon label gave OCR its top half only.
MOSTLY_UNREAD = 2


def soften_mostly_unread(checks: list[CheckResult]) -> list[CheckResult]:
    """Refer every missing statement when several are missing at once."""
    missing = {c.field for c in checks
               if c.verdict is Verdict.FAIL and c.observed is None
               and c.field in ABSENCE_FIELDS | {"government_warning"}}
    if len(missing) < MOSTLY_UNREAD:
        return checks
    why = (f"{len(missing)} required statements were not found on this image, which usually "
           "means it was not read in full")
    return [_unconfirmed(c, why, frozenset(missing) | {"bottler_address"}) for c in checks]


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
        if (not same_words(record.brand_name, brand)
                and brand_similarity(record.brand_name, joined) >= BRAND_PASS_THRESHOLD):
            return joined, extraction.class_type_next, True
    return brand, klass, False


def wrapped_class(record: ApplicationRecord, klass: str | None, following: str | None) -> str | None:
    """A designation set over two lines, put back together.

    "Kentucky Straight" over "Bourbon Whiskey" was read as the class
    "Kentucky Straight" and referred. When the class line alone is not the
    application's designation and the class line plus the next one is, the
    two are one designation. Decided against the application, as for a
    stacked brand.
    """
    if record.class_type and klass and following and not same_words(record.class_type, klass):
        joined = f"{klass} {following}"
        if same_words(record.class_type, joined):
            return joined
    return klass


def brand_is_designation(record: ApplicationRecord, brand: str | None) -> bool:
    """The line read as the brand is the application's class/type designation.

    Outlined or ornamental brand lettering can defeat OCR entirely, and then
    the largest line it did read, the designation, is taken for the brand.
    Found on an AI-generated Scotch label: "GLEN ARDEN" was not read, and the
    brand and class both failed against a compliant label. Another Tesseract
    build ran the two lines together as "ge Malt Whisky": every real word in it
    is the designation's and none is the brand's, which counts the same.
    """
    if not (record.class_type and brand) or same_words(record.brand_name, brand):
        return False
    if same_words(record.class_type, brand):
        return True
    words = [w for w in normalize_brand(brand).split() if len(w) >= 3]
    designation = set(normalize_brand(record.class_type).split())
    brand_words = set(normalize_brand(record.brand_name).split())
    return bool(words) and all(w in designation and w not in brand_words for w in words)


def read_brand_and_class(record: ApplicationRecord,
                         extraction: LabelExtraction) -> tuple[str | None, str | None, str]:
    """(brand, class/type, how they were read) as the rules see them.

    `how` is "stacked" for a two-line brand, "unread" when the brand was not
    read and its line reads as the designation, and "" otherwise. The
    evaluation scores extraction on the same values.
    """
    brand, klass, joined = stacked_brand(record, extraction)
    if joined:
        return brand, klass, "stacked"
    if brand_is_designation(record, brand):
        return None, brand, "unread"
    return brand, wrapped_class(record, klass, extraction.class_type_next), ""


def review(record: ApplicationRecord, extraction: LabelExtraction,
           elapsed_ms: int | None = None) -> ReviewResult:
    brand, klass, how = read_brand_and_class(record, extraction)
    # The application's designation first: it is typed, not read.
    commodity = commodity_of(record.class_type, klass)
    brand_check = check_brand_name(record.brand_name, brand)
    if how == "stacked" and brand_check.verdict is Verdict.PASS:
        brand_check = brand_check.model_copy(update={
            "reason": "The brand is set on two lines on the label; read together they match "
                      "the application. " + brand_check.reason})
    elif how == "unread":
        brand_check = brand_check.model_copy(update={
            "verdict": Verdict.FLAG, "read_uncertain": True,
            "reason": (f"The largest text read, {klass!r}, is the class/type designation, so the "
                       "brand name was not read; ornamental or outlined lettering can defeat "
                       "OCR. Confirm the brand on the artwork.")})
    class_check = check_class_type(record.class_type, klass, record.brand_name)
    if how == "unread" and class_check.verdict is Verdict.FAIL:
        # The designation was found by where the brand is. With the brand
        # unread, which line is the designation is not known either.
        class_check = class_check.model_copy(update={
            "verdict": Verdict.FLAG, "read_uncertain": True,
            "reason": (f"{class_check.reason} The brand was not read, so the line taken for "
                       "the designation may be another; confirm on the artwork.")})
    checks: list[CheckResult] = [
        brand_check,
        class_check,
        *check_alcohol_content(record.alcohol_content_pct, extraction.alcohol_statement,
                               commodity),
        check_net_contents(record.net_contents, extraction.net_contents, commodity),
        *check_bottler(record.bottler_name, record.bottler_address,
                       extraction.bottler_name, extraction.bottler_address),
        check_country_of_origin(record.country_of_origin, extraction.country_of_origin),
        check_warning_text(extraction.warning_text, extraction.warning_legibility,
                           extraction.warning_unsure),
        check_warning_typography(extraction.warning_prefix_is_bold,
                                 container_volume_ml(record, extraction),
                                 extraction.warning_small_type),
    ]
    # Several missing at once first: each is then referred for that reason,
    # before any single one is referred for an unread line beside it.
    checks = soften_unconfirmed_absence(soften_mostly_unread(checks), extraction.unread_text,
                                        extraction.warning_legibility == "illegible")
    checks = assign_layers(cite_for(
        soften_unreliable_failures(checks, extraction.field_confidence, extraction.image_soft),
        commodity))
    return ReviewResult(
        cola_id=record.cola_id,
        verdict=aggregate(checks),
        checks=checks,
        elapsed_ms=elapsed_ms,
    )
