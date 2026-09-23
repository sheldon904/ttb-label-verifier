"""Government health warning statement -- 27 CFR 16.21 / 16.22.

Jenny Park: "It has to be exact. Like, word-for-word, and the 'GOVERNMENT
WARNING:' part has to be in all caps and bold."

This is the one field with a byte-exact policy on wording. Three things are
forgiven, because rejecting on them would be rejecting on something the
statute never asked for, or on something the camera did:

  * letter case in the body of the statement. 27 CFR 16.22(a)(2) regulates the
    case and weight of the words "GOVERNMENT WARNING" only.
  * line wrapping, including a hyphen at a line break. The statute contains no
    hyphens, so any "word- word" in a transcription is a wrap, not wording.
  * differences a misread produces. They are referred to an agent, never
    rejected: see `deviations`.
"""

from __future__ import annotations

import difflib
import re

from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

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
_HYPHEN_BREAK = re.compile(r"(?<=\w)[-\u2010-\u2014]\s+(?=\w)")
_SOFT_HYPHEN = "\u00ad"
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
# Clause numbers OCR commonly misreads: "(1)" as "(l)", "(I)" or "(|)",
# "(2)" as "(Z)". Mapped back before wording is compared, so the label is
# referred as a read problem and never rejected as altered wording.
_CLAUSE_ONE = re.compile(r"\(\s*[lI|!i]\s*\)")
_CLAUSE_TWO = re.compile(r"\(\s*[zZ]\s*\)")
_PREFIX = re.compile(r"(government)\s+(warning)\s*(:?)\s*", re.IGNORECASE)


def normalize_whitespace(text: str) -> str:
    """Collapse the only differences we forgive: line breaks, runs of spaces
    and hyphenated wraps.

    Deliberately does NOT casefold or strip punctuation -- case is substantive
    in the prefix (title-case "Government Warning" is a real rejection reason)
    and so is the numbered-clause punctuation.
    """
    text = _HYPHEN_BREAK.sub("", text.replace(_SOFT_HYPHEN, ""))
    return _WS.sub(" ", text).strip()


def letters(text: str) -> list[str]:
    """The words of a statement with case, punctuation and stray glyphs removed.

    This is what "the same wording" means for comparison purposes: the
    sequence of alphanumeric tokens. Everything the camera can plausibly
    change is stripped; everything the applicant would have had to change is
    kept.
    """
    text = _CLAUSE_TWO.sub(" 2 ", _CLAUSE_ONE.sub(" 1 ", text))
    # Punctuation becomes a space, never nothing: "defects.(2)" and
    # "WARNING:(1)" are two words each, not one.
    return _NON_ALNUM.sub(" ", text.casefold()).split()


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


# The statute's own words. A token of one or two characters that is not one of
# them is a mark read as letters: "ee" from a border, "Da" from a speck, "0"
# from a smudged "2".
_STATUTE_WORDS = frozenset(letters(STATUTORY_WARNING))
# Words whose loss reverses what the statement says. "Women should drink
# alcoholic beverages during pregnancy" is not a misread to refer.
_MEANING_WORDS = frozenset({"not"})
# More words than this missing is a statement with something cut out of it.
MAX_MISREAD_WORDS_LOST = 4


def _stray(token: str) -> bool:
    # A lone digit counts even though "1" and "2" are the statute's own: under
    # heavy JPEG compression "(1)" came back as "(2)".
    return len(token) <= 2 and (token not in _STATUTE_WORDS or token.isdigit())


def _piece(found: str, gone: list[str]) -> bool:
    """Part of what went missing: "ral" of "General" under glare, "acar" for
    "a car" and "notdrin" for "not drink" where OCR ran words together, and
    "iption" for the end of "consumption", a piece with a letter misread."""
    joined = "".join(gone)
    return len(found) >= 2 and (found in joined
                                or (len(found) >= 3 and fuzz.partial_ratio(found, joined) >= 66))


def _near_miss(expected: str, found: str) -> bool:
    """'bnth' for 'birth', 'Accerding' for 'According': one or two letters out,
    on a word long enough for that to be a misread rather than another word."""
    return len(expected) >= 4 and Levenshtein.distance(expected, found) <= 2


