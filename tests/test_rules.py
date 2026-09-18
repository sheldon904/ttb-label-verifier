"""Rule-engine tests. No network, no API key, no images -- pure functions.

These encode the specific cases the stakeholders described in the brief.
"""

from app.models import ApplicationRecord, LabelExtraction, Verdict
from app.rules.engine import review
from app.rules.fields import (
    check_brand_name,
    check_net_contents,
    parse_alcohol_statement,
    parse_net_contents_ml,
)
from app.rules.warning import STATUTORY_WARNING, check_warning_text


# --- Dave Morrison: "obviously the same thing. You need judgment." ---------

def test_brand_case_difference_passes():
    r = check_brand_name("Stone's Throw", "STONE'S THROW")
    assert r.verdict is Verdict.PASS


def test_brand_genuinely_different_fails():
    assert check_brand_name("Stone's Throw", "Old Tom Distillery").verdict is Verdict.FAIL


def test_brand_near_miss_flags_for_human():
    assert check_brand_name("Old Tom Distillery", "Old Tim Distillery").verdict is Verdict.FLAG


# --- Jenny Park: "It has to be exact." ------------------------------------

def test_exact_warning_passes():
    assert check_warning_text(STATUTORY_WARNING).verdict is Verdict.PASS


def test_warning_tolerates_line_breaks_only():
    wrapped = STATUTORY_WARNING.replace(" (2)", "\n   (2)")
    assert check_warning_text(wrapped).verdict is Verdict.PASS


def test_title_case_prefix_fails():
    """The rejection Jenny caught last month."""
    r = check_warning_text(STATUTORY_WARNING.replace("GOVERNMENT WARNING:", "Government Warning:"))
    assert r.verdict is Verdict.FAIL
    assert "capital" in r.reason.lower()


def test_reworded_warning_fails_with_a_diff():
    r = check_warning_text(STATUTORY_WARNING.replace("should not drink", "may wish to avoid"))
    assert r.verdict is Verdict.FAIL
    assert "may wish to avoid" in r.reason


def test_missing_warning_fails():
    assert check_warning_text(None).verdict is Verdict.FAIL


# --- the sample label planted in the brief --------------------------------

def test_proof_parses_and_cross_checks():
    assert parse_alcohol_statement("45% Alc./Vol. (90 Proof)") == (45.0, 90.0)


def test_net_contents_unit_normalization():
    assert parse_net_contents_ml("750 mL") == parse_net_contents_ml("75 cl") == 750.0
    assert parse_net_contents_ml("0.75 L") == 750.0
    assert check_net_contents("750 mL", "75cl").verdict is Verdict.PASS


# --- end to end through the engine ----------------------------------------

def _record(**kw):
    base = dict(cola_id="TEST-1", brand_name="Old Tom Distillery",
                alcohol_content_pct=45.0, net_contents="750 mL")
    return ApplicationRecord(**(base | kw))


def _extraction(**kw):
    base = dict(brand_name="OLD TOM DISTILLERY", alcohol_statement="45% Alc./Vol. (90 Proof)",
                net_contents="750 mL", warning_text=STATUTORY_WARNING,
                warning_prefix_is_bold=True)
    return LabelExtraction(**(base | kw))


def test_clean_label_passes():
    assert review(_record(), _extraction()).verdict is Verdict.PASS


def test_abv_mismatch_fails():
    assert review(_record(), _extraction(alcohol_statement="40% Alc./Vol.")).verdict is Verdict.FAIL


def test_internally_inconsistent_proof_fails():
    r = review(_record(), _extraction(alcohol_statement="45% Alc./Vol. (80 Proof)"))
    assert r.verdict is Verdict.FAIL
    assert any(c.field == "proof_consistency" and c.verdict is Verdict.FAIL for c in r.checks)


def test_unknown_boldness_flags_but_never_fails():
    r = review(_record(), _extraction(warning_prefix_is_bold=None))
    assert r.verdict is Verdict.FLAG
