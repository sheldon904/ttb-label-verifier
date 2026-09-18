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


def check_brand_name(expected: str, observed: str | None) -> CheckResult:
    citation = "27 CFR 5.63 (brand name)"
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
    else:
        verdict = Verdict.FAIL
        reason = f"Brand name on label does not match the application (similarity {score:.0f}%)."

    return CheckResult(
        field="brand_name", verdict=verdict, expected=expected,
        observed=observed, reason=reason, citation=citation,
    )


# --- alcohol content -------------------------------------------------------

_ABV = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_PROOF = re.compile(r"(\d+(?:\.\d+)?)\s*proof", re.IGNORECASE)

# TOLERANCE IS BEVERAGE-CLASS DEPENDENT AND MUST BE CITED, NOT INVENTED.
# Distilled spirits, wine (27 CFR 4.36) and malt beverages each differ. Look up
# the governing section for the class in scope and set this per class before
# submission; 0.0 here means "label must state exactly what the application says".
ABV_TOLERANCE_PCT = 0.0


def parse_alcohol_statement(statement: str) -> tuple[float | None, float | None]:
    """Return (abv_pct, proof) from a verbatim statement like '45% Alc./Vol. (90 Proof)'."""
    abv = float(m.group(1)) if (m := _ABV.search(statement)) else None
    proof = float(m.group(1)) if (m := _PROOF.search(statement)) else None
    return abv, proof


def check_alcohol_content(expected_pct: float | None, statement: str | None) -> list[CheckResult]:
    citation = "27 CFR 5.65 (alcohol content)"
    results: list[CheckResult] = []

    if statement is None:
        results.append(CheckResult(
            field="alcohol_content", verdict=Verdict.FAIL,
            expected=f"{expected_pct}% Alc./Vol." if expected_pct is not None else None,
            reason="No alcohol content statement found on the label.", citation=citation,
        ))
        return results

    abv, proof = parse_alcohol_statement(statement)

    if abv is None:
        results.append(CheckResult(
            field="alcohol_content", verdict=Verdict.FLAG, observed=statement,
            expected=f"{expected_pct}% Alc./Vol." if expected_pct is not None else None,
            reason="Could not parse a percentage from the alcohol statement.", citation=citation,
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

_QTY = re.compile(r"(\d+(?:[.,]\d+)?)\s*(ml|millilitre|milliliter|l|liter|litre|cl|centilitre|centiliter)\b",
                  re.IGNORECASE)
_TO_ML = {"ml": 1.0, "millilitre": 1.0, "milliliter": 1.0,
          "cl": 10.0, "centilitre": 10.0, "centiliter": 10.0,
          "l": 1000.0, "liter": 1000.0, "litre": 1000.0}


def parse_net_contents_ml(text: str) -> float | None:
    """'750 mL' == '750ml' == '75 cl' == '0.75 L'."""
    m = _QTY.search(text)
    if not m:
        return None
    return float(m.group(1).replace(",", ".")) * _TO_ML[m.group(2).lower()]


def check_net_contents(expected: str | None, observed: str | None) -> CheckResult:
    citation = "27 CFR 5.70 (net contents)"
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
        )
    if abs(exp_ml - obs_ml) < 0.5:
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


def check_class_type(expected: str | None, observed: str | None) -> CheckResult:
    """The class/type designation, e.g. "Kentucky Straight Bourbon Whiskey".

    Stricter than a brand name, because the designation is regulated vocabulary
    rather than a mark: "Straight Bourbon" and "Blended Bourbon" are different
    products, not spelling variants. Case and spacing are still forgiven.
    """
    citation = "27 CFR 5.63 (class and type)"
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
    citation = "27 CFR 5.66 (name and address)"
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
    citation = "27 CFR 5.69 (country of origin)"

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
            citation=citation,
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
