"""Layout heuristics, exercised directly with synthetic word boxes.

The evaluation harness only sees the fixture set, and every fixture puts the
warning last on the label. Real artwork does not. These pin the behaviour of
the block extractor on layouts the fixtures never produce.
"""

from app.extract.layout import (
    Line,
    Word,
    build_lines,
    closes_statement,
    extract_warning,
    pick_alcohol_statement,
)
from app.models import Verdict
from app.rules.warning import STATUTORY_WARNING, check_warning_text

WARNING_LINES = [
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not",
    "drink alcoholic beverages during pregnancy because of the risk of birth defects.",
    "(2) Consumption of alcoholic beverages impairs your ability to drive a car",
    "or operate machinery, and may cause health problems.",
]


def line(text: str, top: int, height: int = 14, conf: float = 92.0) -> Line:
    words = [Word(t, 10 + i * 60, top, 50, height, conf, (0, 0, top))
             for i, t in enumerate(text.split())]
    return Line(words=words)


def label(*extra_after_warning: str) -> list[Line]:
    lines = [line("OLD TOM DISTILLERY", 0, 46),
             line("Kentucky Straight Bourbon Whiskey", 70, 24),
             line("45% Alc./Vol. (90 Proof)", 120, 26)]
    top = 300
    for text in WARNING_LINES:
        lines.append(line(text, top))
        top += 20
    for text in extra_after_warning:
        lines.append(line(text, top))
        top += 20
    return lines


def test_warning_block_stops_at_the_statutes_last_words():
    text, block = extract_warning(label("www.oldtomdistillery.com", "BOTTLED BY OLD TOM DISTILLING CO."))
    assert text == STATUTORY_WARNING
    assert len(block) == 4
    assert check_warning_text(text).verdict is Verdict.PASS


def test_warning_block_without_trailing_text_is_unchanged():
    text, block = extract_warning(label())
    assert text == STATUTORY_WARNING
    assert len(block) == 4


def test_closing_phrase_tolerates_one_misread_character():
    assert closes_statement("or operate machinery, and may cause health problerns.")
    assert closes_statement("HEALTH PROBLEMS")
    assert not closes_statement("drink alcoholic beverages during pregnancy")


def test_warning_block_still_ends_on_a_type_size_jump():
    lines = label()
    # A large line straight after the warning, with the closing words absent
    # from the block, must still terminate it.
    lines[-1] = line("or operate machinery, and may cause health", lines[-1].top)
    lines.append(line("ESTATE BOTTLED", lines[-1].top + 20, 40))
    text, block = extract_warning(lines)
    assert len(block) == 4
    assert "ESTATE" not in text


def test_build_lines_orders_by_position():
    words = [Word("b", 60, 0, 10, 10, 90, (0, 0, 1)), Word("a", 0, 0, 10, 10, 90, (0, 0, 1)),
             Word("second", 0, 30, 10, 10, 90, (0, 0, 2))]
    lines = build_lines(words)
    assert [ln.text for ln in lines] == ["a b", "second"]


def test_alcohol_statement_spelled_out_is_found():
    lines = [line("BRAND", 0, 46), line("Alcohol 45 percent by volume", 100)]
    assert pick_alcohol_statement(lines, set()) == "Alcohol 45 percent by volume"
