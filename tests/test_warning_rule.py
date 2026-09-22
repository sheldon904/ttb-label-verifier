"""The warning rule against what 27 CFR 16.21 and 16.22 actually regulate.

16.21 fixes the wording. 16.22(a)(2) fixes the case and weight of the two prefix
words only. Everything else a transcription can vary -- body case, wrapping,
hyphenation, what follows the statement -- must not become a rejection.
"""

from app.models import Verdict
from app.rules.warning import (
    STATUTORY_BODY,
    STATUTORY_WARNING,
    check_warning_text,
    check_warning_typography,
    minimum_type_mm,
    normalize_whitespace,
    split_prefix,
)

PREFIX = "GOVERNMENT WARNING:"


def test_statutory_text_is_the_published_text():
    """Pinned against 27 CFR 16.21 as published. If this fails, the regulation
    changed or someone edited the constant; either way, stop and check."""
    assert STATUTORY_WARNING == (
        "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not "
        "drink alcoholic beverages during pregnancy because of the risk of birth "
        "defects. (2) Consumption of alcoholic beverages impairs your ability to "
        "drive a car or operate machinery, and may cause health problems."
    )


# --- the body's case is not regulated ---------------------------------------

def test_body_in_capitals_passes():
    caps = PREFIX + " " + STATUTORY_BODY.upper()
    r = check_warning_text(caps)
    assert r.verdict is Verdict.PASS
    assert "16.22" in r.reason


def test_body_in_title_case_passes():
    r = check_warning_text(PREFIX + " " + STATUTORY_BODY.title())
    assert r.verdict is Verdict.PASS


def test_prefix_in_title_case_still_fails():
    r = check_warning_text(STATUTORY_WARNING.replace(PREFIX, "Government Warning:"))
    assert r.verdict is Verdict.FAIL
    assert "capital" in r.reason.lower()
    assert r.citation == "27 CFR 16.22(a)(2)"


def test_prefix_in_lower_case_fails():
    r = check_warning_text(STATUTORY_WARNING.replace(PREFIX, "government warning:"))
    assert r.verdict is Verdict.FAIL


def test_title_case_prefix_with_a_dropped_word_still_fails():
    """A real prefix defect is not excused by an imperfect read of the body."""
    text = STATUTORY_WARNING.replace(PREFIX, "Government Warning:").replace(" a car", "")
    assert check_warning_text(text).verdict is Verdict.FAIL


# --- wrapping -----------------------------------------------------------------

def test_hyphenated_line_break_is_a_wrap_not_a_word():
    wrapped = STATUTORY_WARNING.replace("pregnancy", "preg-\nnancy")
    assert normalize_whitespace(wrapped) == STATUTORY_WARNING
    assert check_warning_text(wrapped).verdict is Verdict.PASS


def test_hyphen_inside_a_genuine_word_is_untouched():
    assert normalize_whitespace("well-being") == "well-being"


def test_detached_colon_is_reattached():
    prefix, body = split_prefix("GOVERNMENT WARNING : (1) According")
    assert prefix == PREFIX
    assert body == "(1) According"


# --- what follows the statement ------------------------------------------

def test_trailing_text_after_an_exact_statement_flags_not_fails():
    r = check_warning_text(STATUTORY_WARNING + " www.oldtomdistillery.com")
    assert r.verdict is Verdict.FLAG
    assert "www.oldtomdistillery.com" in r.reason
    assert r.citation == "27 CFR 16.21"


def test_trailing_text_after_a_reworded_statement_still_fails():
    text = STATUTORY_WARNING.replace("should not drink", "may wish to avoid") + " Enjoy!"
    assert check_warning_text(text).verdict is Verdict.FAIL


# --- dropouts are compared case-insensitively ------------------------------

def test_dropout_in_a_capitalised_body_flags():
    caps = PREFIX + " " + STATUTORY_BODY.upper().replace(" A CAR", "")
    r = check_warning_text(caps)
    assert r.verdict is Verdict.FLAG
    assert "missing" in r.reason


# --- 16.22(b) type size, stated from the container volume ------------------

def test_minimum_type_size_bands():
    assert minimum_type_mm(50) == 1
    assert minimum_type_mm(237) == 1
    assert minimum_type_mm(750) == 2
    assert minimum_type_mm(3000) == 2
    assert minimum_type_mm(4500) == 3
    assert minimum_type_mm(None) is None


def test_typography_states_the_applicable_minimum():
    r = check_warning_typography(True, container_ml=750)
    assert r.verdict is Verdict.PASS and r.advisory
    assert "2 mm" in r.reason
    assert "750 mL" in r.reason


def test_typography_without_a_container_size_says_so():
    r = check_warning_typography(None)
    assert r.verdict is Verdict.FLAG
    assert "cannot be verified" in r.reason
