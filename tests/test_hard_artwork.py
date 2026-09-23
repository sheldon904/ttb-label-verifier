"""What AI-generated artwork, a fuzz of degraded photographs and an adversarial
review found, one test per finding.

Each of these was a false rejection, a pass that should have been referred,
or a message that misled, before its fix.
"""

import asyncio
import io
import os
import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageFilter

from app.extract.layout import (
    Line,
    Word,
    extract_warning,
    looks_like_warning,
    pick_alcohol_statement,
    pick_bottler,
    pick_bottler_statement,
    pick_brand_and_class,
)
from app.models import ApplicationRecord, LabelExtraction, Verdict
from app.records import parse_records
from app.rules.engine import review
from app.rules.fields import (
    check_alcohol_content,
    check_bottler,
    check_brand_name,
    check_class_type,
    check_country_of_origin,
    check_net_contents,
    parse_net_contents_ml,
)
from app.rules.warning import STATUTORY_WARNING as W
from app.rules.warning import check_warning_text

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _tesseract_available() -> bool:
    return bool(shutil.which("tesseract")
                or os.path.isfile(r"C:\Program Files\Tesseract-OCR\tesseract.exe"))


needs_tesseract = pytest.mark.skipif(not _tesseract_available(), reason="Tesseract is not installed")


@pytest.fixture
def api():
    """A client on a chosen extractor, with no model call and no network."""
    from dataclasses import replace

    from fastapi.testclient import TestClient

    from app import main
    from app.config import load_settings
    before = main.settings

    def make(extractor):
        main.settings = replace(load_settings(), extractor=extractor, second_opinion="off",
                                triage="heuristic")
        main._extractor = None
        main._assist = None
        return TestClient(main.app)

    yield make
    main.settings, main._extractor, main._assist = before, None, None


def _line(text, top, height=40, conf=95.0, key=None):
    key = key or (top, 1, 1)
    return Line(words=[Word(t, 100 + i * 90, top, 80, height, conf, key)
                       for i, t in enumerate(text.split())])


# --- the warning: a misread is referred, an alteration rejects -------------

@pytest.mark.parametrize("name,text", [
    ("a word a letter out", W.replace("risk of birth", "risk of bnth")),
    ("a border ornament read as a short word", W.replace("alcoholic beverages impairs",
                                                          "alcoholic ee beverages impairs")),
    ("a clause number misread", W.replace("(2)", "(0)")),
    ("words run together", W.replace("a car", "acar")),
    ("pieces of words under glare", W.replace("Surgeon General", "ral")
     .replace("defects. (2) Consumption", "defe iption")),
    ("a heading letter read small", W.replace("GOVERNMENT", "GOvERNMENT")),
    ("text after the statement", W + " pect"),
])
def test_what_a_misread_produces_is_referred(name, text):
    r = check_warning_text(text)
    assert r.verdict is Verdict.FLAG, name
    # Text after the statement is a question of layout (16.21, "separate and
    # apart"), not of reading, so no second reading is offered it.
    assert r.read_uncertain is (name != "text after the statement")


@pytest.mark.parametrize("name,text", [
    ("a word added", W.replace("of alcoholic beverages impairs",
                               "of alcoholic alcoholic beverages impairs")),
    ("a word swapped", W.replace("may cause", "can cause")),
    ("a short word swapped", W.replace("impairs your ability", "impairs the ability")),
    ("an adjective added", W.replace("operate machinery", "operate heavy machinery")),
    ("'not' dropped", W.replace("should not drink", "should drink")),
    ("a phrase cut out", W.replace("According to the Surgeon General, ", "")),
    ("the second clause cut", W.split(" (2)")[0]),
    ("the heading in title case", W.replace("GOVERNMENT WARNING:", "Government Warning:")),
])
def test_an_alteration_is_rejected(name, text):
    assert check_warning_text(text).verdict is Verdict.FAIL, name


def test_words_ocr_scored_low_are_marks_not_wording():
    """"Pax" read at 32% from a Scotch label's ornamental border."""
    text = W.replace("of alcoholic beverages impairs", "of alcoholic Pax beverages impairs")
    assert check_warning_text(text).verdict is Verdict.FAIL
    assert check_warning_text(text, unsure=["Pax"]).verdict is Verdict.FLAG


def test_nothing_missing_rejects_while_part_of_the_statement_went_unread():
    cut = W.replace("According to the Surgeon General, women should not drink", "")
    assert check_warning_text(cut).verdict is Verdict.FAIL
    assert check_warning_text(cut, unsure=["~"]).verdict is Verdict.FLAG


