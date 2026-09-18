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


DROPOUT_SIMILARITY_FLOOR = 0.93


def _is_dropout_only(expected: str, observed: str) -> bool:
    """True when the observed text differs from the statute only by omission.

    Deletions are consistent with an imperfect read; replacements and insertions
    are not -- a title-case prefix or a softened phrase both show up as
    replacements, and those stay hard failures.
    """
    exp_words, obs_words = expected.split(), observed.split()
    sm = difflib.SequenceMatcher(a=exp_words, b=obs_words, autojunk=False)
    if sm.ratio() < DROPOUT_SIMILARITY_FLOOR:
        return False
    return all(tag in ("equal", "delete") for tag, *_ in sm.get_opcodes())


def check_warning_text(observed: str | None, legibility: str = "read") -> CheckResult:
    """Compare the transcribed warning against the statute.

    The `legibility` argument is the safety valve for an OCR pipeline. Tesseract
    fails by not reading text, not by inventing it, and those two outcomes must
    never collapse into the same verdict: a rejection says an applicant broke the
    law, whereas an unreadable photograph says only that we need a better image.
    """
    citation = "27 CFR 16.21"

    if legibility == "illegible" and not observed:
        return CheckResult(
            field="government_warning",
            verdict=Verdict.FLAG,
            expected=STATUTORY_WARNING,
            observed=None,
            reason=(
                "Small print was detected where the warning should be, but it could not "
                "be read reliably. Review the artwork directly or request a clearer image."
            ),
            citation=citation,
        )

    if not observed or not observed.strip():
        return CheckResult(
            field="government_warning",
            verdict=Verdict.FAIL,
            expected=STATUTORY_WARNING,
            observed=None,
            reason="No government warning statement found on the label.",
            citation=citation,
        )

    if legibility == "illegible":
        return CheckResult(
            field="government_warning",
            verdict=Verdict.FLAG,
            expected=STATUTORY_WARNING,
            observed=normalize_whitespace(observed),
            reason=(
                "The warning statement was only partially legible, so it cannot be "
                "compared to the statutory text with confidence. Agent review required."
            ),
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

    # Distinguish a transcription dropout from an altered statement.
    #
    # Tesseract's characteristic failure is losing a word, not inventing one. A
    # label that is missing words but substitutes none, and is otherwise a near
    # perfect match, is far more likely to have been read imperfectly than to
    # have been printed that way. Rejecting on that evidence would mean telling
    # an applicant they broke the law because of a JPEG artifact, so it goes to
    # a human instead. A genuine omission still gets caught -- by the reviewer.
    if _is_dropout_only(STATUTORY_WARNING, obs):
        return CheckResult(
            field="government_warning",
            verdict=Verdict.FLAG,
            expected=STATUTORY_WARNING,
            observed=obs,
            reason=(
                "The warning is nearly an exact match but words are missing from the "
                "transcription, which is consistent with an imperfect read rather than "
                "an altered statement: "
                + "; ".join(word_diff(STATUTORY_WARNING, obs))
                + ". Confirm against the artwork."
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
