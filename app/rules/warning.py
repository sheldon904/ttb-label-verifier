"""Government health warning statement -- 27 CFR 16.21 / 16.22.

Jenny Park: "It has to be exact. Like, word-for-word, and the 'GOVERNMENT
WARNING:' part has to be in all caps and bold."

This is the one field with a byte-exact policy. Everything else is fuzzy.
"""

from __future__ import annotations

import difflib
import re

from app.models import CheckResult, Verdict

# 27 CFR 16.21. VERIFY VERBATIM AGAINST eCFR BEFORE SUBMISSION -- do not trust a
# transcription of this constant from any model, including the one that wrote it.
STATUTORY_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not "
    "drink alcoholic beverages during pregnancy because of the risk of birth "
    "defects. (2) Consumption of alcoholic beverages impairs your ability to "
    "drive a car or operate machinery, and may cause health problems."
)

WARNING_PREFIX = "GOVERNMENT WARNING:"

_WS = re.compile(r"\s+")


def normalize_whitespace(text: str) -> str:
    """Collapse the only difference we forgive: line breaks and runs of spaces.

    Deliberately does NOT casefold or strip punctuation -- case is substantive
    here (title-case "Government Warning" is a real rejection reason) and so is
    the numbered-clause punctuation.
    """
    return _WS.sub(" ", text).strip()


def word_diff(expected: str, observed: str) -> list[str]:
    """Human-readable word-level diff, for showing the agent *what* deviated."""
    exp_words = expected.split()
    obs_words = observed.split()
    out: list[str] = []
    sm = difflib.SequenceMatcher(a=exp_words, b=obs_words, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace":
            out.append(f"expected {' '.join(exp_words[i1:i2])!r}, found {' '.join(obs_words[j1:j2])!r}")
        elif tag == "delete":
            out.append(f"missing {' '.join(exp_words[i1:i2])!r}")
        elif tag == "insert":
            out.append(f"unexpected {' '.join(obs_words[j1:j2])!r}")
    return out


def check_warning_text(observed: str | None) -> CheckResult:
    citation = "27 CFR 16.21"

    if not observed or not observed.strip():
        return CheckResult(
            field="government_warning",
            verdict=Verdict.FAIL,
            expected=STATUTORY_WARNING,
            observed=None,
            reason="No government warning statement found on the label.",
            citation=citation,
        )

    obs = normalize_whitespace(observed)

    if obs == STATUTORY_WARNING:
        return CheckResult(
            field="government_warning",
            verdict=Verdict.PASS,
            expected=STATUTORY_WARNING,
            observed=obs,
            reason="Matches the statutory text exactly.",
            citation=citation,
        )

    # Case-only deviation in the prefix is the specific failure Jenny described.
    if obs.casefold() == STATUTORY_WARNING.casefold():
        return CheckResult(
            field="government_warning",
            verdict=Verdict.FAIL,
            expected=STATUTORY_WARNING,
            observed=obs,
            reason=(
                "Wording is correct but capitalization deviates from the required "
                f"form. {WARNING_PREFIX!r} must appear in capital letters."
            ),
            citation=citation,
        )

    return CheckResult(
        field="government_warning",
        verdict=Verdict.FAIL,
        expected=STATUTORY_WARNING,
        observed=obs,
        reason="Warning text does not match the statutory wording: "
        + "; ".join(word_diff(STATUTORY_WARNING, obs)),
        citation=citation,
    )


def check_warning_typography(prefix_is_bold: bool | None) -> CheckResult:
    """Advisory only.

    27 CFR 16.22 sets minimum type size in millimetres and requires the statement
    be readily legible and separate from other information. A photograph gives us
    pixels, not millimetres -- without the container dimensions or image DPI we
    cannot verify type size, so this never hard-fails. It surfaces for agent
    review. See README > Limitations.
    """
    citation = "27 CFR 16.22"

    if prefix_is_bold is None:
        return CheckResult(
            field="warning_typography",
            verdict=Verdict.FLAG,
            reason="Could not determine whether the warning prefix is bold; agent review required.",
            citation=citation,
            advisory=True,
        )
    if prefix_is_bold:
        return CheckResult(
            field="warning_typography",
            verdict=Verdict.PASS,
            reason=f"{WARNING_PREFIX!r} appears in bold type.",
            citation=citation,
            advisory=True,
        )
    return CheckResult(
        field="warning_typography",
        verdict=Verdict.FLAG,
        reason=f"{WARNING_PREFIX!r} does not appear to be bold. Type size cannot be "
        "verified from an image alone; confirm against the physical container.",
        citation=citation,
        advisory=True,
    )
