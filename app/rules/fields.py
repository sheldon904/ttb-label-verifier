"""Per-field matching policies.

The central insight of this exercise: matching policy is per-field, not global.
Dave wants "STONE'S THROW" to pass against "Stone's Throw"; Jenny wants the
warning byte-exact. A single equality check fails both of them.
"""

from __future__ import annotations

import re
import unicodedata

from rapidfuzz import fuzz

from app.models import CheckResult, Verdict
from app.rules.citations import Commodity
from app.rules.citations import citation as cite

# --- brand name ------------------------------------------------------------

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_LEADING_ARTICLE = re.compile(r"^(the)\s+", re.IGNORECASE)

# A brand passes only on the same words (see same_words). Two lines are read
# as one stacked brand when together they reach this similarity.
BRAND_PASS_THRESHOLD = 95.0
BRAND_FLAG_THRESHOLD = 80.0   # >= this: plausibly the same, needs a human


def normalize_brand(name: str) -> str:
    """Fold away the differences that are not substantive to a brand identity."""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.casefold()
    s = _PUNCT.sub(" ", s)
    s = _LEADING_ARTICLE.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


def brand_similarity(a: str, b: str) -> float:
    return fuzz.ratio(normalize_brand(a), normalize_brand(b))


def _tokens(text: str) -> list[str]:
    return normalize_brand(text).split()


def same_words(a: str, b: str) -> bool:
    """Equal once case, accents, punctuation and spacing are set aside.

    "STONE'S THROW" is "Stone's Throw" and "STONES THROW". A letter is never
    set aside: "BUFFALO GRACE" is not "Buffalo Trace", however similar.
    """
    return normalize_brand(a).replace(" ", "") == normalize_brand(b).replace(" ", "")


def is_part_of(part: str, whole: str) -> bool:
    """Every word of `part` appears in `whole`, and `whole` has more words."""
    p, w = _tokens(part), _tokens(whole)
    return bool(p) and len(p) < len(w) and all(t in w for t in p)


def is_fragment_of(part: str, whole: str) -> bool:
    """`part` reads as a piece of `whole`: "STILLERY" of "Old Tom Distillery",
    "entucky Straight" of "Kentucky Straight Bourbon Whiskey". What a photograph
    that cuts off or curves away part of a line gives OCR."""
    p, w = normalize_brand(part), normalize_brand(whole)
    return 4 <= len(p) < len(w) and fuzz.partial_ratio(p, w) >= 90


def check_brand_name(expected: str, observed: str | None) -> CheckResult:
    citation = cite("brand_name", "spirits")
    if not observed:
        return CheckResult(
            field="brand_name", verdict=Verdict.FAIL, expected=expected,
            reason="No brand name found on the label.", citation=citation,
        )

    score = fuzz.ratio(normalize_brand(expected), normalize_brand(observed))

    if same_words(expected, observed):
        reason = "Exact match." if expected == observed else (
            "Matches; only case, punctuation or spacing differ."
        )
        verdict = Verdict.PASS
    elif score >= BRAND_FLAG_THRESHOLD:
        # One letter apart is a different mark ("Buffalo Grace") or a misread;
        # either way a person decides.
        verdict = Verdict.FLAG
        reason = f"Similar but not the same (similarity {score:.0f}%); agent review required."
    elif is_part_of(observed, expected) or is_fragment_of(observed, expected):
        # "OLD TOM" read from a label whose brand is "Old Tom Distillery": part
        # of the brand was read and the rest was not, or sits on a line that
        # was taken for something else. That is a partial read, not a
        # different brand, so it is referred.
        return CheckResult(
            field="brand_name", verdict=Verdict.FLAG, expected=expected, observed=observed,
            reason=(f"The label reads {observed!r}, which is part of the application's brand. "
                    "The rest may be set on another line or may not have been read; "
                    "confirm on the artwork."),
            citation=citation, read_uncertain=True,
        )
    elif is_part_of(expected, observed):
        # The application's brand and more: a fanciful name set in the same
        # type as the brand, read together with it. The agent decides whether
        # the extra words belong to the brand.
        return CheckResult(
            field="brand_name", verdict=Verdict.FLAG, expected=expected, observed=observed,
            reason=(f"The label reads {observed!r}, which contains the application's brand "
                    "and more. Confirm on the artwork whether the extra words are part of "
                    "the brand name."),
            citation=citation,
        )
    else:
        verdict = Verdict.FAIL
        reason = f"Brand name on label does not match the application (similarity {score:.0f}%)."

    return CheckResult(
        field="brand_name", verdict=verdict, expected=expected,
        observed=observed, reason=reason, citation=citation,
    )


