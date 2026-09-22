"""Inputs the fixture set never produces, each one a defect found by probing.

Every case here once gave a wrong answer on a compliant label or crashed on a
legal upload: a phone photo at full resolution, a 16-bit scan, a label printed
light on dark, a brand set on two lines, a European decimal comma, a pint
statement. Most were false rejections, the outcome the tool exists to avoid.
"""

import io

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.extract.imageprep import (
    MAX_IMAGE_PIXELS,
    MAX_OCR_EDGE,
    UnreadableImageError,
    prepare_for_ocr,
)
from app.extract.layout import (
    Line,
    Word,
    pick_alcohol_statement,
    pick_bottler,
    pick_brand_and_class,
    pick_country,
    pick_net_contents,
)
from app.models import ApplicationRecord, LabelExtraction, Verdict
from app.rules.engine import review
from app.rules.fields import (
    check_alcohol_content,
    check_alcohol_format,
    check_brand_name,
    check_class_type,
    check_net_contents,
    parse_alcohol_statement,
    parse_net_contents_ml,
)
from app.rules.warning import STATUTORY_WARNING, check_warning_text

LABEL = "fixtures/labels/clean_01.png"


def _encoded(img: Image.Image, fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def _row(checks, field):
    return next(c for c in checks if c.field == field)


# --- image preparation -------------------------------------------------------

def test_a_full_resolution_photo_is_reduced_to_the_working_size():
    """Tesseract misread "45%" as "495%" on a 12 MP photo and read it right
    at 2200 px, so every image is brought to that size first."""
    p = prepare_for_ocr(_encoded(Image.new("RGB", (4000, 3000), "white"), "JPEG"))
    assert max(p.working_size) == MAX_OCR_EDGE
    assert p.original_size == (4000, 3000)


def test_evidence_boxes_are_placed_on_the_image_as_uploaded():
    """Boxes are normalised by the working size, so a box at the centre of
    the reduced image is at the centre of the original."""
    p = prepare_for_ocr(_encoded(Image.new("RGB", (4400, 2200), "white")))
    cx, cy = p.final_size[0] / 2, p.final_size[1] / 2
    quad = p.to_display_quad(cx - 5, cy - 5, cx + 5, cy + 5)
    xs, ys = [pt[0] for pt in quad], [pt[1] for pt in quad]
    assert sum(xs) / 4 == pytest.approx(0.5, abs=0.01)
    assert sum(ys) / 4 == pytest.approx(0.5, abs=0.01)


def test_an_image_over_the_pixel_limit_is_refused_before_it_is_decoded():
    side = int(MAX_IMAGE_PIXELS ** 0.5) + 200
    raw = _encoded(Image.new("1", (side, side), 1))
    with pytest.raises(UnreadableImageError, match="megapixels"):
        prepare_for_ocr(raw)


def test_a_16_bit_scan_keeps_its_picture():
    """Converting 16-bit straight to 8-bit clipped every pixel to white."""
    arr = np.full((400, 600), 50_000, dtype=np.uint16)
    arr[150:250, 100:500] = 2_000
    p = prepare_for_ocr(_encoded(Image.fromarray(arr)))
    gray = np.asarray(p.image.convert("L"))
    assert gray.min() < 60 and gray.max() > 200


def test_light_type_on_a_dark_label_is_inverted_for_ocr():
    img = Image.new("RGB", (800, 600), (20, 20, 30))
    ImageDraw.Draw(img).rectangle((100, 250, 700, 300), fill=(240, 240, 240))
    p = prepare_for_ocr(_encoded(img))
    assert p.inverted
    assert np.median(np.asarray(p.image.convert("L"))) > 200


def test_a_light_label_is_not_inverted():
    assert not prepare_for_ocr(_encoded(Image.open(LABEL))).inverted


def test_a_truncated_file_is_a_readable_error():
    raw = _encoded(Image.open(LABEL).convert("RGB"), "JPEG")
    with pytest.raises(UnreadableImageError, match="could not be read"):
        prepare_for_ocr(raw[: len(raw) // 3])


def test_a_blank_image_is_not_rotated():
    """A blank page scored the same at every angle and was turned 12 degrees."""
    assert prepare_for_ocr(_encoded(Image.new("RGB", (800, 600), "white"))).deskew_deg == 0


# --- reading the layout ------------------------------------------------------

def _lines(*texts: str) -> list[Line]:
    return [Line(words=[Word(t, 10 + j * 60, i * 40, 50, 20, 92.0, (0, 0, i))
                        for j, t in enumerate(text.split())])
            for i, text in enumerate(texts)]


@pytest.mark.parametrize("text", ["750 ML", "1 LITER", "70 Cl", "750 Milliliters",
                                  "1.75 LITRES", "1 PINT 6 FL OZ", "1,000 mL"])
def test_net_contents_is_found_in_any_case_and_unit(text):
    assert pick_net_contents(_lines("OLD TOM", text), set()) == text


def test_a_volume_on_the_alcohol_line_is_kept():
    assert pick_net_contents(_lines("750 mL 45% Alc./Vol."), set()) == "750 mL"


def test_the_alcohol_statement_is_not_100_percent_agave():
    lines = _lines("100% Blue Agave Tequila", "40% Alc./Vol. (80 Proof)")
    assert pick_alcohol_statement(lines, set()) == "40% Alc./Vol. (80 Proof)"


def test_a_bare_100_percent_is_never_the_alcohol_statement():
    assert pick_alcohol_statement(_lines("100% Blue Agave Tequila"), set()) is None


def test_a_100_percent_class_line_is_the_class_not_a_statement():
    """Skipping it made the importer's line the class and the address the
    bottler, which rejected a compliant import."""
    lines = _lines("CASA LUNA", "100% Blue Agave Tequila", "40% Alc./Vol. (80 Proof)",
                   "750 mL", "Imported by Harbor Imports", "New York, New York",
                   "Product of Mexico")
    for w in lines[0].words:
        w.height = 60
    brand, klass, _ = pick_brand_and_class(lines, set())
    assert (brand, klass) == ("CASA LUNA", "100% Blue Agave Tequila")
    assert pick_bottler(lines, set()) == ("Imported by Harbor Imports", "New York, New York")


def test_a_decimal_comma_percentage_is_the_statement():
    assert pick_alcohol_statement(_lines("40,5% vol"), set()) == "40,5% vol"


def test_an_importer_line_is_not_the_country_statement():
    lines = _lines("Imported by Harbor Wines, New York, NY", "Product of France")
    assert pick_country(lines, set()) == "Product of France"


def test_imported_from_counts_when_there_is_no_product_of_line():
    assert pick_country(_lines("Imported from Mexico"), set()) == "Imported from Mexico"


# --- brand and class ---------------------------------------------------------

RECORD = ApplicationRecord(cola_id="T-1", brand_name="Old Tom Distillery",
                           class_type="Kentucky Straight Bourbon Whiskey")


def test_a_brand_set_on_two_lines_is_read_whole():
    extraction = LabelExtraction(brand_name="OLD TOM", class_type="DISTILLERY",
                                 class_type_next="Kentucky Straight Bourbon Whiskey")
    checks = review(RECORD, extraction).checks
    assert _row(checks, "brand_name").verdict is Verdict.PASS
    assert "two lines" in _row(checks, "brand_name").reason
    assert _row(checks, "class_type").verdict is Verdict.PASS


def test_a_two_line_join_is_not_used_when_the_first_line_already_matches():
    extraction = LabelExtraction(brand_name="OLD TOM DISTILLERY", class_type="Gin")
    checks = review(RECORD, extraction).checks
    assert _row(checks, "brand_name").verdict is Verdict.PASS
    assert _row(checks, "class_type").observed == "Gin"


def test_part_of_the_brand_is_referred_not_rejected():
    r = check_brand_name("Old Tom Distillery", "OLD TOM")
    assert r.verdict is Verdict.FLAG and r.read_uncertain


def test_a_different_brand_that_shares_a_word_still_fails():
    assert check_brand_name("Old Tom Distillery", "OLD HARBOR").verdict is Verdict.FAIL


def test_a_class_line_that_is_part_of_the_brand_is_referred():
    r = check_class_type("Kentucky Straight Bourbon Whiskey", "DISTILLERY", "Old Tom Distillery")
    assert r.verdict is Verdict.FLAG and r.read_uncertain


@pytest.mark.parametrize("expected, observed", [("Dry Gin", "Gin"), ("Tequila", "Tequila Blanco")])
def test_one_designation_containing_the_other_is_referred(expected, observed):
    r = check_class_type(expected, observed)
    assert r.verdict is Verdict.FLAG and not r.read_uncertain


def test_a_different_class_still_fails():
    assert check_class_type("Straight Bourbon Whiskey", "Vodka").verdict is Verdict.FAIL


# --- alcohol content ---------------------------------------------------------

def test_a_percentage_the_proof_contradicts_is_a_misread_not_a_rejection():
    checks = check_alcohol_content(45.0, "495% Alc./Vol. (90 Proof)")
    assert all(c.verdict is not Verdict.FAIL for c in checks)
    assert _row(checks, "alcohol_content").read_uncertain
    assert _row(checks, "proof_consistency").read_uncertain


def test_an_impossible_percentage_is_a_misread():
    checks = check_alcohol_content(40.0, "400% Alc./Vol.")
    assert _row(checks, "alcohol_content").verdict is Verdict.FLAG
    assert _row(checks, "alcohol_content").read_uncertain


def test_a_wrong_percentage_with_a_matching_proof_still_fails():
    """The label's own proof agrees with its percentage, and both disagree
    with the application: a real mismatch, not a misread."""
    checks = check_alcohol_content(45.0, "40% Alc./Vol. (80 Proof)")
    assert _row(checks, "alcohol_content").verdict is Verdict.FAIL


def test_a_decimal_comma_is_read_as_a_decimal():
    assert parse_alcohol_statement("40,5% vol") == (40.5, None)
    assert _row(check_alcohol_content(40.5, "40,5% vol"), "alcohol_content").verdict is Verdict.PASS


def test_val_is_read_as_vol_in_the_advisory_format_check():
    assert check_alcohol_format("45% Alc./Val.").verdict is Verdict.PASS


# --- net contents ------------------------------------------------------------

@pytest.mark.parametrize("text, ml", [
    ("1,000 mL", 1000.0),
    ("1,75 L", 1750.0),
    ("1 PINT", 473.176),
    ("1 PINT 6 FL OZ", 473.176 + 6 * 29.5735),
    ("1 QUART", 946.353),
    ("750 MILLILITERS", 750.0),
])
def test_net_contents_units(text, ml):
    assert parse_net_contents_ml(text) == pytest.approx(ml, abs=0.01)


def test_a_fluid_ounce_statement_rounded_to_a_tenth_matches():
    """250 mL is printed "8.4 FL OZ", 1.6 mL short."""
    assert check_net_contents("250 mL", "8.4 FL OZ").verdict is Verdict.PASS


def test_metric_statements_stay_exact():
    assert check_net_contents("750 mL", "748 mL").verdict is Verdict.FAIL


def test_a_different_fluid_ounce_container_still_fails():
    assert check_net_contents("12 FL OZ", "16 FL OZ").verdict is Verdict.FAIL


# --- the warning -------------------------------------------------------------

def test_clause_numbers_glued_to_punctuation_are_not_a_wording_change():
    glued = STATUTORY_WARNING.replace("WARNING: (1) ", "WARNING:(1)").replace(
        "defects. (2) ", "defects.(2)")
    assert check_warning_text(glued).verdict is not Verdict.FAIL


@pytest.mark.parametrize("misread", [("(1)", "(l)"), ("(1)", "(I)"), ("(2)", "(Z)")])
def test_misread_clause_numbers_are_referred(misread):
    r = check_warning_text(STATUTORY_WARNING.replace(*misread))
    assert r.verdict is Verdict.FLAG and r.read_uncertain


@pytest.mark.parametrize("dash", ["-", "‐", "–", "—"])
def test_a_word_wrapped_with_any_dash_is_rejoined(dash):
    wrapped = STATUTORY_WARNING.replace("pregnancy", f"preg{dash}\nnancy")
    assert check_warning_text(wrapped).verdict is Verdict.PASS


def test_a_soft_hyphen_is_ignored():
    assert check_warning_text(STATUTORY_WARNING.replace("machinery", "machin­ery")).verdict \
        is Verdict.PASS
