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
            field="alcohol_content", verdict=Verdict.FLAG, observed=statement,
            reason="Application record has no alcohol content to compare against.", citation=citation,
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
            field="net_contents", verdict=Verdict.FLAG, observed=observed,
            reason="Application record has no net contents to compare against.", citation=citation,
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
