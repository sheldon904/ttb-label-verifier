"""Government health warning statement -- 27 CFR 16.21 / 16.22.

Jenny Park: "It has to be exact. Like, word-for-word, and the 'GOVERNMENT
WARNING:' part has to be in all caps and bold."

This is the one field with a byte-exact policy on wording. Three things are
forgiven, because rejecting on them would be rejecting on something the
statute never asked for, or on something the camera did:

  * letter case in the body of the statement. 27 CFR 16.22(b) regulates the
    case and weight of the words "GOVERNMENT WARNING" only.
  * line wrapping, including a hyphen at a line break. The statute contains no
    hyphens, so any "word- word" in a transcription is a wrap, not wording.
  * punctuation and stray glyphs, when every word is right. A period read as a
    colon, or a compression artifact read as a character, is not a change of
    wording. It is referred to an agent, never rejected.
"""

from __future__ import annotations

import difflib
import re

from app.models import CheckResult, Verdict

# 27 CFR 16.21. Verified character-for-character against the published CFR
# text on 2026-09-21 (https://www.law.cornell.edu/cfr/text/27/16.21). If the
# regulation is amended this constant must change with it.
STATUTORY_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not "
    "drink alcoholic beverages during pregnancy because of the risk of birth "
    "defects. (2) Consumption of alcoholic beverages impairs your ability to "
    "drive a car or operate machinery, and may cause health problems."
)

WARNING_PREFIX = "GOVERNMENT WARNING:"
STATUTORY_BODY = STATUTORY_WARNING[len(WARNING_PREFIX):].strip()

_WS = re.compile(r"\s+")
# A hyphen followed by whitespace between two word characters is a line wrap.
_HYPHEN_BREAK = re.compile(r"(?<=\w)-\s+(?=\w)")
_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")


def normalize_whitespace(text: str) -> str:
    """Collapse the only differences we forgive: line breaks, runs of spaces
    and hyphenated wraps.

    Deliberately does NOT casefold or strip punctuation -- case is substantive
    in the prefix (title-case "Government Warning" is a real rejection reason)
    and so is the numbered-clause punctuation.
    """
    text = _HYPHEN_BREAK.sub("", text)
    return _WS.sub(" ", text).strip()


def letters(text: str) -> list[str]:
    """The words of a statement with case, punctuation and stray glyphs removed.

    This is what "the same wording" means for comparison purposes: the
    sequence of alphanumeric tokens. Everything the camera can plausibly
    change is stripped; everything the applicant would have had to change is
    kept.
    """
    return _NON_ALNUM.sub("", text.casefold()).split()


def word_diff(expected: str, observed: str, ignore_case: bool = False) -> list[str]:
    """Human-readable word-level diff, for showing the agent *what* deviated."""
    exp_words = expected.split()
    obs_words = observed.split()
    key = (lambda w: w.casefold()) if ignore_case else (lambda w: w)
    sm = difflib.SequenceMatcher(
        a=[key(w) for w in exp_words], b=[key(w) for w in obs_words], autojunk=False
    )
    out: list[str] = []
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
    """True when the observed wording differs from the statute only by omission.

    Deletions are consistent with an imperfect read; replacements and insertions
    are not -- a softened phrase shows up as a replacement, and stays a hard
    failure. Compared on letters only: case, punctuation and stray glyphs are
    handled before this is reached, and the prefix's case is checked separately.
    """
    exp_words, obs_words = letters(expected), letters(observed)
    sm = difflib.SequenceMatcher(a=exp_words, b=obs_words, autojunk=False)
    if sm.ratio() < DROPOUT_SIMILARITY_FLOOR:
        return False
    return all(tag in ("equal", "delete") for tag, *_ in sm.get_opcodes())


def split_prefix(text: str) -> tuple[str | None, str]:
    """Separate the "GOVERNMENT WARNING:" prefix, as printed, from the body.

    Returns (prefix_as_printed, body). The prefix is recognised regardless of
    case so that its case can then be judged; a colon that OCR detached from
    the word is re-attached. Returns (None, text) when the statement does not
    open with the two prefix words at all.
    """
    parts = text.split(" ", 2)
    if len(parts) < 2:
        return None, text
    first, second = parts[0], parts[1]
    rest = parts[2] if len(parts) > 2 else ""
    if first.casefold() != "government" or second.casefold().rstrip(":") != "warning":
        return None, text
    prefix = f"{first} {second}"
    if not prefix.endswith(":") and rest.startswith(":"):
        prefix += ":"
        rest = rest[1:]
    return prefix, rest.strip()


def _result(verdict: Verdict, observed: str | None, reason: str,
            citation: str = "27 CFR 16.21", read_uncertain: bool = False) -> CheckResult:
    return CheckResult(
        field="government_warning", verdict=verdict, expected=STATUTORY_WARNING,
        observed=observed, reason=reason, citation=citation, layer="regulation",
        read_uncertain=read_uncertain,
    )