def deviations(expected: str, observed: str,
               unsure: frozenset[str] = frozenset()) -> tuple[list[str], list[str]]:
    """The word-level differences, split into (alterations, misreads).

    A camera and OCR lose words, get a letter or two wrong and read marks as
    short tokens. Only artwork adds a real word, swaps one word for another or
    drops "not". A misread is referred to an agent with the differences listed;
    only an alteration rejects. A misprint that looks like a misread ("defect"
    for "defects") is referred, never passed: the agent sees the difference.

    `unsure` holds words OCR itself could not read with confidence: a border
    ornament read as "Pax", or glyphs it detected and could not resolve. A
    difference made of those alone is a misread, and while any exist, part of
    the statement went unread, so no number of missing words rejects: they
    may be in the part that could not be read. Text after the statute's last
    word is a separate element, which 16.21 asks an agent to look at, not a
    change of wording.
    """
    exp, obs = letters(expected), letters(observed)
    unsure_tokens = {t for word in unsure for t in letters(word)}
    partly_unread = bool(unsure)
    sm = difflib.SequenceMatcher(a=exp, b=obs, autojunk=False)
    altered: list[str] = []
    misread: list[str] = []
    lost = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        gone, found = exp[i1:i2], obs[j1:j2]
        text = (f"missing {' '.join(gone)!r}" if tag == "delete"
                else f"unexpected {' '.join(found)!r}" if tag == "insert"
                else f"expected {' '.join(gone)!r}, found {' '.join(found)!r}")
        meaning_lost = any(w in _MEANING_WORDS and not any(w in f for f in found) for w in gone)
        if meaning_lost and not partly_unread:
            altered.append(text)
        elif tag == "delete":
            lost += len(gone)
            misread.append(text)
        elif tag == "insert" and i1 == len(exp):
            misread.append(f"text after the statement: {' '.join(found)!r}")
        elif all(_stray(f) or f in unsure_tokens or _piece(f, gone)
                 or any(_near_miss(g, f) for g in gone) for f in found):
            # Pieces and near misses show the words were printed and read
            # badly. Only a stretch replaced by marks alone counts as lost.
            if all(_stray(f) or f in unsure_tokens for f in found):
                lost += len(gone)
            misread.append(text)
        else:
            altered.append(text)
    if lost > MAX_MISREAD_WORDS_LOST and not partly_unread:
        # Too much is missing for a misread: every difference counts.
        return altered + misread, []
    return altered, misread


def split_prefix(text: str) -> tuple[str | None, str]:
    """Separate the "GOVERNMENT WARNING:" prefix, as printed, from the body.

    Returns (prefix_as_printed, body). The prefix is recognised regardless of
    case so that its case can then be judged; a colon that OCR detached from
    the word is re-attached. Returns (None, text) when the statement does not
    open with the two prefix words at all.
    """
    m = _PREFIX.match(text)
    if not m:
        return None, text
    # "WARNING:(1)" with no space, and "WARNING :" with one, both split here.
    prefix = f"{m.group(1)} {m.group(2)}{m.group(3)}"
    return prefix, text[m.end():].strip()


def _result(verdict: Verdict, observed: str | None, reason: str,
            citation: str = "27 CFR 16.21", read_uncertain: bool = False) -> CheckResult:
    return CheckResult(
        field="government_warning", verdict=verdict, expected=STATUTORY_WARNING,
        observed=observed, reason=reason, citation=citation, layer="regulation",
        read_uncertain=read_uncertain,
    )


