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

_ABV_RE = re.compile(r"\d+(?:[.,]\d+)?\s*(?:%|percent\b)", re.IGNORECASE)
# Words that make a percentage an alcohol statement rather than, say,
# "100% Blue Agave" or a mash bill.
_ALCOHOL_WORD = re.compile(r"\b(?:alc|alcohol|vol|volume|proof|abv)\b", re.IGNORECASE)
# Only the statement's own abbreviations, which no other element prints.
_ALCOHOL_STATEMENT_WORDS = re.compile(r"\balc\b\.?\s*/?\s*\bvol\b|\bproof\b", re.IGNORECASE)
# Case-insensitive: labels print "1 LITER", "750 Milliliters", "70 Cl".
_VOLUME_RE = re.compile(
    r"(?:\d+\s*/\s*)?\d+(?:[.,]\d+)*\s*(?:fl\.?\s*oz|fluid\s+ounces?|pints?|quarts?|gallons?|"
    r"millilit(?:re|er)s?|ml|centilit(?:re|er)s?|cl|lit(?:re|er)s?|l)\b",
    re.IGNORECASE,
)
# "Imported by <importer>" names the importer, not the country, so it is not
# a country statement.
_COUNTRY_RE = re.compile(
    r"\b(?:product|produce)\s+of\b|\bimported\s+from\b|\bmade\s+in\b", re.IGNORECASE)
_PRODUCT_OF = re.compile(r"\b(?:product|produce)\s+of\b", re.IGNORECASE)


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


def _percent(match: re.Match) -> float:
    return float(re.sub(r"[^\d.]", "", match.group(0).replace(",", ".")) or 0)


def is_capitals(text: str) -> bool:
    """Set in capitals: at least 60% of its letters are upper case."""
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(c.isupper() for c in letters) / len(letters) >= 0.6


def is_alcohol_statement(text: str) -> bool:
    """A percentage that states alcohol content.

    "100% Blue Agave Tequila" is a class designation. Treating every
    percentage as a statement dropped it from the class candidates, so the
    importer's line was read as the class and the label was rejected. A
    percentage counts beside an alcohol word ("Alc", "Vol", "Proof"), or
    alone when it is under 100.
    """
    m = _ABV_RE.search(text)
    return bool(m) and (bool(_ALCOHOL_WORD.search(text)) or _percent(m) < 100)


_BARE_NUMBER = re.compile(r"^\d+(?:[.,]\d+)?$")
# A quantity with a short word after it that is not a unit OCR knows.
_NUMBER_AND_UNIT_LIKE = re.compile(r"^\d+(?:[.,]\d+)?\s*[A-Za-z.]{1,4}$")
_HAS_WORD = re.compile(r"[A-Za-z]{2,}")
_ALNUM = re.compile(r"[A-Za-z0-9]")

# Below this a line is not a reliable reading; the rules use the same floor.
UNREAD_CONFIDENCE = 80.0
# Below this a line is not text at all: an edge, an ornament, a shadow.
JUNK_CONFIDENCE = 50.0


# Words only the health warning prints. A line carrying one is part of the
# statement even when its "GOVERNMENT WARNING" prefix was not read.
_WARNING_ONLY_WORDS = re.compile(
    r"\b(?:surgeon|pregnancy|defects|consumption|alcoholic|beverages|impairs|machinery)\b",
    re.IGNORECASE)


def looks_like_warning(text: str) -> bool:
    """A fragment of the health warning. On a can photographed at an angle the
    prefix went unread, and "and may cause... machinery" was taken for the
    bottler's name and failed against the application."""
    return bool(_WARNING_ONLY_WORDS.search(text))


def looks_unread(line: Line) -> bool:
    """A line OCR detected but could not make sense of: read with low
    confidence, or hardly any letters in it ("TL" for "1 L", "7: iL")."""
    return line.conf < UNREAD_CONFIDENCE or len(_ALNUM.findall(line.text)) <= 3


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

    return " ".join([from_prefix(block[0])] + [ln.text for ln in block[1:]]), block