# --- alcohol content -------------------------------------------------------

# A decimal comma is accepted ("40,5% vol" on European imports); without it
# the pattern matched "5%" inside "40,5%" and rejected a compliant label.
_ABV = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:%|percent\b)", re.IGNORECASE)
_PROOF = re.compile(r"(\d+(?:[.,]\d+)?)\s*proof", re.IGNORECASE)

# No tolerance, on purpose. 27 CFR 5.65(c) allows 0.3 percentage points between
# the labeled alcohol content and the ACTUAL content of the product, which is a
# laboratory question and out of scope here. Between the label and the
# application there is no tolerance: the application states what the label
# says, and a label that says something else is a different label. (Wine, 27 CFR
# 4.36, and malt beverages, 7.65, carry their own actual-versus-labeled
# tolerances; none applies to this comparison either.)
ABV_TOLERANCE_PCT = 0.0

# 27 CFR 5.65(b): the statement must express alcohol by volume, in one of
# "Alcohol __% by volume", "__% alcohol by volume" or "Alcohol by volume __%",
# with "alc", "%", "/" and "vol" as the permitted abbreviations. A bare "45%"
# is not a compliant statement even when the number is right.
_ALC_WORD = re.compile(r"\balc(?:ohol)?\b", re.IGNORECASE)
# "Val." is a common misread of "Vol."; this check is advisory, so it is forgiven.
_VOL_WORD = re.compile(r"\bv[oa0]l(?:ume)?\b", re.IGNORECASE)
_PCT_WORD = re.compile(r"%|\bpercent\b", re.IGNORECASE)


def check_alcohol_format(statement: str) -> CheckResult:
    """Advisory: does the statement use a 5.65(b) form? Never rejects on its own.

    Wording variants are an agent's call, and this must not turn an OCR
    dropout of the word "Vol." into a rejection.
    """
    citation = cite("alcohol_format", "spirits")
    ok = bool(_ALC_WORD.search(statement) and _VOL_WORD.search(statement)
              and _PCT_WORD.search(statement))
    if ok:
        return CheckResult(
            field="alcohol_format", verdict=Verdict.PASS, observed=statement,
            reason="Stated as alcohol by volume in a permitted form.",
            citation=citation, advisory=True,
        )
    return CheckResult(
        field="alcohol_format", verdict=Verdict.FLAG, observed=statement,
        reason=(
            "The percentage is present but the statement does not read as one of the "
            "permitted forms ('Alcohol __% by volume', '__% alcohol by volume' or "
            "'Alcohol by volume __%'; 'alc', '%', '/' and 'vol' may be abbreviated). "
            "Confirm the wording on the artwork."
        ),
        citation=citation, advisory=True,
    )


def _number(text: str) -> float:
    """'45' -> 45.0, '40,5' -> 40.5 (European decimal comma)."""
    return float(text.replace(",", "."))


def parse_alcohol_statement(statement: str) -> tuple[float | None, float | None]:
    """Return (abv_pct, proof) from a verbatim statement like '45% Alc./Vol. (90 Proof)'."""
    abv = _number(m.group(1)) if (m := _ABV.search(statement)) else None
    proof = _number(m.group(1)) if (m := _PROOF.search(statement)) else None
    return abv, proof


# No beverage is stronger than this; a reading above it is a misread.
MAX_PLAUSIBLE_ABV = 96.0


def _statement_may_be_omitted(commodity: Commodity | None, expected_pct: float) -> str | None:
    """Why a label of this commodity may lawfully carry no alcohol statement."""
    if commodity == "malt":
        return ("An alcohol content statement is optional on a malt beverage unless alcohol "
                "comes from added flavors or other nonbeverage ingredients (27 CFR 7.63(a)(3), "
                "7.65(a)). Confirm whether that applies.")
    if commodity == "wine" and expected_pct <= 14:
        return ("A wine of 14% or less may omit the statement when the label designates it "
                '"table wine" or "light wine" (27 CFR 4.36(a)). Confirm the designation on '
                "the artwork.")
    return None