def test_an_ornament_before_the_heading_is_not_part_of_the_statement():
    lines = [_line("~ GOVERNMENT WARNING: (1) According to the Surgeon General,", 900),
             _line("women should not drink alcoholic beverages during pregnancy because of", 950),
             _line("the risk of birth defects. (2) Consumption of alcoholic beverages impairs", 1000),
             _line("your ability to drive a car or operate machinery, and may cause health problems.", 1050)]
    text, _ = extract_warning(lines)
    assert text.startswith("GOVERNMENT WARNING:")
    assert check_warning_text(text).verdict is Verdict.PASS


# --- brand, class, bottler and country: the same words, or a person looks ----

def test_a_brand_one_letter_different_is_referred_however_long():
    r = check_brand_name("Buffalo Trace Distillery", "BUFFALO GRACE DISTILLERY")
    assert r.verdict is Verdict.FLAG
    assert "case/punctuation" not in r.reason


def test_a_brand_passes_on_case_punctuation_and_spacing():
    assert check_brand_name("Stone's Throw", "STONES THROW").verdict is Verdict.PASS


@pytest.mark.parametrize("label", ["STILLERY", "OLD TOM"])
def test_part_of_the_brand_is_referred(label):
    r = check_brand_name("Old Tom Distillery", label)
    assert r.verdict is Verdict.FLAG and r.read_uncertain


def test_the_brand_and_more_is_referred():
    assert check_brand_name("Old Tom", "OLD TOM RESERVE").verdict is Verdict.FLAG


def test_a_designation_needs_the_same_words():
    assert check_class_type("California Red Wine", "California Rose Wine").verdict is Verdict.FLAG
    assert check_class_type("Straight Bourbon Whiskey",
                            "Blended Bourbon Whiskey").verdict is Verdict.FAIL
    assert check_class_type("Kentucky Straight Bourbon Whiskey",
                            "entucky Straight").verdict is Verdict.FLAG


def _name(expected, observed):
    return next(c for c in check_bottler(expected, None, observed, None) if c.field == "bottler_name")


def test_a_bottler_is_told_apart_by_its_own_words():
    assert _name("ABC Distilling Company", "XYZ Distilling Company").verdict is Verdict.FAIL
    assert _name("Old Tom Distilling Co.",
                 "Distilled and Bottled by Old Tom Distilling Co.").verdict is Verdict.PASS
    assert _name("Old Tom Distilling Co.", "Distilling Co.").verdict is Verdict.FLAG


def test_the_address_read_as_the_name_means_the_name_went_unread():
    """Heavy JPEG and a 6 degree tilt left the name line unread, and the
    address under it was taken for the name: three compliant copies failed."""
    name = next(c for c in check_bottler("Old Tom Distilling Co.", "Bardstown, Kentucky",
                                         "Bardstown, Kentucky", None)
                if c.field == "bottler_name")
    assert name.verdict is Verdict.FLAG and name.read_uncertain
    wrong = next(c for c in check_bottler("Old Tom Distilling Co.", "Bardstown, Kentucky",
                                          "Kentucky Spirits Co.", "Bardstown, Kentucky")
                 if c.field == "bottler_name")
    assert wrong.verdict is Verdict.FAIL


def test_a_bottler_phrase_with_no_name_after_it_is_referred():
    """The statement was read and the name in it was not."""
    name = _name("Old Tom Distilling Co.", "istilled and Bottled by")
    assert name.verdict is Verdict.FLAG and name.read_uncertain


@pytest.mark.parametrize("expected,observed,verdict", [
    ("Product of Australia", "Product of Austria", Verdict.FLAG),
    ("Product of Ireland", "Product of Northern Ireland", Verdict.FAIL),
    ("Product of Scotland", "Product of Canada", Verdict.FAIL),
    ("Product of Scotland", "Product of Scotland", Verdict.PASS),
    ("USA", "Product of Mexico", Verdict.FLAG),
    ("Product of the United States", "Product of the United Stafes", Verdict.PASS),
])
def test_country_of_origin_needs_the_same_country(expected, observed, verdict):
    assert check_country_of_origin(expected, observed).verdict is verdict


# --- figures OCR gets wrong in ways the regulations rule out ---------------

def test_a_lost_decimal_point_is_referred():
    rows = check_alcohol_content(4.5, "45% ALC/VOL", "malt")
    assert rows[0].verdict is Verdict.FLAG and "decimal point" in rows[0].reason


def test_a_size_no_bottle_comes_in_is_a_misread():
    r = check_net_contents("750 mL", "790 mL", "spirits")
    assert r.verdict is Verdict.FLAG and "27 CFR 5.203" in r.reason
    # A real size that differs is a real difference.
    assert check_net_contents("750 mL", "700 mL", "spirits").verdict is Verdict.FAIL
    # Beer has no standards of fill.
    assert check_net_contents("12 fl oz", "16 fl oz", "malt").verdict is Verdict.FAIL