def from_prefix(line: Line) -> str:
    """The warning's first line from "GOVERNMENT" on.

    A border ornament read just before it ("~ GOVERNMENT WARNING:", on a dark
    vodka label) is not part of the statement, and left in, it made a
    compliant warning differ from the statute.
    """
    for k, w in enumerate(line.words):
        if fuzz.ratio(w.text.upper().strip(":;,."), "GOVERNMENT") >= 80:
            return " ".join(x.text for x in line.words[k:])
    return line.text


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
    lines: list[Line], exclude: set[int], page_height: int | None = None
) -> tuple[str | None, str | None, float]:
    """The brand is the largest type on the label; the class/type follows it.

    Restricted to the upper half because a bottler's name can be set large on
    some artwork, and the statutory ordering puts brand first. The half is of
    the image when its height is known. Measured from the lowest line read
    instead, a photograph whose lower half OCR could not read put the class
    line "below the middle" and lost it.
    """
    if not lines:
        return None, None, 0.0
    page_bottom = max([ln.bottom for ln in lines] + [page_height or 0])
    # A line that parses as an alcohol or volume statement is never the brand.
    # Without this guard, glare that washes out the brand promotes "50% Alc./Vol.
    # (100 Proof)" -- the next-largest line -- into the brand field, which then
    # fails against the application and rejects a compliant label.
    candidates = [
        (i, ln) for i, ln in enumerate(lines)
        if i not in exclude and ln.top < page_bottom * 0.55 and ln.text.strip()
        and not is_alcohol_statement(ln.text) and not _VOLUME_RE.search(ln.text)
        # "Alc./Vol. (80 Proof)" whose figure was lost, or run into another
        # line by OCR, is still the alcohol statement.
        and not _ALCOHOL_STATEMENT_WORDS.search(ln.text)
        # A photograph's background edge can read as tall "text" ("Oe ee" at
        # 35%); taken for the brand, it pushed every field down a line.
        and ln.conf >= JUNK_CONFIDENCE
    ]
    if not candidates:
        return None, None, 0.0

    brand_idx, brand_line = max(candidates, key=lambda pair: pair[1].height)
    brand_lines = brand_block(lines, brand_idx, exclude)
    last_brand = max(lines.index(ln) for ln in brand_lines)

    after = [
        (i, ln) for i, ln in candidates
        if i > last_brand and ln.height < brand_line.height * 0.92
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
    #
    # The brand's own lines are left out of the median. A wine label with six
    # lines, three of them large, counted its brand against itself and scored
    # 1.24, and the whole label was referred as unreadable.
    body = [ln.height for i, ln in enumerate(lines)
            if i not in exclude and ln not in brand_lines]
    median_height = sorted(body)[len(body) // 2] if body else 0
    dominance = (brand_line.height / median_height) if median_height else 0.0

    brand = " ".join(ln.text.strip() for ln in brand_lines).strip()
    return (brand or None,
            (class_type.strip() if class_type else None),
            dominance)


def pick_class_continuation(lines: list[Line], exclude: set[int],
                            page_height: int | None = None) -> str | None:
    """The line after the class/type, in case the class line is really the
    second line of a stacked brand ("OLD TOM" over a smaller "DISTILLERY"),
    or the class continues onto it ("Kentucky Straight" over "Bourbon Whiskey").

    Extraction only reports it. Which it is, if either, is decided by the
    rules, against the application.
    """
    if not lines:
        return None
    page_bottom = max([ln.bottom for ln in lines] + [page_height or 0])
    candidates = [
        (i, ln) for i, ln in enumerate(lines)
        if i not in exclude and ln.top < page_bottom * 0.55 and ln.text.strip()
        and not is_alcohol_statement(ln.text) and not _VOLUME_RE.search(ln.text)
        and not _ALCOHOL_STATEMENT_WORDS.search(ln.text)
        and ln.conf >= JUNK_CONFIDENCE
    ]
    if not candidates:
        return None
    brand_idx, brand_line = max(candidates, key=lambda pair: pair[1].height)
    last_brand = max(lines.index(ln) for ln in brand_block(lines, brand_idx, exclude))
    after = [ln for i, ln in candidates
             if i > last_brand and ln.height < brand_line.height * 0.92]
    return after[1].text.strip() if len(after) > 1 else None


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
    anchor_caps = is_capitals(anchor.text)

    # Same size and the same case. A capitals line and a mixed-case line of
    # similar height are different type: mixed case measures taller for its
    # ascenders and descenders. "STONE'S THROW" over "Cabernet Sauvignon" was
    # read as one brand.
    def same_type(ln: Line) -> bool:
        return (abs(ln.height - anchor.height) <= anchor.height * 0.12 and bool(ln.text.strip())
                and is_capitals(ln.text) == anchor_caps)

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
    internal-consistency check.

    A percentage beside an alcohol word ("Alc", "Vol", "Proof") is the
    statement. Only when no line has one does a bare percentage count, and
    never 100% or more: "100% Blue Agave Tequila" is a class designation, and
    reading it as the alcohol content rejected a compliant label.
    """
    candidates = [ln.text.strip() for i, ln in enumerate(lines)
                  if i not in exclude and _ABV_RE.search(ln.text)]
    for text in candidates:
        if _ALCOHOL_WORD.search(text):
            return text
    for text in candidates:
        if is_alcohol_statement(text):
            return text
    # "% Alc./Vol. (90 Proof)" with its number cut off by the edge of a
    # bottle: the statement is there, its figure unread. Reported, so the
    # rules refer it; not reported, it read as a label with no statement.
    for i, ln in enumerate(lines):
        if i not in exclude and _ALCOHOL_STATEMENT_WORDS.search(ln.text):
            return ln.text.strip()
    return None


def pick_net_contents(lines: list[Line], exclude: set[int]) -> str | None:
    """The net contents statement, from the first line that carries a volume.

    A volume on the same line as the alcohol statement ("750 mL 45% Alc./Vol.")
    is kept: dropping it reported a missing statement and rejected the label.
    A compound statement ("1 PINT 6 FL OZ", the 27 CFR 7.70 form) is returned
    whole, from its first quantity to its last.
    """
    for i, ln in enumerate(lines):
        if i in exclude:
            continue
        found = list(_VOLUME_RE.finditer(ln.text))
        if found:
            return ln.text[found[0].start():found[-1].end()].strip()
    # A number standing alone where the statements are is a quantity whose
    # unit was not read, or was misread ("750 mb" on a tilted photograph).
    # Reporting it makes the check say "could not read the volume" (a
    # referral) rather than "there is no net contents statement" (a rejection).
    for i, ln in enumerate(lines):
        if i not in exclude and (_BARE_NUMBER.match(ln.text.strip())
                                 or _NUMBER_AND_UNIT_LIKE.match(ln.text.strip())):
            return ln.text.strip()
    return None


def pick_country(lines: list[Line], exclude: set[int]) -> str | None:
    """"Product of" first; "Made in" or "Imported from" only if there is none."""
    return first_match(lines, _PRODUCT_OF, exclude) or first_match(lines, _COUNTRY_RE, exclude)


# The phrase that introduces the name and address (27 CFR 4.35, 5.66-5.68,
# 7.66-7.68): "Bottled by", "Imported by", "Distilled and Bottled by",
# "Brewed and Canned by", "Produced and Bottled by", "Made by".
# Only the verbs the regulations use: a slogan such as "Inspired by the sea"
# names no bottler.
_BOTTLER_VERB = (r"(?:bottled|distilled|blended|produced|imported|brewed|canned|packed|"
                 r"packaged|vinted|cellared|made|prepared|manufactured|fermented|rectified|kegged)")
_BY_PHRASE = re.compile(
    rf"\b{_BOTTLER_VERB}(?:\s*(?:,|and|&)\s*{_BOTTLER_VERB})*\s+by\b[\s:]*", re.IGNORECASE)


def split_name_address(text: str) -> tuple[str, str | None]:
    """"Old Tom Distilling Co., Bardstown, Kentucky" -> name, then address.

    The name runs to the first comma; the city and state follow it.
    """
    name, _, rest = text.partition(",")
    return name.strip(), (rest.strip(" ,") or None)


def pick_bottler_statement(lines: list[Line], exclude: set[int]) -> tuple[str | None, str | None]:
    """Name and address, read from the line that says who bottled or imported.

    Found on artwork from an image model: the statement is often one line
    ("Imported by Harbor Imports, New York, New York"), which left no address,
    or its phrase stands on a line of its own over the name, which was then
    read as the name itself and failed a compliant label. The name keeps its
    phrase, as printed; the rules compare what follows it.
    """
    for i, ln in enumerate(lines):
        if i in exclude or looks_like_warning(ln.text):
            continue
        m = _BY_PHRASE.search(ln.text)
        if not m:
            continue
        phrase, rest = ln.text[:m.end()].strip(), ln.text[m.end():].strip()
        following = [lines[j].text.strip() for j in range(i + 1, min(i + 3, len(lines)))
                     if j not in exclude and lines[j].text.strip()]
        if not rest and following:
            rest = following.pop(0)
        if not rest:
            return None, None
        name, address = split_name_address(rest)
        if address is None and following and "," in following[0]:
            address = following[0].strip(" ,")
        return f"{phrase} {name}".strip(), address
    return None, None


def pick_bottler(
    lines: list[Line], exclude: set[int], warning_start: int | None = None
) -> tuple[str | None, str | None]:
    """Bottler name and address.

    From the "…by" statement when there is one (see pick_bottler_statement).
    Otherwise anchored positionally rather than by taking the last lines of
    the page: the bottler block sits below the alcohol and volume statements
    and above the warning, which is where labels actually put it.

    Taking the tail instead was wrong in two ways found on the fixture set: when
    the warning block could not be detected (a blurred photo) the tail was
    warning text, and when extra lines appeared the pair shifted and the address
    was read as the name. Both produced confident failures against a compliant
    label.
    """
    name, address = pick_bottler_statement(lines, exclude)
    if name:
        return name, address

    statement_end = -1
    for i, ln in enumerate(lines):
        if i in exclude:
            continue
        if is_alcohol_statement(ln.text) or _VOLUME_RE.search(ln.text):
            statement_end = i

    upper_bound = warning_start if warning_start is not None else len(lines)

    block = [
        ln for i, ln in enumerate(lines)
        if statement_end < i < upper_bound and i not in exclude and ln.text.strip()
        and not _ABV_RE.search(ln.text) and not _VOLUME_RE.search(ln.text)
        and not _COUNTRY_RE.search(ln.text)
        # A name has letters. A bare number here is a quantity OCR half-read,
        # and a fragment ("led" of "Bottled by") is a line it could not read.
        and _HAS_WORD.search(ln.text) and not looks_unread(ln)
        and not looks_like_warning(ln.text)
    ]
    if not block:
        return None, None
    if len(block) == 1:
        return block[0].text.strip(), None
    return block[0].text.strip(), block[1].text.strip()