def check_alcohol_content(expected_pct: float | None, statement: str | None,
                          commodity: Commodity | None = None) -> list[CheckResult]:
    citation = cite("alcohol_content", "spirits")
    results: list[CheckResult] = []

    if statement is None:
        if expected_pct is None:
            # The brief notes exceptions for certain wine and beer. With nothing
            # to compare against, absence is a question for an agent, not a
            # rejection issued on the strength of an empty application field.
            results.append(CheckResult(
                field="alcohol_content", verdict=Verdict.FLAG,
                reason=("No alcohol content statement found on the label, and the "
                        "application does not state one. Required for distilled "
                        "spirits; confirm whether an exception applies."),
                citation=citation,
            ))
            return results
        exception = _statement_may_be_omitted(commodity, expected_pct)
        if exception:
            # Rejecting a beer for leaving off a statement the regulation makes
            # optional would be a false rejection, so an agent decides.
            results.append(CheckResult(
                field="alcohol_content", verdict=Verdict.FLAG,
                expected=f"{expected_pct}% Alc./Vol.",
                reason="No alcohol content statement found on the label. " + exception,
                citation=citation,
            ))
            return results
        results.append(CheckResult(
            field="alcohol_content", verdict=Verdict.FAIL,
            expected=f"{expected_pct}% Alc./Vol.",
            reason="No alcohol content statement found on the label.", citation=citation,
        ))
        return results

    abv, proof = parse_alcohol_statement(statement)

    # Two readings of one fact. When the label's own proof statement agrees
    # with the application and its percentage does not, the percentage is far
    # more likely misread than the label wrong: a phone photo read "45% ...
    # (90 Proof)" as "495% ... (90 Proof)". Either way it goes to an agent;
    # it is never rejected on the reading that disagrees with the rest.
    proof_backs_application = (
        abv is not None and proof is not None and expected_pct is not None
        and abs(proof - 2 * expected_pct) < 0.1 and abs(abv - expected_pct) > ABV_TOLERANCE_PCT
    )
    implausible = abv is not None and not 0 < abv <= MAX_PLAUSIBLE_ABV
    # "6.5%" read as "65%": the decimal point is the smallest mark in the
    # statement and the first a blurred photo loses.
    decimal_slip = (abv is not None and expected_pct is not None and not implausible
                    and (abs(abv - 10 * expected_pct) < 0.01 or abs(10 * abv - expected_pct) < 0.01))

    if implausible or proof_backs_application or decimal_slip:
        why = (f"{abv:g}% is not a possible alcohol content" if implausible else
               f"the label's own proof statement ({proof:g} Proof) matches the application's "
               f"{expected_pct:g}%" if proof_backs_application else
               f"it differs from the application's {expected_pct:g}% only by a decimal point")
        results.append(CheckResult(
            field="alcohol_content", verdict=Verdict.FLAG, observed=statement,
            expected=f"{expected_pct}% Alc./Vol." if expected_pct is not None else None,
            reason=(f"The percentage was read as {abv:g}%, but {why}, so it is probably "
                    "misread. Confirm on the artwork."),
            citation=citation, read_uncertain=True,
        ))
        results.append(check_alcohol_format(statement))
        if proof is not None:
            results.append(CheckResult(
                field="proof_consistency", verdict=Verdict.FLAG, observed=statement,
                reason=("The proof statement cannot be checked against a percentage that "
                        "was probably misread. Confirm on the artwork."),
                citation=citation, read_uncertain=True,
            ))
        return results

    if abv is None:
        results.append(CheckResult(
            field="alcohol_content", verdict=Verdict.FLAG, observed=statement,
            expected=f"{expected_pct}% Alc./Vol." if expected_pct is not None else None,
            reason="Could not parse a percentage from the alcohol statement.", citation=citation,
            read_uncertain=True,
        ))
    elif expected_pct is None:
        results.append(CheckResult(
            field="alcohol_content", verdict=Verdict.PASS, observed=statement,
            reason=NOT_PROVIDED, citation=citation, advisory=True,
        ))
    elif abs(abv - expected_pct) <= ABV_TOLERANCE_PCT:
        results.append(CheckResult(
            field="alcohol_content", verdict=Verdict.PASS, observed=statement,
            expected=f"{expected_pct}% Alc./Vol.",
            reason=f"Label states {abv}% Alc./Vol., matching the application.", citation=citation,
        ))
    else:
        results.append(CheckResult(
            field="alcohol_content", verdict=Verdict.FAIL, observed=statement,
            expected=f"{expected_pct}% Alc./Vol.",
            reason=f"Label states {abv}% but the application states {expected_pct}%.",
            citation=citation,
        ))

    if abv is not None:
        results.append(check_alcohol_format(statement))

    # Internal consistency: US proof is exactly twice ABV. The sample label in the
    # brief reads "45% Alc./Vol. (90 Proof)" -- a label can be self-contradictory
    # while still matching the application, and an agent should see that.
    if abv is not None and proof is not None:
        consistent = abs(proof - (abv * 2)) < 0.05
        results.append(CheckResult(
            field="proof_consistency", verdict=Verdict.PASS if consistent else Verdict.FAIL,
            observed=statement, expected=f"{abv * 2:g} Proof",
            reason=(
                f"{abv}% Alc./Vol. is consistent with {proof:g} proof."
                if consistent else
                f"Label is internally inconsistent: {abv}% Alc./Vol. corresponds to "
                f"{abv * 2:g} proof, but the label states {proof:g} proof."
            ),
            citation=citation,
        ))

    return results


