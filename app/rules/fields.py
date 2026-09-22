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

BRAND_PASS_THRESHOLD = 95.0   # >= this: same brand, cosmetic difference only
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


def is_part_of(part: str, whole: str) -> bool:
    """Every word of `part` appears in `whole`, and `whole` has more words."""
    p, w = _tokens(part), _tokens(whole)
    return bool(p) and len(p) < len(w) and all(t in w for t in p)


def check_brand_name(expected: str, observed: str | None) -> CheckResult:
    citation = cite("brand_name", "spirits")
    if not observed:
        return CheckResult(
            field="brand_name", verdict=Verdict.FAIL, expected=expected,
            reason="No brand name found on the label.", citation=citation,
        )

    score = fuzz.ratio(normalize_brand(expected), normalize_brand(observed))

    if score >= BRAND_PASS_THRESHOLD:
        reason = "Exact match." if expected == observed else (
            f"Matches after normalization (case/punctuation differ, similarity {score:.0f}%)."
        )
        verdict = Verdict.PASS
    elif score >= BRAND_FLAG_THRESHOLD:
        verdict = Verdict.FLAG
        reason = f"Similar but not equivalent (similarity {score:.0f}%); agent review required."
    elif is_part_of(observed, expected):
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

    if implausible or proof_backs_application:
        why = (f"{abv:g}% is not a possible alcohol content" if implausible else
               f"the label's own proof statement ({proof:g} Proof) matches the application's "
               f"{expected_pct:g}%")
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
    r"(\d+(?:[.,]\d+)*)\s*"
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
    count); '1,75 L' is one and three quarters. '1 PINT 6 FL OZ', the form
    27 CFR 7.70 prescribes for malt beverages over a pint, is the sum.
    """
    found = list(_QTY.finditer(text))
    if not found:
        return None

    def ml(m: re.Match) -> float:
        unit = re.sub(r"[^a-z]", "", m.group(2).lower())
        digits = m.group(1)
        if unit in ("ml", "millilitre", "milliliter", "millilitres", "milliliters") \
                and re.fullmatch(r"\d{1,3}(?:,\d{3})+", digits):
            digits = digits.replace(",", "")
        return float(digits.replace(",", ".")) * _TO_ML[unit]

    first = found[0]
    total = ml(first)
    first_unit = re.sub(r"[^a-z]", "", first.group(2).lower())
    if first_unit.rstrip("s") in ("pint", "quart", "gallon") and len(found) > 1 \
            and "oz" in found[1].group(2).lower():
        total += ml(found[1])
    return total


def check_net_contents(expected: str | None, observed: str | None) -> CheckResult:
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
        return CheckResult(
            field="net_contents", verdict=Verdict.PASS, expected=expected, observed=observed,
            reason=f"Both resolve to {obs_ml:g} mL.", citation=citation,
        )
    return CheckResult(
        field="net_contents", verdict=Verdict.FAIL, expected=expected, observed=observed,
        reason=f"Label states {obs_ml:g} mL but the application states {exp_ml:g} mL.",
        citation=citation,
    )


# --- class / type designation ----------------------------------------------

# Shown when the application record omits a field. This is a gap in the
# submitted data, not a finding about the label, so it never changes the
# verdict -- but it stays visible on the checklist, because an agent needs to
# see that an element went unverified rather than quietly disappearing.
NOT_PROVIDED = "Not provided on the application, so this element was not verified."

CLASS_TYPE_PASS_THRESHOLD = 92.0
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
    if score < CLASS_TYPE_FLAG_THRESHOLD and brand and is_part_of(observed, brand):
        # "DISTILLERY" read as the class of "OLD TOM DISTILLERY": a line of a
        # stacked brand taken for the designation, so the designation itself
        # was not found. A reading problem, referred.
        return CheckResult(
            field="class_type", verdict=Verdict.FLAG, expected=expected, observed=observed,
            reason=(f"The line read as the class/type, {observed!r}, is part of the brand name, "
                    "so the designation may not have been found. Confirm on the artwork."),
            citation=citation, read_uncertain=True)
    if score < CLASS_TYPE_PASS_THRESHOLD and (is_part_of(observed, expected)
                                              or is_part_of(expected, observed)):
        # "Gin" against "Dry Gin", "Tequila" against "Tequila Blanco": one
        # designation contains the other. Whether the shorter one is enough
        # is a judgement about the class, so an agent makes it.
        return CheckResult(
            field="class_type", verdict=Verdict.FLAG, expected=expected, observed=observed,
            reason=(f"One designation contains the other ({observed!r} on the label, "
                    f"{expected!r} on the application); agent review required."),
            citation=citation)
    if score >= CLASS_TYPE_PASS_THRESHOLD:
        verdict, reason = Verdict.PASS, (
            "Exact match." if expected == observed
            else f"Matches after normalization (similarity {score:.0f}%)."
        )
    elif score >= CLASS_TYPE_FLAG_THRESHOLD:
        verdict = Verdict.FLAG
        reason = f"Designation differs from the application (similarity {score:.0f}%); agent review required."
    else:
        verdict = Verdict.FAIL
        reason = f"Class/type on the label does not match the application (similarity {score:.0f}%)."

    return CheckResult(field="class_type", verdict=verdict, expected=expected,
                       observed=observed, reason=reason, citation=citation)


# --- bottler / producer -----------------------------------------------------

BOTTLER_PASS_THRESHOLD = 88.0


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
        else:
            score = fuzz.token_set_ratio(normalize_brand(expected_name),
                                         normalize_brand(observed_name))
            if score >= BOTTLER_PASS_THRESHOLD:
                verdict, reason = Verdict.PASS, f"Matches the application (similarity {score:.0f}%)."
            elif score >= 65.0:
                verdict = Verdict.FLAG
                reason = f"Differs from the application (similarity {score:.0f}%); agent review required."
            else:
                verdict = Verdict.FAIL
                reason = f"Bottler name does not match the application (similarity {score:.0f}%)."
            results.append(CheckResult(
                field="bottler_name", verdict=verdict, expected=expected_name,
                observed=observed_name, reason=reason, citation=citation))

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
    """A record with no country, or a domestic one, is not an import."""
    return bool(country) and not _DOMESTIC.search(country)


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

    score = fuzz.token_set_ratio(normalize_brand(country_name(expected)),
                                 normalize_brand(observed_country))
    if score >= 80.0:
        return CheckResult(
            field="country_of_origin", verdict=Verdict.PASS, expected=expected,
            observed=observed, reason=f"Matches the application (similarity {score:.0f}%).",
            citation=citation)
    return CheckResult(
        field="country_of_origin", verdict=Verdict.FAIL, expected=expected,
        observed=observed,
        reason=f"Country of origin on the label does not match the application "
               f"(similarity {score:.0f}%).",
        citation=citation)
