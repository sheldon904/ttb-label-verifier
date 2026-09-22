"""Citations by commodity, and the alcohol statement exceptions they bring.

Wine is labelled under 27 CFR part 4, distilled spirits under part 5 and malt
beverages under part 7. A reviewer from TTB reads the citation on every row,
so a beer label must not be cited to the spirits part.
"""

import pytest

from app.models import ApplicationRecord, LabelExtraction, Verdict
from app.rules.citations import citation, commodity_of
from app.rules.engine import review
from app.rules.fields import check_alcohol_content
from app.rules.warning import STATUTORY_WARNING


@pytest.mark.parametrize("designation, expected", [
    ("Kentucky Straight Bourbon Whiskey", "spirits"),
    ("Single Malt Whisky", "spirits"),
    ("100% Blue Agave Tequila", "spirits"),
    ("London Dry Gin", "spirits"),
    ("Cabernet Sauvignon", "wine"),
    ("Sparkling Wine", "wine"),
    ("Hard Cider", "wine"),
    ("India Pale Ale", "malt"),
    ("Bourbon Barrel Aged Stout", "malt"),
    ("Special Reserve", None),
    ("Imported Virgin Islands Product", None),
])
def test_the_commodity_follows_the_designation(designation, expected):
    assert commodity_of(designation) == expected


def test_the_application_designation_wins_over_the_read_one():
    assert commodity_of("India Pale Ale", "Straight Rye Whiskey") == "malt"
    assert commodity_of(None, "Straight Rye Whiskey") == "spirits"


@pytest.mark.parametrize("field, commodity, expected", [
    ("brand_name", "spirits", "27 CFR 5.64 (brand name)"),
    ("brand_name", "wine", "27 CFR 4.33 (brand name)"),
    ("brand_name", "malt", "27 CFR 7.64 (brand name)"),
    ("net_contents", "malt", "27 CFR 7.70 (net contents)"),
    ("bottler_name", "wine", "27 CFR 4.35 (name and address)"),
    ("country_of_origin", "spirits", "27 CFR 5.69 and 19 CFR 134.11 (country of origin)"),
])
def test_each_commodity_is_cited_to_its_own_part(field, commodity, expected):
    assert citation(field, commodity) == expected


def test_an_unknown_commodity_names_all_three_parts():
    assert citation("alcohol_content", None) == (
        "27 CFR 5.65 (spirits), 4.36 (wine) or 7.65 (malt beverages): alcohol content")


def test_the_warning_is_not_in_the_commodity_table():
    assert citation("government_warning", "wine") is None


def _label(**kw):
    base = {"brand_name": "HARBOR LIGHT", "class_type": "India Pale Ale",
            "alcohol_statement": "6.5% ALC/VOL", "net_contents": "12 FL OZ",
            "warning_text": STATUTORY_WARNING, "warning_prefix_is_bold": True,
            "warning_legibility": "read"}
    return LabelExtraction(**(base | kw))


BEER = ApplicationRecord(cola_id="B", brand_name="Harbor Light", class_type="India Pale Ale",
                         alcohol_content_pct=6.5, net_contents="12 FL OZ")


def test_a_beer_label_is_cited_to_part_7():
    checks = {c.field: c for c in review(BEER, _label()).checks}
    assert checks["brand_name"].citation == "27 CFR 7.64 (brand name)"
    assert checks["alcohol_content"].citation == "27 CFR 7.65 (alcohol content)"
    assert checks["net_contents"].citation == "27 CFR 7.70 (net contents)"
    assert checks["government_warning"].citation == "27 CFR 16.21"


def test_a_beer_without_an_alcohol_statement_is_referred_not_rejected():
    r = review(BEER, _label(alcohol_statement=None))
    row = next(c for c in r.checks if c.field == "alcohol_content")
    assert row.verdict is Verdict.FLAG and not row.read_uncertain
    assert "7.65(a)" in row.reason
    assert r.verdict is Verdict.FLAG


def test_a_table_wine_without_an_alcohol_statement_is_referred():
    rows = check_alcohol_content(12.5, None, "wine")
    assert rows[0].verdict is Verdict.FLAG and "4.36(a)" in rows[0].reason


def test_a_strong_wine_without_an_alcohol_statement_still_fails():
    assert check_alcohol_content(15.5, None, "wine")[0].verdict is Verdict.FAIL


def test_a_spirit_without_an_alcohol_statement_still_fails():
    assert check_alcohol_content(45.0, None, "spirits")[0].verdict is Verdict.FAIL
    assert check_alcohol_content(45.0, None, None)[0].verdict is Verdict.FAIL
