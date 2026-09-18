"""The three required label elements beyond brand, alcohol and net contents.

The brief lists seven mandatory elements. These cover the class/type
designation, the bottler name and address, and country of origin.
"""

from app.models import ApplicationRecord, LabelExtraction, Verdict
from app.rules.engine import review
from app.rules.fields import (
    check_bottler,
    check_class_type,
    check_country_of_origin,
    is_import,
)
from app.rules.warning import STATUTORY_WARNING


# --- class / type -----------------------------------------------------------

def test_class_type_case_difference_passes():
    assert check_class_type("Kentucky Straight Bourbon Whiskey",
                            "KENTUCKY STRAIGHT BOURBON WHISKEY").verdict is Verdict.PASS


def test_different_product_class_fails():
    """'Straight' and 'Blended' are different products, not spelling variants."""
    assert check_class_type("Straight Bourbon Whiskey",
                            "Canadian Blended Whisky").verdict is Verdict.FAIL


def test_missing_class_type_fails():
    assert check_class_type("Straight Rye Whiskey", None).verdict is Verdict.FAIL


def test_no_class_type_on_the_application_is_advisory_only():
    """A gap in the submitted record is not a finding about the label, so it
    stays visible on the checklist without changing the verdict."""
    r = check_class_type(None, "Straight Rye Whiskey")
    assert r.verdict is Verdict.PASS and r.advisory
    assert "not verified" in r.reason


# --- bottler ----------------------------------------------------------------

def _by_field(results, name):
    """Select by field rather than position: check_bottler emits advisory rows
    for elements the application omitted, so ordering is not stable."""
    return next(r for r in results if r.field == name)


def test_bottler_name_match():
    r = check_bottler("Old Tom Distilling Co.", None, "Old Tom Distilling Co.", None)
    assert _by_field(r, "bottler_name").verdict is Verdict.PASS


def test_wrong_bottler_fails():
    r = check_bottler("Old Tom Distilling Co.", None, "Copper Ridge Distillers", None)
    assert _by_field(r, "bottler_name").verdict is Verdict.FAIL


def test_abbreviated_address_flags_rather_than_fails():
    """Address formatting varies between a form field and printed artwork; a
    rejection here would be for a difference with no regulatory meaning."""
    r = _by_field(check_bottler(None, "Bardstown, Kentucky", None, "Bardstown, KY"),
                  "bottler_address")
    assert r.verdict is not Verdict.FAIL


def test_missing_address_flags():
    r = _by_field(check_bottler(None, "Bardstown, Kentucky", None, None), "bottler_address")
    assert r.verdict is Verdict.FLAG


def test_absent_application_fields_do_not_change_the_verdict():
    """A record with no bottler details must not flag the label."""
    for row in check_bottler(None, None, "Someone Ltd", "Somewhere"):
        assert row.verdict is Verdict.PASS and row.advisory


# --- country of origin ------------------------------------------------------

def test_domestic_products_do_not_require_a_country_statement():
    """Demanding one on a Kentucky bourbon would reject a label for omitting
    something the regulation never asked for."""
    r = check_country_of_origin("Product of the United States", None)
    assert r.verdict is Verdict.PASS and r.advisory


def test_import_without_country_statement_fails():
    r = check_country_of_origin("Product of Scotland", None)
    assert r.verdict is Verdict.FAIL
    assert "imported" in r.reason


def test_import_with_matching_country_passes():
    assert check_country_of_origin("Product of Scotland",
                                   "Product of Scotland").verdict is Verdict.PASS


def test_import_with_wrong_country_fails():
    assert check_country_of_origin("Product of Scotland",
                                   "Product of Canada").verdict is Verdict.FAIL


def test_is_import_recognises_domestic_spellings():
    assert not is_import("Product of the United States")
    assert not is_import("USA")
    assert not is_import(None)
    assert is_import("Product of Scotland")


# --- all seven elements together --------------------------------------------

def test_every_required_element_is_checked():
    """Guards against a required element silently dropping out of the engine."""
    record = ApplicationRecord(
        cola_id="T-1", brand_name="Copper Ridge Reserve", class_type="Single Malt Whisky",
        alcohol_content_pct=43.0, net_contents="700 mL",
        bottler_name="Copper Ridge Distillers", bottler_address="Inverness, Scotland",
        country_of_origin="Product of Scotland",
    )
    extraction = LabelExtraction(
        brand_name="COPPER RIDGE RESERVE", class_type="Single Malt Whisky",
        alcohol_statement="43% Alc./Vol. (86 Proof)", net_contents="700 mL",
        bottler_name="Copper Ridge Distillers", bottler_address="Inverness, Scotland",
        country_of_origin="Product of Scotland", warning_text=STATUTORY_WARNING,
        warning_prefix_is_bold=True, warning_legibility="read",
    )
    result = review(record, extraction)
    fields = {c.field for c in result.checks}
    assert {"brand_name", "class_type", "alcohol_content", "net_contents",
            "bottler_name", "bottler_address", "country_of_origin",
            "government_warning", "warning_typography"} <= fields
    assert result.verdict is Verdict.PASS


def test_truncated_country_statement_flags_rather_than_fails():
    """Blur truncated "Product of Scotland" to "Product of". The country did not
    survive the read; that is not the same as a wrong country."""
    r = check_country_of_origin("Product of Scotland", "Product of")
    assert r.verdict is Verdict.FLAG
    assert "could not be read" in r.reason