def test_us_measures_in_the_forms_part_7_prescribes():
    assert parse_net_contents_ml("1/2 GALLON") == pytest.approx(1892.7, abs=0.1)
    assert parse_net_contents_ml("1 QUART 1 PINT") == pytest.approx(1419.5, abs=0.1)
    assert parse_net_contents_ml("750 mL 25.4 FL OZ") == 750


# --- extraction on real artwork ---------------------------------------------

def test_a_one_line_bottler_statement_gives_name_and_address():
    lines = [_line("Imported by Harbor Imports, New York, New York", 800)]
    assert pick_bottler_statement(lines, set()) == ("Imported by Harbor Imports",
                                                     "New York, New York")


def test_a_statement_phrase_on_its_own_line_is_not_the_name():
    lines = [_line("Distilled and Bottled by", 800), _line("Old Tom Distilling Co.,", 850),
             _line("Bardstown, Kentucky", 900)]
    assert pick_bottler(lines, set()) == ("Distilled and Bottled by Old Tom Distilling Co.",
                                          "Bardstown, Kentucky")


def test_a_slogan_names_no_bottler():
    assert pick_bottler_statement([_line("Inspired by the sea", 800)], set()) == (None, None)


def test_a_fragment_of_the_warning_is_never_the_bottler():
    assert looks_like_warning("ale machinery, and may")
    lines = [_line("4.8% ALC/VOL", 600), _line("12 FL OZ", 650), _line("ale machinery, and may", 900)]
    assert pick_bottler(lines, set()) == (None, None)


def test_a_capitals_brand_does_not_absorb_a_mixed_case_varietal():
    lines = [_line("STONE'S THROW", 120, height=136), _line("Cabernet Sauvignon", 330, height=123),
             _line("Napa Valley", 490, height=110), _line("Alc. 13.5% by Vol.", 630, height=71),
             _line("750 ML", 740, height=72)]
    brand, klass, _ = pick_brand_and_class(lines, set(), page_height=1200)
    assert (brand, klass) == ("STONE'S THROW", "Cabernet Sauvignon")


def test_a_junk_line_is_never_the_brand():
    lines = [_line("Oe ee", 0, height=99, conf=35.0), _line("CHATEAU BELLE RIVE", 240, height=73),
             _line("Cabernet Sauvignon", 376, height=48)]
    brand, klass, _ = pick_brand_and_class(lines, set(), page_height=2200)
    assert (brand, klass) == ("CHATEAU BELLE RIVE", "Cabernet Sauvignon")


def test_an_alcohol_statement_without_its_figure_is_still_found():
    assert pick_alcohol_statement([_line("% Alc./Vol. (90 Proof)", 600)], set()) == \
        "% Alc./Vol. (90 Proof)"
    row = next(c for c in review(ApplicationRecord(cola_id="X", brand_name="A", alcohol_content_pct=45),
                                 LabelExtraction(brand_name="A",
                                                 alcohol_statement="% Alc./Vol. (90 Proof)")).checks
               if c.field == "alcohol_content")
    assert row.verdict is Verdict.FLAG


# --- the engine: what the image shows limits what it can prove -------------

RECORD = ApplicationRecord(cola_id="X", brand_name="Old Tom Distillery",
                           class_type="Kentucky Straight Bourbon Whiskey", alcohol_content_pct=45,
                           net_contents="750 mL", bottler_name="Old Tom Distilling Co.",
                           bottler_address="Bardstown, Kentucky")


def _rows(**extraction):
    base = {"brand_name": "OLD TOM DISTILLERY", "class_type": "Kentucky Straight Bourbon Whiskey",
            "alcohol_statement": "45% Alc./Vol. (90 Proof)", "net_contents": "750 mL",
            "bottler_name": "Old Tom Distilling Co.", "bottler_address": "Bardstown, Kentucky",
            "warning_text": W, "warning_prefix_is_bold": True}
    result = review(RECORD, LabelExtraction(**(base | extraction)))
    return result, {c.field: c for c in result.checks}


def test_a_missing_statement_beside_an_unread_line_is_referred():
    result, rows = _rows(net_contents=None, unread_text=["TL"])
    assert rows["net_contents"].verdict is Verdict.FLAG and "'TL'" in rows["net_contents"].reason
    assert result.verdict is Verdict.FLAG
    # With every line read, the same absence rejects.
    assert _rows(net_contents=None)[0].verdict is Verdict.FAIL


def test_several_statements_missing_at_once_are_referred():
    result, rows = _rows(net_contents=None, bottler_name=None, bottler_address=None,
                         warning_text=None, warning_prefix_is_bold=None)
    assert result.verdict is Verdict.FLAG
    assert "not read in full" in rows["government_warning"].reason


