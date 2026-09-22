"""The safety properties that justify using OCR for a regulatory decision.

Tesseract fails by not reading text, not by inventing it. Every rule here
exists to keep that failure mode from being reported as a violation: a false
rejection tells an applicant they broke the law, while a false flag costs an
agent a minute.
"""

from app.models import ApplicationRecord, CheckResult, LabelExtraction, Verdict
from app.rules.engine import review, soften_unreliable_failures
from app.rules.warning import STATUTORY_WARNING, check_warning_text


def _record(**kw):
    base = {"cola_id": "T-1", "brand_name": "Old Tom Distillery",
                "alcohol_content_pct": 45.0, "net_contents": "750 mL"}
    return ApplicationRecord(**(base | kw))


def _extraction(**kw):
    base = {"brand_name": "OLD TOM DISTILLERY", "alcohol_statement": "45% Alc./Vol. (90 Proof)",
                "net_contents": "750 mL", "warning_text": STATUTORY_WARNING,
                "warning_prefix_is_bold": True, "warning_legibility": "read"}
    return LabelExtraction(**(base | kw))


# --- an unreadable warning is never a violation ---------------------------

def test_illegible_warning_flags_rather_than_fails():
    r = check_warning_text(None, legibility="illegible")
    assert r.verdict is Verdict.FLAG
    assert "could not be read" in r.reason


def test_genuinely_absent_warning_still_fails():
    r = check_warning_text(None, legibility="absent")
    assert r.verdict is Verdict.FAIL


def test_partially_legible_warning_flags():
    r = check_warning_text(STATUTORY_WARNING, legibility="illegible")
    assert r.verdict is Verdict.FLAG


# --- dropped words are a read failure, altered words are a violation ------

def test_dropped_word_flags_as_a_transcription_dropout():
    """Tesseract lost 'beverages' on a compressed JPEG of a compliant label."""
    dropped = STATUTORY_WARNING.replace("alcoholic beverages during pregnancy",
                                        "alcoholic during pregnancy")
    r = check_warning_text(dropped)
    assert r.verdict is Verdict.FLAG
    assert "imperfect read" in r.reason


def test_substituted_wording_still_fails():
    """A softened warning is a substitution, not a dropout."""
    reworded = STATUTORY_WARNING.replace("should not drink", "may wish to avoid")
    assert check_warning_text(reworded).verdict is Verdict.FAIL


def test_title_case_prefix_still_fails():
    """Jenny's rejection must survive the dropout carve-out."""
    r = check_warning_text(STATUTORY_WARNING.replace("GOVERNMENT WARNING:", "Government Warning:"))
    assert r.verdict is Verdict.FAIL


def test_wholesale_garbage_still_fails():
    assert check_warning_text("GOVERNMENT WARNING: Acoondng bb th Genind shou").verdict is Verdict.FAIL


# --- low confidence cannot reject -----------------------------------------

def test_low_confidence_failure_is_softened_to_flag():
    checks = [CheckResult(field="brand_name", verdict=Verdict.FAIL, reason="Does not match.")]
    out = soften_unreliable_failures(checks, {"brand_name": 20.0})
    assert out[0].verdict is Verdict.FLAG
    assert "low confidence" in out[0].reason


def test_high_confidence_failure_is_left_alone():
    checks = [CheckResult(field="brand_name", verdict=Verdict.FAIL, reason="Does not match.")]
    assert soften_unreliable_failures(checks, {"brand_name": 95.0})[0].verdict is Verdict.FAIL


def test_absent_field_has_no_confidence_entry_and_still_fails():
    """Regression: an absent field reported 0.0 confidence, which softened a
    genuine missing-net-contents finding into a flag."""
    r = review(_record(), _extraction(net_contents=None))
    assert r.verdict is Verdict.FAIL


def test_degraded_image_cannot_reject_anything():
    """When the brand did not survive the photograph, nothing on it is trusted."""
    r = review(
        _record(),
        _extraction(brand_name=None, alcohol_statement="90% Alc./Vol. (100 Proof)",
                    field_confidence={"brand_name": 0.0, "alcohol_content": 0.0,
                                      "proof_consistency": 0.0, "net_contents": 0.0}),
    )
    assert r.verdict is Verdict.FLAG