# --- net contents ----------------------------------------------------------

_QTY = re.compile(
    r"(\d+\s*/\s*\d+|\d+(?:[.,]\d+)*)\s*"
    r"(fl\.?\s*oz|fluid\s+ounces?|pints?|quarts?|gallons?|ml|millilitres?|milliliters?|cl"
    r"|centilitres?|centiliters?|l|liters?|litres?)(?![a-z])",
    re.IGNORECASE,
)
# US malt beverages are labelled in fluid ounces (27 CFR 7.70); 1 US fl oz is
# 29.5735 mL, so "12 FL OZ" and "355 mL" are the same container.
_TO_ML = {"ml": 1.0, "millilitre": 1.0, "milliliter": 1.0,
          "millilitres": 1.0, "milliliters": 1.0,
          "cl": 10.0, "centilitre": 10.0, "centiliter": 10.0,
          "centilitres": 10.0, "centiliters": 10.0,
          "l": 1000.0, "liter": 1000.0, "litre": 1000.0, "liters": 1000.0, "litres": 1000.0,
          "floz": 29.5735, "fluidounce": 29.5735, "fluidounces": 29.5735,
          "pint": 473.176, "pints": 473.176, "quart": 946.353, "quarts": 946.353,
          "gallon": 3785.41, "gallons": 3785.41}

# A metric statement is exact to the millilitre. A fluid-ounce statement is
# printed to a tenth of an ounce (750 mL is "25.4 FL OZ", 250 mL is "8.4 FL OZ",
# which is 1.6 mL short), so it is allowed a tenth of an ounce. No two
# standard container sizes are that close.
NET_CONTENTS_TOLERANCE_ML = 1.0
FL_OZ_TOLERANCE_ML = 2.96


def parse_net_contents_ml(text: str) -> float | None:
    """'750 mL' == '750ml' == '75 cl' == '0.75 L'; '12 FL OZ' == 354.9 mL.

    '1,000 mL' is a thousand (a comma before three digits of a millilitre
    count); '1,75 L' is one and three quarters. '1/2 GALLON' is a half.
    '1 PINT 6 FL OZ' and '1 QUART 1 PINT', the forms 27 CFR 7.70 prescribes
    for malt beverages, are sums: each US unit smaller than the last is added.
    """
    found = list(_QTY.finditer(text))
    if not found:
        return None

    def unit_of(m: re.Match) -> str:
        return re.sub(r"[^a-z]", "", m.group(2).lower())

    def ml(m: re.Match) -> float:
        unit = unit_of(m)
        digits = m.group(1)
        if "/" in digits:
            numerator, denominator = (float(x) for x in digits.split("/"))
            return numerator / denominator * _TO_ML[unit] if denominator else 0.0
        if unit in ("ml", "millilitre", "milliliter", "millilitres", "milliliters") \
                and re.fullmatch(r"\d{1,3}(?:,\d{3})+", digits):
            digits = digits.replace(",", "")
        return float(digits.replace(",", ".")) * _TO_ML[unit]

    us_rank = {"gallon": 4, "quart": 3, "pint": 2, "floz": 1, "fluidounce": 1}
    total = ml(found[0])
    rank = us_rank.get(unit_of(found[0]).rstrip("s"), 0)
    for m in found[1:]:
        next_rank = us_rank.get(unit_of(m).rstrip("s"), 0)
        if not 0 < next_rank < rank:
            break
        total += ml(m)
        rank = next_rank
    return total


# 27 CFR 5.203(a) and 4.72(a): the only container sizes spirits and wine may
# be sold in, in mL. Wine also comes in even liters from 4 L up (4.72(b)).
STANDARD_FILLS_ML: dict[str, tuple[int, ...]] = {
    "spirits": (3750, 3000, 2000, 1800, 1750, 1000, 945, 900, 750, 720, 710, 700, 570, 500,
                475, 375, 355, 350, 331, 250, 200, 187, 100, 50),
    "wine": (3000, 2250, 1800, 1500, 1000, 750, 720, 700, 620, 600, 568, 550, 500, 473, 375,
             360, 355, 330, 300, 250, 200, 187, 180, 100, 50),
}
_FILL_SECTION = {"spirits": "27 CFR 5.203", "wine": "27 CFR 4.72"}