def test_a_photo_read_in_part_ranks_as_a_reading_problem():
    """The close-up compliant photo was triaged "likely a real problem with
    the label" because its missing address counted as a confident finding."""
    from app.assist.triage import HeuristicTriage
    result, rows = _rows(net_contents=None, bottler_name=None, bottler_address=None,
                         warning_text=None, warning_prefix_is_bold=None)
    assert rows["bottler_address"].read_uncertain
    triage = asyncio.run(HeuristicTriage().score(result))
    assert triage.probability <= 0.4


def test_nothing_read_from_an_out_of_focus_image_rejects():
    result, rows = _rows(brand_name="COPPER RIDGE", image_soft=True)
    assert rows["brand_name"].verdict is Verdict.FLAG and "out of focus" in rows["brand_name"].reason
    assert result.verdict is Verdict.FLAG


def test_the_designation_read_as_the_brand_means_the_brand_went_unread():
    """Scotch: "GLEN ARDEN" in outlined capitals was not read at all."""
    record = RECORD.model_copy(update={"brand_name": "Glen Arden",
                                       "class_type": "Single Malt Scotch Whisky"})
    result = review(record, LabelExtraction(brand_name="Single Malt Scotch Whisky",
                                            class_type="Aged 12 Years"))
    rows = {c.field: c for c in result.checks}
    assert rows["brand_name"].verdict is Verdict.FLAG and rows["brand_name"].read_uncertain
    assert rows["class_type"].verdict is Verdict.PASS


def test_a_brand_line_made_of_designation_words_is_the_designation_misread():
    """Tesseract 5.5 ran the outlined brand and the class line together as
    "ge Malt Whisky" at 84%: both rows are referred, neither rejects."""
    record = RECORD.model_copy(update={"brand_name": "Glen Arden",
                                       "class_type": "Single Malt Scotch Whisky"})
    result = review(record, LabelExtraction(brand_name="ge Malt Whisky", class_type="Aged 12 Years"))
    rows = {c.field: c.verdict for c in result.checks}
    assert rows["brand_name"] is Verdict.FLAG and rows["class_type"] is Verdict.FLAG
    # A brand of its own words is still compared as a brand.
    wrong = review(record, LabelExtraction(brand_name="COPPER RIDGE",
                                           class_type="Single Malt Scotch Whisky"))
    assert {c.field: c.verdict for c in wrong.checks}["brand_name"] is Verdict.FAIL


def test_a_designation_set_over_two_lines_is_read_whole():
    _, rows = _rows(class_type="Kentucky Straight", class_type_next="Bourbon Whiskey")
    assert rows["class_type"].verdict is Verdict.PASS


# --- the pipeline and the API -------------------------------------------------

def _png(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@needs_tesseract
def test_an_image_with_no_text_is_refused_and_never_rejected(api):
    r = api("ocr").post("/api/review?second_opinion=off",
                    data={"cola_id": "X", "brand_name": "Old Tom Distillery"},
                    files={"image": ("blank.png", _png(Image.new("RGB", (1200, 1600), "white")),
                                     "image/png")})
    assert r.status_code == 400
    assert r.json()["detail"].startswith("No text could be read from this image")


@needs_tesseract
def test_a_blurred_photo_of_a_compliant_label_is_never_rejected():
    from app.extract.ocr import OcrExtractor
    from app.pipeline import review_label
    truth = (FIXTURES / "labels" / "clean_01.png")
    blurred = _png(Image.open(truth).filter(ImageFilter.GaussianBlur(1.5)))
    bundle = asyncio.run(review_label(blurred, RECORD, OcrExtractor()))
    assert bundle.result.verdict is not Verdict.FAIL
    assert bundle.extraction.image_soft


def test_ocr_reads_luminance():
    """Colour let Tesseract threshold on its own and lose a warning strip."""
    from app.extract.imageprep import prepare_for_ocr
    raw = _png(Image.new("RGB", (800, 600), (249, 123, 28)))
    assert prepare_for_ocr(raw).image.mode == "L"


def test_a_tiff_comes_back_with_a_picture_the_browser_can_show(api):
    buf = io.BytesIO()
    Image.open(FIXTURES / "labels" / "clean_01.png").convert("RGB").save(buf, format="TIFF")
    r = api("stub").post("/api/review/example/clean_01")
    assert r.json()["preview"] is None
    from app.extract.imageprep import browser_preview
    assert browser_preview(buf.getvalue()).startswith("data:image/jpeg;base64,")


# --- records files ----------------------------------------------------------

def test_a_windows_excel_csv_keeps_its_accents():
    data = "cola_id,brand_name\n1,Château Margaux\n".encode("cp1252")
    assert parse_records(data, "x.csv").records[0].brand_name == "Château Margaux"


def test_numeric_ids_in_json_are_read():
    p = parse_records(b'[{"ttb_id": 24001, "brand": "Old Tom"}]', "x.json")
    assert p.records[0].cola_id == "24001"