def check_warning_text(observed: str | None, legibility: str = "read") -> CheckResult:
    """Compare the transcribed warning against the statute.

    The `legibility` argument is the safety valve for an OCR pipeline. Tesseract
    fails by not reading text, not by inventing it, and those two outcomes must
    never collapse into the same verdict: a rejection says an applicant broke the
    law, whereas an unreadable photograph says only that we need a better image.
    """
    if legibility == "illegible" and not observed:
        return _result(Verdict.FLAG, None, (
            "Small print was detected where the warning should be, but it could not "
            "be read reliably. Review the artwork directly or request a clearer image."
        ), read_uncertain=True)

    if not observed or not observed.strip():
        return _result(Verdict.FAIL, None, "No government warning statement found on the label.")

    if legibility == "illegible":
        return _result(Verdict.FLAG, normalize_whitespace(observed), (
            "The warning statement was only partially legible, so it cannot be "
            "compared to the statutory text with confidence. Agent review required."
        ), read_uncertain=True)

    obs = normalize_whitespace(observed)

    if obs == STATUTORY_WARNING:
        return _result(Verdict.PASS, obs, "Matches the statutory text exactly.")

    prefix, body = split_prefix(obs)
    body_words = letters(body)
    statute_words = letters(STATUTORY_BODY)
    body_same_wording = body_words == statute_words

    # The prefix is the one place where letter case is regulated. A title-case
    # or lower-case prefix over a correct body is the rejection Jenny described,
    # and it is a real defect on the artwork rather than a read error, so it
    # fails even when the body is only nearly complete.
    prefix_case_wrong = (prefix is not None and prefix != WARNING_PREFIX
                         and prefix.casefold() == WARNING_PREFIX.casefold())
    if prefix_case_wrong and (body_same_wording or _is_dropout_only(STATUTORY_BODY, body)):
        return _result(Verdict.FAIL, obs, (
            f"Wording is correct but the label reads {prefix!r}. "
            f"{WARNING_PREFIX!r} must appear in capital letters."
        ), citation="27 CFR 16.22(b)")

    if prefix == WARNING_PREFIX:
        if body.casefold() == STATUTORY_BODY.casefold():
            return _result(Verdict.PASS, obs, (
                "Matches the statutory text. The body differs only in letter case, "
                "which 27 CFR 16.22 does not regulate."
            ))

        # Every word is right; only punctuation or a stray character differs.
        # That is what a JPEG artifact or a speck on the label looks like to
        # OCR, and it is not evidence of altered wording. An agent confirms.
        if body_same_wording:
            return _result(Verdict.FLAG, obs, (
                "Every word of the statutory text is present in order; the transcription "
                "differs only in punctuation or a stray character, which is consistent "
                "with an imperfect read: "
                + "; ".join(word_diff(STATUTORY_WARNING, obs, ignore_case=True))
                + ". Confirm against the artwork."
            ), read_uncertain=True)

        # The full statute is present, and then something else follows it.
        # That is not wrong wording -- but 16.22(a) requires the statement to
        # be separate and apart from all other information, so an agent looks.
        if body_words[:len(statute_words)] == statute_words:
            trailing = " ".join(body.split()[len(STATUTORY_BODY.split()):])
            return _result(Verdict.FLAG, obs, (
                "The statutory text is present and exact, but additional text was read "
                f"immediately after it: {trailing!r}. 27 CFR 16.22(a) requires the "
                "statement to appear separate and apart from other information; confirm "
                "on the artwork that this is a separate element."
            ), citation="27 CFR 16.22(a)")

    # Distinguish a transcription dropout from an altered statement.
    #
    # Tesseract's characteristic failure is losing a word, not inventing one. A
    # label that is missing words but substitutes none, and is otherwise a near
    # perfect match, is far more likely to have been read imperfectly than to
    # have been printed that way. Rejecting on that evidence would mean telling
    # an applicant they broke the law because of a JPEG artifact, so it goes to
    # a human instead. A genuine omission still gets caught -- by the reviewer.
    if _is_dropout_only(STATUTORY_WARNING, obs):
        return _result(Verdict.FLAG, obs, (
            "The warning is nearly an exact match but words are missing from the "
            "transcription, which is consistent with an imperfect read rather than "
            "an altered statement: "
            + "; ".join(word_diff(STATUTORY_WARNING, obs, ignore_case=True))
            + ". Confirm against the artwork."
        ), read_uncertain=True)

    return _result(Verdict.FAIL, obs, (
        "Warning text does not match the statutory wording: "
        + "; ".join(word_diff(STATUTORY_WARNING, obs))
    ))


def minimum_type_mm(container_ml: float | None) -> int | None:
    """27 CFR 16.22(b): minimum type size for the statement, by container volume."""
    if container_ml is None:
        return None
    if container_ml <= 237:
        return 1
    if container_ml <= 3000:
        return 2
    return 3


def _size_note(container_ml: float | None) -> str:
    mm = minimum_type_mm(container_ml)
    if mm is None:
        return " Type size cannot be verified from an image alone."
    return (
        f" A {container_ml:g} mL container requires the statement in type at least "
        f"{mm} mm high (27 CFR 16.22(b)); that cannot be measured from an image, so "
        "confirm against the physical container."
    )


def check_warning_typography(prefix_is_bold: bool | None,
                             container_ml: float | None = None) -> CheckResult:
    """Advisory only.

    27 CFR 16.22 requires the prefix in bold, the remainder not in bold, and a
    minimum type size in millimetres that depends on container volume. A
    photograph gives us pixels, not millimetres -- without the container
    dimensions or image DPI we cannot verify type size, so this never
    hard-fails. What an image CAN support is stated: the relative weight of the
    prefix, and the size minimum that applies to this container.
    """
    citation = "27 CFR 16.22"

    if prefix_is_bold is None:
        return CheckResult(
            field="warning_typography",
            verdict=Verdict.FLAG,
            reason="Could not determine whether the warning prefix is bold; agent review required."
                   + _size_note(container_ml),
            citation=citation,
            advisory=True,
            read_uncertain=True,
            layer="regulation",
        )
    if prefix_is_bold:
        return CheckResult(
            field="warning_typography",
            verdict=Verdict.PASS,
            reason=f"{WARNING_PREFIX!r} appears in bold type." + _size_note(container_ml),
            citation=citation,
            advisory=True,
            layer="regulation",
        )
    return CheckResult(
        field="warning_typography",
        verdict=Verdict.FLAG,
        reason=f"{WARNING_PREFIX!r} does not appear to be bold." + _size_note(container_ml),
        citation=citation,
        advisory=True,
    )