def check_warning_text(observed: str | None, legibility: str = "read",
                       unsure: list[str] | None = None) -> CheckResult:
    """Compare the transcribed warning against the statute.

    The `legibility` argument is the safety valve for an OCR pipeline. Tesseract
    fails by not reading text, not by inventing it, and those two outcomes must
    never collapse into the same verdict: a rejection says an applicant broke the
    law, whereas an unreadable photograph says only that we need a better image.
    `unsure` lists words OCR read with low confidence (see `deviations`).
    """
    if legibility == "illegible" and not observed:
        return _result(Verdict.FLAG, None, (
            "The warning statement could not be read from this image. Review the "
            "artwork directly or request a clearer image."
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
    # Compared from the prefix on when it was recognised, whole otherwise, so a
    # misread prefix ("WARNlNG") is judged as a word like any other.
    marks = frozenset(unsure or ())
    altered, misread = (deviations(STATUTORY_BODY, body, marks) if prefix is not None
                        else deviations(STATUTORY_WARNING, obs, marks))

    # The prefix is the one place where letter case is regulated. A title-case
    # or lower-case prefix over a correct body is the rejection Jenny described,
    # and it is a real defect on the artwork rather than a read error, so it
    # fails even when the body is only nearly complete.
    prefix_case_wrong = (prefix is not None and prefix != WARNING_PREFIX
                         and prefix.casefold() == WARNING_PREFIX.casefold())
    # "Government Warning" has 15 small letters. One or two are OCR: a V, O, S,
    # W, C or X differs from its capital only in size, and "GOvERNMENT" is a
    # misread of capitals, not a heading set in title case.
    case_misread = prefix_case_wrong and sum(c.islower() for c in prefix) <= 2
    if case_misread and not altered:
        return _result(Verdict.FLAG, obs, (
            f"The heading reads {prefix!r}. One or two letters of a capital heading are "
            "easily misread as small ones; confirm on the artwork that it is set in capitals."
        ), citation="27 CFR 16.22(a)(2)", read_uncertain=True)
    if prefix_case_wrong and not altered:
        return _result(Verdict.FAIL, obs, (
            f"Wording is correct but the label reads {prefix!r}. "
            f"{WARNING_PREFIX!r} must appear in capital letters."
        ), citation="27 CFR 16.22(a)(2)")

    if prefix == WARNING_PREFIX:
        if body == STATUTORY_BODY:
            return _result(Verdict.PASS, obs, "Matches the statutory text; only the spacing differs.")
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
        # That is not wrong wording -- but 16.21 requires the statement to
        # be separate and apart from all other information, so an agent looks.
        if body_words[:len(statute_words)] == statute_words:
            trailing = " ".join(body.split()[len(STATUTORY_BODY.split()):])
            return _result(Verdict.FLAG, obs, (
                "The statutory text is present and exact, but additional text was read "
                f"immediately after it: {trailing!r}. 27 CFR 16.21 requires the "
                "statement to appear separate and apart from all other information; "
                "confirm on the artwork that this is a separate element."
            ))

    # Rejecting on a misread would tell an applicant they broke the law because
    # of a JPEG artifact, so a statement that differs only the way a misread
    # does goes to a human with the differences listed. An alteration rejects.
    if not altered:
        found = misread or word_diff(STATUTORY_WARNING, obs, ignore_case=True)
        return _result(Verdict.FLAG, obs, (
            "The warning differs from the statutory text only in ways a misread "
            "produces: " + "; ".join(found) + ". It may be misprinted or misread; "
            "confirm against the artwork."
        ), read_uncertain=True)

    if prefix_case_wrong:
        altered.append(f"the heading reads {prefix!r}, which must be in capital letters")
    return _result(Verdict.FAIL, obs, (
        "Warning text does not match the statutory wording: "
        + "; ".join(altered)
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
        f" A {container_ml:.0f} mL container requires the statement in type at least "
        f"{mm} mm high (27 CFR 16.22(b)); that cannot be measured from an image, so "
        "confirm against the physical container."
    )


def check_warning_typography(prefix_is_bold: bool | None,
                             container_ml: float | None = None,
                             small_type: bool = False) -> CheckResult:
    """Advisory only.

    27 CFR 16.22(a)(2) requires the prefix in bold capitals; 16.22(b) sets a
    minimum type size in millimetres by container volume. A photograph gives
    us pixels, not millimetres -- without the container dimensions or image DPI
    we cannot verify type size, so this never hard-fails. What an image CAN
    support is stated: the relative weight of the prefix, and the size minimum
    that applies to this container. The weight of the rest of the statement is
    not measured.
    """
    citation = "27 CFR 16.22(a)(2) and (b)"

    # Jenny: people "try to get creative with the warning... burying it in tiny
    # text". Type too small to measure is that concern, and it is about size,
    # so it is not marked read_uncertain: a second reading of the words, however
    # good, cannot clear it. Found when a vision model read 6-point type
    # perfectly and the label would otherwise have passed.
    if small_type:
        return CheckResult(
            field="warning_typography",
            verdict=Verdict.FLAG,
            reason=("The warning is set in very small type relative to the rest of the "
                    "label, too small to judge its weight or size from the image."
                    + _size_note(container_ml)),
            citation="27 CFR 16.22(b)",
            advisory=True,
            layer="regulation",
        )

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