_METRIC_UNIT = re.compile(r"\d\s*(?:ml|millilit(?:re|er)s?|l|lit(?:re|er)s?)\b", re.IGNORECASE)
_US_UNIT = re.compile(r"\b(?:fl\.?\s*oz|fluid\s+ounces?|pints?|quarts?|gallons?)\b", re.IGNORECASE)


def _required_units_missing(statement: str, commodity: Commodity | None) -> str | None:
    """Which unit rule a net contents statement breaks, as a sentence.

    Spirits and wine are stated in liters or milliliters (27 CFR 5.70(a),
    4.37(a)); centiliters and U.S. units may appear only beside that. Malt
    beverages are stated in U.S. units (7.70); metric may appear only beside
    them. "75 cl" alone on a whisky states the right volume the wrong way.
    """
    if commodity in ("spirits", "wine") and not _METRIC_UNIT.search(statement):
        section = "27 CFR 5.70(a)" if commodity == "spirits" else "27 CFR 4.37(a)"
        return (f"the label states it as {statement!r}. {section} requires liters or "
                "milliliters; other units may appear only beside that statement. Confirm "
                "on the artwork.")
    if commodity == "malt" and not _US_UNIT.search(statement):
        return (f"the label states it as {statement!r}. 27 CFR 7.70 requires U.S. units "
                "(fluid ounces, pints, quarts or gallons); metric may appear only beside "
                "them. Confirm on the artwork.")
    return None


def is_standard_fill(ml: float, commodity: Commodity | None) -> bool | None:
    """Whether a volume is an authorized size; None where none are prescribed."""
    sizes = STANDARD_FILLS_ML.get(commodity or "")
    if not sizes:
        return None
    if commodity == "wine" and ml >= 4000:
        return abs(ml / 1000 - round(ml / 1000)) < 0.001
    # 3 mL covers a US-unit statement rounded to a tenth of an ounce.
    return any(abs(ml - size) <= 3 for size in sizes)


def check_net_contents(expected: str | None, observed: str | None,
                       commodity: Commodity | None = None) -> CheckResult:
    citation = cite("net_contents", "spirits")
    if not observed:
        return CheckResult(
            field="net_contents", verdict=Verdict.FAIL, expected=expected,
            reason="No net contents statement found on the label.", citation=citation,
        )
    if not expected:
        return CheckResult(
            field="net_contents", verdict=Verdict.PASS, observed=observed,
            reason=NOT_PROVIDED, citation=citation, advisory=True,
        )

    exp_ml, obs_ml = parse_net_contents_ml(expected), parse_net_contents_ml(observed)
    if exp_ml is None or obs_ml is None:
        return CheckResult(
            field="net_contents", verdict=Verdict.FLAG, expected=expected, observed=observed,
            reason="Could not parse a volume from one or both values.", citation=citation,
            read_uncertain=obs_ml is None,
        )
    tolerance = (FL_OZ_TOLERANCE_ML if "oz" in f"{expected} {observed}".lower()
                 else NET_CONTENTS_TOLERANCE_ML)
    if abs(exp_ml - obs_ml) <= tolerance:
        wrong_form = _required_units_missing(observed, commodity)
        if wrong_form:
            # The right volume in a form the part does not accept. Referred:
            # OCR may have missed the required statement printed nearby.
            return CheckResult(
                field="net_contents", verdict=Verdict.FLAG, expected=expected, observed=observed,
                reason=f"Both resolve to {obs_ml:.0f} mL, but {wrong_form}", citation=citation,
            )
        return CheckResult(
            field="net_contents", verdict=Verdict.PASS, expected=expected, observed=observed,
            reason=f"Both resolve to {obs_ml:.0f} mL.", citation=citation,
        )
    if is_standard_fill(obs_ml, commodity) is False and is_standard_fill(exp_ml, commodity):
        # "750 mL" read as "790 mL" or "7950 mL". No such bottle can be sold,
        # so the reading is far likelier wrong than the label.
        return CheckResult(
            field="net_contents", verdict=Verdict.FLAG, expected=expected, observed=observed,
            reason=(f"The label reads {obs_ml:g} mL, which is not an authorized container size "
                    f"for {'wine' if commodity == 'wine' else 'distilled spirits'} "
                    f"({_FILL_SECTION[commodity]}), so it is probably misread. The application "
                    f"states {exp_ml:g} mL; confirm on the artwork."),
            citation=citation, read_uncertain=True,
        )
    return CheckResult(
        field="net_contents", verdict=Verdict.FAIL, expected=expected, observed=observed,
        reason=f"Label states {obs_ml:.0f} mL but the application states {exp_ml:.0f} mL.",
        citation=citation,
    )


