"""Parsing a batch of application records.

The brief never says how application data reaches the tool, so the parser has
to cope with whatever an agent can export. A typo in one row must never cost
them the rest of the batch.
"""

from app.records import parse_records

CSV = (
    "cola_id,brand_name,class_type,abv,net_contents,country\n"
    "24-001,Old Tom Distillery,Kentucky Straight Bourbon Whiskey,45,750 mL,United States\n"
    "24-003,Copper Ridge Reserve,Single Malt Whisky,43,700 mL,Product of Scotland\n"
)


def test_parses_a_csv_export():
    p = parse_records(CSV.encode(), "records.csv")
    assert len(p.records) == 2
    assert p.records[0].cola_id == "24-001"
    assert p.records[0].alcohol_content_pct == 45.0
    assert p.records[1].country_of_origin == "Product of Scotland"
    assert not p.errors


def test_column_aliases_are_accepted():
    """An export should not have to be reshaped by hand."""
    csv = "TTB ID,Brand,Alc/Vol,Size\n24-009,Stone's Throw,50,750 mL\n"
    p = parse_records(csv.encode(), "x.csv")
    assert p.records[0].cola_id == "24-009"
    assert p.records[0].brand_name == "Stone's Throw"
    assert p.records[0].alcohol_content_pct == 50.0


def test_percent_signs_are_tolerated():
    p = parse_records(b"cola_id,brand,abv\n1,X,45.5%\n", "x.csv")
    assert p.records[0].alcohol_content_pct == 45.5


def test_parses_json_array():
    p = parse_records(b'[{"cola_id":"24-001","brand_name":"Old Tom"}]', "r.json")
    assert p.records[0].brand_name == "Old Tom"


def test_parses_json_object_with_records_key():
    p = parse_records(b'{"records":[{"cola_id":"1","brand_name":"X"}]}', "r.json")
    assert len(p.records) == 1


def test_image_column_is_captured_for_matching():
    csv = "cola_id,brand,image\n24-001,Old Tom,front.png\n"
    p = parse_records(csv.encode(), "x.csv")
    assert p.images["24-001"] == "front.png"


# --- a bad row must not abort the batch -----------------------------------

def test_one_bad_row_does_not_lose_the_others():
    csv = ("cola_id,brand,abv\n"
           "24-001,Old Tom,45\n"
           "24-002,Bad Row,not-a-number\n"
           "24-003,Copper Ridge,43\n")
    p = parse_records(csv.encode(), "x.csv")
    assert [r.cola_id for r in p.records] == ["24-001", "24-003"]
    assert len(p.errors) == 1
    assert "not a number" in p.errors[0]


def test_row_without_a_cola_id_is_reported():
    p = parse_records(b"cola_id,brand\n,Nameless\n", "x.csv")
    assert not p.records
    assert "COLA ID" in p.errors[0]


def test_duplicate_ids_keep_the_first():
    csv = "cola_id,brand\n24-001,First\n24-001,Second\n"
    p = parse_records(csv.encode(), "x.csv")
    assert len(p.records) == 1
    assert p.records[0].brand_name == "First"
    assert "duplicate" in p.errors[0]


def test_empty_file_is_reported_clearly():
    assert "empty" in parse_records(b"", "x.csv").errors[0]


def test_malformed_json_is_reported_clearly():
    assert "JSON" in parse_records(b"[{oops}]", "r.json").errors[0]


def test_bom_prefixed_csv_from_excel_is_handled():
    """Excel writes a UTF-8 BOM, which otherwise corrupts the first header."""
    p = parse_records("﻿cola_id,brand\n24-001,Old Tom\n".encode(), "x.csv")
    assert p.records[0].cola_id == "24-001"
