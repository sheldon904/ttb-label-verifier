"""OCR noise on a compliant warning must refer, never reject.

Found by running the fixture set on a different Tesseract build (5.4 on
Windows) from the one the thresholds were tuned on: the compressed-JPEG
fixture came back with a stray glyph and two punctuation substitutions, and
the rule engine rejected a compliant label. These pin the behaviour.
"""

from app.models import Verdict
from app.rules.warning import STATUTORY_WARNING, check_warning_text, letters

# What Tesseract 5.4 actually read from fixtures/labels/photo_compressed.png.
TESSERACT_54_READ = (
    "GOVERNMENT WARNING: (1) According to the� Surgeon General, women should not "
    "drink alcoholic beverages during pregnancy because of the risk of birth "
    "defects: (2) Consumption of alcoholic beverages impairs your ability to "
    "drive a car or operate. machinery, and may cause health problems."
)


def test_letters_strips_everything_a_camera_can_change():
    assert letters("Defects: (2) the� operate.") == ["defects", "2", "the", "operate"]


def test_real_compressed_photo_read_flags_not_fails():
    r = check_warning_text(TESSERACT_54_READ)
    assert r.verdict is Verdict.FLAG
    assert "punctuation or a stray character" in r.reason


def test_period_read_as_colon_flags():
    r = check_warning_text(STATUTORY_WARNING.replace("defects.", "defects:"))
    assert r.verdict is Verdict.FLAG


def test_stray_glyph_flags():
    r = check_warning_text(STATUTORY_WARNING.replace("the Surgeon", "the| Surgeon"))
    assert r.verdict is Verdict.FLAG


def test_a_changed_word_still_fails_through_the_noise():
    text = TESSERACT_54_READ.replace("should not drink", "may wish to avoid")
    assert check_warning_text(text).verdict is Verdict.FAIL


def test_missing_numbering_is_noise_not_wording():
    """"(1)" read as "1)" is the camera, not the applicant."""
    r = check_warning_text(STATUTORY_WARNING.replace("(1)", "1)"))
    assert r.verdict is Verdict.FLAG


def test_noise_does_not_excuse_a_title_case_prefix():
    text = TESSERACT_54_READ.replace("GOVERNMENT WARNING:", "Government Warning:")
    assert check_warning_text(text).verdict is Verdict.FAIL