# --- class / type designation ----------------------------------------------

# Shown when the application record omits a field. This is a gap in the
# submitted data, not a finding about the label, so it never changes the
# verdict -- but it stays visible on the checklist, because an agent needs to
# see that an element went unverified rather than quietly disappearing.
NOT_PROVIDED = "Not provided on the application, so this element was not verified."

CLASS_TYPE_FLAG_THRESHOLD = 75.0


def check_class_type(expected: str | None, observed: str | None,
                     brand: str | None = None) -> CheckResult:
    """The class/type designation, e.g. "Kentucky Straight Bourbon Whiskey".

    Stricter than a brand name, because the designation is regulated vocabulary
    rather than a mark: "Straight Bourbon" and "Blended Bourbon" are different
    products, not spelling variants. Case and spacing are still forgiven.
    """
    citation = cite("class_type", "spirits")
    if expected is None:
        return CheckResult(
            field="class_type", verdict=Verdict.PASS, observed=observed,
            reason=NOT_PROVIDED, citation=citation, advisory=True,
        )
    if not observed:
        return CheckResult(
            field="class_type", verdict=Verdict.FAIL, expected=expected,
            reason="No class or type designation found on the label.", citation=citation,
        )

    score = fuzz.ratio(normalize_brand(expected), normalize_brand(observed))
    if same_words(expected, observed):
        return CheckResult(
            field="class_type", verdict=Verdict.PASS, expected=expected, observed=observed,
            reason="Exact match." if expected == observed
            else "Matches; only case, punctuation or spacing differ.",
            citation=citation)
    if score < CLASS_TYPE_FLAG_THRESHOLD and is_fragment_of(observed, expected):
        return CheckResult(
            field="class_type", verdict=Verdict.FLAG, expected=expected, observed=observed,
            reason=(f"The label reads {observed!r}, which looks like part of the application's "
                    "designation; the rest may not have been read. Confirm on the artwork."),
            citation=citation, read_uncertain=True)
    if score < CLASS_TYPE_FLAG_THRESHOLD and brand and is_part_of(observed, brand):
        # "DISTILLERY" read as the class of "OLD TOM DISTILLERY": a line of a
        # stacked brand taken for the designation, so the designation itself
        # was not found. A reading problem, referred.
        return CheckResult(
            field="class_type", verdict=Verdict.FLAG, expected=expected, observed=observed,
            reason=(f"The line read as the class/type, {observed!r}, is part of the brand name, "
                    "so the designation may not have been found. Confirm on the artwork."),
            citation=citation, read_uncertain=True)
    if is_part_of(observed, expected) or is_part_of(expected, observed):
        # "Gin" against "Dry Gin", "Tequila" against "Tequila Blanco": one
        # designation contains the other. Whether the shorter one is enough
        # is a judgement about the class, so an agent makes it.
        return CheckResult(
            field="class_type", verdict=Verdict.FLAG, expected=expected, observed=observed,
            reason=(f"One designation contains the other ({observed!r} on the label, "
                    f"{expected!r} on the application); agent review required."),
            citation=citation)
    # The designation is regulated vocabulary: "California Rose Wine" is not
    # "California Red Wine" at any similarity, so nothing short of the same
    # words passes.
    if score >= CLASS_TYPE_FLAG_THRESHOLD:
        verdict = Verdict.FLAG
        reason = f"Designation differs from the application (similarity {score:.0f}%); agent review required."
    else:
        verdict = Verdict.FAIL
        reason = f"Class/type on the label does not match the application (similarity {score:.0f}%)."

    return CheckResult(field="class_type", verdict=verdict, expected=expected,
                       observed=observed, reason=reason, citation=citation)


# --- bottler / producer -----------------------------------------------------

BOTTLER_PASS_THRESHOLD = 88.0

# "Distilled and bottled by", "Imported by": the statement's phrase, not the name.
_BY_PHRASE = re.compile(r"^.*?\bby\b[\s:]*", re.IGNORECASE)
# Words every producer shares. Compared with them left in, "XYZ Distilling
# Company" scored 90% against "ABC Distilling Company" and passed.
_GENERIC_NAME_WORDS = frozenset({
    "co", "company", "inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation",
    "distilling", "distillery", "distilleries", "distillers", "brewing", "brewery", "brewers",
    "winery", "wines", "vineyards", "vineyard", "cellars", "spirits", "imports", "importers",
    "importing", "trading", "group", "the", "and", "of",
})


