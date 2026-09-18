"""to_extraction: the boundary where a model's loose dict becomes a typed value."""

from app.extract.base import to_extraction


def test_blank_strings_become_none():
    e = to_extraction({"brand_name": "   ", "net_contents": ""})
    assert e.brand_name is None and e.net_contents is None


def test_missing_keys_do_not_crash():
    assert to_extraction({}).brand_name is None


def test_warning_case_is_preserved_exactly():
    """If this ever normalizes, the exact-match check becomes worthless."""
    e = to_extraction({"warning_text": "Government Warning: (1) According to..."})
    assert e.warning_text.startswith("Government Warning:")


def test_non_boolean_boldness_becomes_none():
    assert to_extraction({"warning_prefix_is_bold": "yes"}).warning_prefix_is_bold is None
    assert to_extraction({"warning_prefix_is_bold": False}).warning_prefix_is_bold is False


def test_legibility_notes_are_carried_through():
    e = to_extraction({"legibility_notes": ["glare on the upper third", "", "  "]})
    assert e.notes == ["glare on the upper third"]
