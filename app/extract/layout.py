"""Turning OCR word boxes into labelled fields.

This is the part a vision model would have done implicitly and the part a
classical pipeline has to earn. Tesseract returns words with positions,
heights and confidences; it does not know which of them is a brand name.

The heuristics below are deliberately typographic rather than semantic, because
that is what label artwork actually encodes: the brand is the biggest thing on
the label, the warning is a dense block of small type, and the alcohol and
volume statements are regex-shaped. Every rule here is inspectable and can be
quoted back to an agent asking why a field was read the way it was.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

WARNING_PREFIX_WORDS = ("GOVERNMENT", "WARNING")
# The statute's closing words. Once these have been read the statement is
# complete, and whatever small type follows it (a web address, a UPC caption,
# a bottler line) is a separate element that must not be transcribed into it.
WARNING_END_PHRASE = "HEALTH PROBLEMS"

_ABV_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|percent\b)", re.IGNORECASE)
_VOLUME_RE = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:[Ff][Ll]\.?\s*[Oo][Zz]|[Ff]luid\s+[Oo]unces?|ml|mL|ML|"
    r"millilitres?|milliliters?|cl|cL|CL|centilitres?|centiliters?|l|L|litres?|liters?)\b"
)
_COUNTRY_RE = re.compile(r"\b(?:product|produce)\s+of\b|\bimported\b", re.IGNORECASE)


@dataclass
class Word:
    text: str
    left: int
    top: int
    width: int
    height: int
    conf: float
    line_key: tuple[int, int, int]

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height


@dataclass
class Line:
    words: list[Word] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def top(self) -> int:
        return min(w.top for w in self.words)

    @property
    def bottom(self) -> int:
        return max(w.bottom for w in self.words)

    @property
    def height(self) -> float:
        """Median glyph height -- the proxy for point size."""
        hs = sorted(w.height for w in self.words)
        return hs[len(hs) // 2]

    @property
    def conf(self) -> float:
        return sum(w.conf for w in self.words) / len(self.words)


def build_lines(words: list[Word]) -> list[Line]:
    grouped: dict[tuple[int, int, int], Line] = {}
    for w in words:
        grouped.setdefault(w.line_key, Line()).words.append(w)
    lines = [ln for ln in grouped.values() if ln.words]
    for ln in lines:
        ln.words.sort(key=lambda w: w.left)
    lines.sort(key=lambda ln: (ln.top, ln.words[0].left))
    return lines


_BARE_NUMBER = re.compile(r"^\d+(?:[.,]\d+)?$")
_HAS_WORD = re.compile(r"[A-Za-z]{2,}")


def rescue_units(lines: list[Line], weak: list[Word]) -> None:
    """Re-attach a unit Tesseract read correctly but scored near zero.

    Found on the second fixture template: Georgia's "12 FL OZ" came back as
    "12" at 96% confidence and "FL", "OZ" at 0%, below the detection floor, so
    the unit was discarded and the label failed for a missing net contents
    statement. Only this shape is rescued -- a bare number whose low-scored
    neighbours on the same line spell a volume unit -- and the rescued words
    keep their scores, so the line's confidence drops and nothing read this
    way can reject.
    """
    for ln in lines:
        if not _BARE_NUMBER.match(ln.text.strip()):
            continue
        key, right = ln.words[0].line_key, ln.words[-1].right
        tail = sorted((w for w in weak if w.line_key == key and w.left >= right),
                      key=lambda w: w.left)[:3]
        if tail and _VOLUME_RE.search(ln.text + " " + " ".join(w.text for w in tail)):
            ln.words.extend(tail)


def find_warning_start(lines: list[Line]) -> int | None:
    """Locate the warning block by its prefix, tolerating OCR noise.

    Matched fuzzily on purpose: this only decides WHERE the warning is. Whether
    the text is compliant is decided later, exactly, by the rule engine.
    """
    for i, ln in enumerate(lines):
        upper = ln.text.upper()
        if all(w in upper for w in WARNING_PREFIX_WORDS):
            return i
        head = " ".join(upper.split()[:2])
        if head and fuzz.ratio(head, "GOVERNMENT WARNING") >= 82:
            return i
    return None


def extract_warning(lines: list[Line]) -> tuple[str | None, list[Line]]:
    """Return the warning text and the lines it occupies.

    The block runs from the prefix to the end of the contiguous run of
    similarly-sized small type -- which is how the statement is actually set.
    """
    start = find_warning_start(lines)
    if start is None:
        return None, []

    block = [lines[start]]
    base_height = lines[start].height
    if not closes_statement(lines[start].text):
        for ln in lines[start + 1:]:
            if ln.height > base_height * 1.8:
                break
            if ln.top - block[-1].bottom > base_height * 2.5:
                break
            block.append(ln)
            if closes_statement(ln.text):
                break

    return " ".join(ln.text for ln in block), block


def closes_statement(text: str) -> bool:
    """Does this line contain the statute's final words?

    Fuzzy on the tail of the line only, so one misread character in
    "problems" does not let the block run on into the next element.
    """
    upper = text.upper()
    if WARNING_END_PHRASE in upper:
        return True
    words = re.findall(r"[A-Z]+", upper)
    if len(words) < 2:
        return False
    return fuzz.ratio(" ".join(words[-2:]), WARNING_END_PHRASE) >= 85


def pick_brand_and_class(
    lines: list[Line], exclude: set[int]
) -> tuple[str | None, str | None, float]:
    """The brand is the largest type on the label; the class/type follows it.

    Restricted to the upper half because a bottler's name can be set large on
    some artwork, and the statutory ordering puts brand first.
    """
    if not lines:
        return None, None, 0.0
    page_bottom = max(ln.bottom for ln in lines)
    # A line that parses as an alcohol or volume statement is never the brand.
    # Without this guard, glare that washes out the brand promotes "50% Alc./Vol.
    # (100 Proof)" -- the next-largest line -- into the brand field, which then
    # fails against the application and rejects a compliant label.
    candidates = [
        (i, ln) for i, ln in enumerate(lines)
        if i not in exclude and ln.top < page_bottom * 0.55 and ln.text.strip()
        and not _ABV_RE.search(ln.text) and not _VOLUME_RE.search(ln.text)
    ]
    if not candidates:
        return None, None, 0.0

    brand_idx, brand_line = max(candidates, key=lambda pair: pair[1].height)
    brand_lines = brand_block(lines, brand_idx, exclude)
    last_brand = max(lines.index(ln) for ln in brand_lines)

    after = [
        (i, ln) for i, ln in candidates
        if i > last_brand and ln.height < brand_line.height * 0.92
        and not _ABV_RE.search(ln.text) and not _VOLUME_RE.search(ln.text)
    ]
    class_type = after[0][1].text if after else None

    # Dominance: how much larger the brand is than the label's body copy.
    #
    # Every label sets its brand as the most prominent element, so a page where
    # nothing stands out means the brand was not read -- typically because glare
    # or blowout erased it, at which point the next-largest line (a bottler name,
    # say) gets promoted into the brand field and confidently mismatches the
    # application. Measured on the fixture set: labels whose brand was read score
    # 1.75-1.85, the glare-damaged one scores 1.39.
    body = [ln.height for i, ln in enumerate(lines) if i not in exclude]
    median_height = sorted(body)[len(body) // 2] if body else 0
    dominance = (brand_line.height / median_height) if median_height else 0.0

    brand = " ".join(ln.text.strip() for ln in brand_lines).strip()
    return (brand or None,
            (class_type.strip() if class_type else None),
            dominance)


def brand_block(lines: list[Line], idx: int, exclude: set[int]) -> list[Line]:
    """The brand line plus any line directly above or below it in the same type.

    A long brand set large wraps: "COPPER RIDGE" over "RESERVE". Taking only
    the tallest line read the brand as "COPPER RIDGE" and failed a compliant
    label against "Copper Ridge Reserve". Found on the second fixture template,
    where the verdict happened to be right for another reason, which is why
    the evaluation now also checks that no row fails unless it was meant to.
    """
    anchor = lines[idx]
    block = [anchor]

    def same_type(ln: Line) -> bool:
        return abs(ln.height - anchor.height) <= anchor.height * 0.12 and bool(ln.text.strip())

    j = idx - 1
    while j >= 0 and j not in exclude and same_type(lines[j]) \
            and block[0].top - lines[j].bottom <= anchor.height * 1.2:
        block.insert(0, lines[j])
        j -= 1
    j = idx + 1
    while j < len(lines) and j not in exclude and same_type(lines[j]) \
            and lines[j].top - block[-1].bottom <= anchor.height * 1.2:
        block.append(lines[j])
        j += 1
    return block


def first_match(lines: list[Line], pattern: re.Pattern, exclude: set[int]) -> str | None:
    for i, ln in enumerate(lines):
        if i in exclude:
            continue
        if pattern.search(ln.text):
            return ln.text.strip()
    return None


def pick_alcohol_statement(lines: list[Line], exclude: set[int]) -> str | None:
    """Return the whole statement line so '(90 Proof)' survives for the
    internal-consistency check."""
    return first_match(lines, _ABV_RE, exclude)


def pick_net_contents(lines: list[Line], exclude: set[int]) -> str | None:
    for i, ln in enumerate(lines):
        if i in exclude:
            continue
        m = _VOLUME_RE.search(ln.text)
        # Skip a volume that is really part of the alcohol statement line.
        if m and not _ABV_RE.search(ln.text):
            return m.group(0).strip()
    # A number standing alone where the statements are is a quantity whose
    # unit was not read. Reporting it makes the check say "could not read the
    # volume" (a referral) rather than "there is no net contents statement"
    # (a rejection).
    for i, ln in enumerate(lines):
        if i not in exclude and _BARE_NUMBER.match(ln.text.strip()):
            return ln.text.strip()
    return None


def pick_country(lines: list[Line], exclude: set[int]) -> str | None:
    return first_match(lines, _COUNTRY_RE, exclude)


def pick_bottler(
    lines: list[Line], exclude: set[int], warning_start: int | None = None
) -> tuple[str | None, str | None]:
    """Bottler name and address.

    Anchored positionally rather than by taking the last lines of the page. The
    bottler block sits below the alcohol and volume statements and above the
    warning, which is where labels actually put it.

    Taking the tail instead was wrong in two ways found on the fixture set: when
    the warning block could not be detected (a blurred photo) the tail was
    warning text, and when extra lines appeared the pair shifted and the address
    was read as the name. Both produced confident failures against a compliant
    label.
    """
    statement_end = -1
    for i, ln in enumerate(lines):
        if i in exclude:
            continue
        if _ABV_RE.search(ln.text) or _VOLUME_RE.search(ln.text):
            statement_end = i

    upper_bound = warning_start if warning_start is not None else len(lines)

    block = [
        ln for i, ln in enumerate(lines)
        if statement_end < i < upper_bound and i not in exclude and ln.text.strip()
        and not _ABV_RE.search(ln.text) and not _VOLUME_RE.search(ln.text)
        and not _COUNTRY_RE.search(ln.text)
        # A name has letters. A bare number here is a quantity OCR half-read.
        and _HAS_WORD.search(ln.text)
    ]
    if not block:
        return None, None
    if len(block) == 1:
        return block[0].text.strip(), None
    return block[0].text.strip(), block[1].text.strip()