def distinctive_name(name: str) -> str:
    """The words that tell one producer from another."""
    words = normalize_brand(_BY_PHRASE.sub("", name)).split()
    kept = [w for w in words if w not in _GENERIC_NAME_WORDS]
    return " ".join(kept or words)


ADDRESS_AS_NAME_THRESHOLD = 80.0


def is_address_of(observed_name: str, expected_address: str | None) -> bool:
    """Whether the text read as the name is the application's address."""
    if not expected_address:
        return False
    return fuzz.token_sort_ratio(normalize_brand(_BY_PHRASE.sub("", observed_name)),
                                 normalize_brand(expected_address)) >= ADDRESS_AS_NAME_THRESHOLD


def check_bottler(expected_name: str | None, expected_address: str | None,
                  observed_name: str | None, observed_address: str | None) -> list[CheckResult]:
    """Name and address of the bottler or producer.

    Matched with token-set similarity rather than a straight ratio, because an
    address legitimately varies in ordering and abbreviation between a form field
    and printed artwork ("Bardstown, KY" against "Bardstown, Kentucky"). A name
    mismatch is substantive and can fail; an address mismatch only ever flags,
    since formatting variance is the common case and a wrong rejection here
    would be for a difference that carries no regulatory meaning.
    """
    citation = cite("bottler_name", "spirits")
    results: list[CheckResult] = []

    if not expected_name:
        results.append(CheckResult(
            field="bottler_name", verdict=Verdict.PASS, observed=observed_name,
            reason=NOT_PROVIDED, citation=citation, advisory=True))
    if not expected_address:
        results.append(CheckResult(
            field="bottler_address", verdict=Verdict.PASS, observed=observed_address,
            reason=NOT_PROVIDED, citation=citation, advisory=True))

    if expected_name:
        if not observed_name:
            results.append(CheckResult(
                field="bottler_name", verdict=Verdict.FAIL, expected=expected_name,
                reason="No bottler or producer name found on the label.", citation=citation))
        elif not normalize_brand(_BY_PHRASE.sub("", observed_name)):
            # "istilled and Bottled by" with nothing after it: the statement
            # was found and the name in it was not read. Compared as a name,
            # it scored 0% and failed a compliant phone photograph when another
            # deskew fill was tried.
            results.append(CheckResult(
                field="bottler_name", verdict=Verdict.FLAG, expected=expected_name,
                observed=observed_name, read_uncertain=True, citation=citation,
                reason=(f"The bottler statement reads {observed_name!r}, and the name after "
                        "it could not be read. Confirm on the artwork.")))
        else:
            score = fuzz.token_sort_ratio(distinctive_name(expected_name),
                                          distinctive_name(observed_name))
            unsure = False
            if score >= BOTTLER_PASS_THRESHOLD:
                verdict, reason = Verdict.PASS, f"Matches the application (similarity {score:.0f}%)."
            elif is_part_of(_BY_PHRASE.sub("", observed_name), expected_name):
                verdict = Verdict.FLAG
                reason = (f"The label reads {observed_name!r}, which is part of the application's "
                          "name; the rest may not have been read. Confirm on the artwork.")
            elif is_address_of(observed_name, expected_address):
                # "Bardstown, Kentucky" read as the name: OCR could not read
                # the name line, and the address under it took its place. The
                # stress test found this on heavy JPEG and on a tilted copy of
                # compliant labels, each of which failed.
                verdict, unsure = Verdict.FLAG, True
                reason = (f"The line read as the name, {observed_name!r}, is the application's "
                          "address, so the name line may not have been read. Confirm on the artwork.")
            elif score >= 65.0:
                verdict = Verdict.FLAG
                reason = f"Differs from the application (similarity {score:.0f}%); agent review required."
            else:
                verdict = Verdict.FAIL
                reason = f"Bottler name does not match the application (similarity {score:.0f}%)."
            results.append(CheckResult(
                field="bottler_name", verdict=verdict, expected=expected_name,
                observed=observed_name, reason=reason, citation=citation, read_uncertain=unsure))

    if expected_address:
        if not observed_address:
            results.append(CheckResult(
                field="bottler_address", verdict=Verdict.FLAG, expected=expected_address,
                reason="No bottler address found on the label.", citation=citation))
        else:
            score = fuzz.token_set_ratio(normalize_brand(expected_address),
                                         normalize_brand(observed_address))
            verdict = Verdict.PASS if score >= 80.0 else Verdict.FLAG
            reason = (f"Matches the application (similarity {score:.0f}%)." if verdict is Verdict.PASS
                      else f"Differs from the application (similarity {score:.0f}%). Address "
                           "formatting varies between forms and artwork, so this is referred "
                           "for review rather than rejected.")
            results.append(CheckResult(
                field="bottler_address", verdict=verdict, expected=expected_address,
                observed=observed_address, reason=reason, citation=citation))

    return results


# --- country of origin ------------------------------------------------------

_DOMESTIC = re.compile(r"\b(united states|u\.?s\.?a?\.?|america)\b", re.IGNORECASE)

# "Product of Scotland" and "Product of Canada" are 83% similar as whole
# strings, because they share the boilerplate. Comparing them intact would pass
# a Scotch declared as Canadian. Only the country itself is compared.
_ORIGIN_BOILERPLATE = re.compile(
    r"^\s*(?:product|produce|produced|bottled|distilled|made|imported)\s+"
    r"(?:of|in|by|from)\s*(?:the\s+)?",
    re.IGNORECASE,
)


def country_name(value: str) -> str:
    """Strip the declaration boilerplate, leaving the country."""
    return _ORIGIN_BOILERPLATE.sub("", value).strip(" .,")


def is_import(country: str | None) -> bool:
    """A record with no country, or a domestic one, is not an import.

    A label's "United Stafes" is OCR, not an import: close spellings of the
    domestic names count as domestic.
    """
    if not country or _DOMESTIC.search(country):
        return False
    name = normalize_brand(country_name(country))
    return not any(fuzz.ratio(name, domestic) >= 85
                   for domestic in ("united states", "united states of america", "america"))


def check_country_of_origin(expected: str | None, observed: str | None) -> CheckResult:
    """Required on imports only.

    Deliberately conditional: demanding a country-of-origin statement on a
    Kentucky bourbon would generate a rejection for omitting something the
    regulation never asked for.
    """
    citation = cite("country_of_origin", "spirits")

    if expected is None:
        return CheckResult(
            field="country_of_origin", verdict=Verdict.PASS, observed=observed,
            reason=NOT_PROVIDED, citation=citation, advisory=True,
        )

    if not is_import(expected) and observed and is_import(observed):
        return CheckResult(
            field="country_of_origin", verdict=Verdict.FLAG, expected=expected,
            observed=observed, citation=citation,
            reason=(f"The label states {observed!r}, but the application declares a domestic "
                    "product. Confirm the country of origin with the applicant."))

    if not is_import(expected):
        return CheckResult(
            field="country_of_origin", verdict=Verdict.PASS, expected=expected,
            observed=observed,
            reason="Not an imported product; a country of origin statement is not required.",
            citation=citation, advisory=True,
        )

    if not observed:
        return CheckResult(
            field="country_of_origin", verdict=Verdict.FAIL, expected=expected,
            reason=f"The application declares an imported product ({expected}) but no country "
                   "of origin statement was found on the label.",
            citation=citation,
        )

    # A declaration whose country did not survive the read ("Product of" with
    # nothing after it) is an incomplete transcription, not a wrong country.
    # Blur truncated exactly this on the fixture set, and rejecting on it would
    # have told an importer their country statement was wrong when it was right.
    observed_country = country_name(observed)
    if not observed_country:
        return CheckResult(
            field="country_of_origin", verdict=Verdict.FLAG, expected=expected,
            observed=observed,
            reason="The country of origin statement was found but the country itself "
                   "could not be read. Confirm against the artwork.",
            citation=citation, read_uncertain=True,
        )

    # The same country, or nothing: "Austria" is 88% similar to "Australia",
    # and "Northern Ireland" contains "Ireland". A near spelling is referred,
    # because OCR produces those too.
    if same_words(country_name(expected), observed_country):
        return CheckResult(
            field="country_of_origin", verdict=Verdict.PASS, expected=expected,
            observed=observed, reason="Matches the application.", citation=citation)
    score = fuzz.ratio(normalize_brand(country_name(expected)), normalize_brand(observed_country))
    if score >= 80.0:
        return CheckResult(
            field="country_of_origin", verdict=Verdict.FLAG, expected=expected,
            observed=observed, citation=citation,
            reason=(f"The country on the label is similar to the application's but not the same "
                    f"(similarity {score:.0f}%). It may be misread; confirm on the artwork."))
    return CheckResult(
        field="country_of_origin", verdict=Verdict.FAIL, expected=expected,
        observed=observed,
        reason=f"Country of origin on the label does not match the application "
               f"(similarity {score:.0f}%).",
        citation=citation)
