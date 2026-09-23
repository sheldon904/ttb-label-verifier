"""Parsing a batch of application records.

The brief never says how application data reaches the tool, so this accepts the
two formats an agent can actually produce from an existing system: a CSV export
and a JSON array. Errors are reported per row and never abort the batch -- a
typo in row 40 of a 300-row export should not cost an agent the other 299.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
from dataclasses import dataclass, field

from pydantic import ValidationError

from app.models import ApplicationRecord

# Accepted column spellings, so an export does not have to be reshaped by hand.
ALIASES = {
    "cola_id": {"cola_id", "cola", "colaid", "id", "ttb_id", "ttbid", "application_id"},
    # Not "fanciful name": on a COLA that is a separate field, and taking it as
    # the brand failed the brand check on a compliant label.
    "brand_name": {"brand_name", "brand", "brandname"},
    "class_type": {"class_type", "class", "type", "classtype", "class_and_type", "designation"},
    "alcohol_content_pct": {"alcohol_content_pct", "abv", "alcohol", "alcohol_content",
                            "alc_vol", "alcohol_percent", "alcohol_pct", "alc_by_vol",
                            "alcohol_by_volume", "proof_abv"},
    "net_contents": {"net_contents", "net", "netcontents", "volume", "size", "fill"},
    "bottler_name": {"bottler_name", "bottler", "producer", "bottler_producer", "applicant"},
    "bottler_address": {"bottler_address", "address", "bottleraddress", "city_state"},
    "country_of_origin": {"country_of_origin", "country", "origin", "countryoforigin"},
    "image": {"image", "image_file", "filename", "file", "artwork", "label_image"},
}


def parse_abv(value: object) -> float | None:
    """'45', '45.0', '45%', '45 %', '40,5' -> a number; '' -> None.

    Raises ValueError for anything that is not a percentage above 0 and at
    most 100. One parser for the form and for records files: the same typo
    ("450" for "45.0") is refused in both places, never accepted in one and
    compared against the label in the other.
    """
    cleaned = str(value).replace("%", "").replace(",", ".").strip()
    if not cleaned:
        return None
    try:
        abv = float(cleaned)
    except ValueError:
        abv = math.nan
    # A nan compares false with everything, so "nan" fails this test too.
    if not 0 < abv <= 100:
        raise ValueError(cleaned)
    return abv


@dataclass
class ParsedRecords:
    records: list[ApplicationRecord] = field(default_factory=list)
    images: dict[str, str] = field(default_factory=dict)   # cola_id -> declared filename
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.records)


def _canonical(name: str) -> str | None:
    """Normalise a column heading before matching it against the aliases.

    Spreadsheet headings arrive as "TTB ID", "Alc/Vol", "Alc. / Vol." and so on.
    Every run of non-alphanumeric characters collapses to a single underscore so
    all of those reach the same key.
    """
    key = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    for canonical, spellings in ALIASES.items():
        if key in spellings:
            return canonical
    return None


def _coerce(row: dict, index: int) -> tuple[ApplicationRecord | None, str | None, str | None]:
    mapped: dict[str, object] = {}
    image = None
    for raw_key, raw_value in row.items():
        if raw_key is None:
            continue
        canonical = _canonical(str(raw_key))
        if canonical is None:
            continue
        value = raw_value.strip() if isinstance(raw_value, str) else raw_value
        if value in ("", None):
            continue
        if canonical in mapped or (canonical == "image" and image is not None):
            # Two columns mean the same field ("TTB ID" and "ID"): the first
            # one in the file wins, rather than the last silently overwriting it.
            continue
        if canonical == "image":
            image = str(value)
        elif canonical == "alcohol_content_pct":
            try:
                mapped[canonical] = parse_abv(value)
            except ValueError:
                return None, None, (
                    f"Row {index}: alcohol content {value!r} must be a number between 0 and "
                    "100, for example 45 or 45.5."
                )
        else:
            # A JSON export can carry a numeric TTB ID; every field is text.
            mapped[canonical] = value if isinstance(value, str) else str(value)

    if not mapped.get("cola_id"):
        return None, None, f"Row {index}: no COLA ID column found or the value is empty."
    if not mapped.get("brand_name"):
        return None, None, f"Row {index}: no brand name for {mapped['cola_id']}."

    try:
        return ApplicationRecord(**mapped), image, None
    except ValidationError as exc:
        return None, None, f"Row {index}: {exc.errors()[0]['msg']}"


def _dialect(text: str) -> type[csv.Dialect] | csv.Dialect:
    """Comma, semicolon (European Excel), tab or pipe, judged from the header."""
    header = text.splitlines()[0] if text else ""
    try:
        return csv.Sniffer().sniff(header, delimiters=",;\t|")
    except csv.Error:
        return csv.excel


def _decode(data: bytes) -> str:
    """UTF-16 with a byte-order mark (Excel's "Unicode text"), UTF-8, or the
    Windows code page Excel uses for a plain "CSV" save. Decoded as UTF-8
    regardless, "Château" from a Windows export became "Ch�teau"."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def parse_records(data: bytes, filename: str = "") -> ParsedRecords:
    text = _decode(data).strip()
    if not text:
        return ParsedRecords(errors=["The records file is empty."])

    looks_json = filename.lower().endswith(".json") or text[0] in "[{"
    rows: list[dict]

    if looks_json:
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError as exc:
            return ParsedRecords(errors=[f"Could not read the JSON records file: {exc.msg}."])
        if isinstance(loaded, dict):
            loaded = loaded.get("records", [loaded])
        if not isinstance(loaded, list):
            return ParsedRecords(errors=["Expected a JSON array of application records."])
        # A JSON row is numbered by its place in the array.
        rows = [(i, r) for i, r in enumerate(loaded, start=1) if isinstance(r, dict)]
    else:
        # A CSV row is numbered as a spreadsheet numbers it, heading row
        # included, so "Row 3" is the row the agent sees as 3 in Excel.
        try:
            reader = csv.DictReader(io.StringIO(text), dialect=_dialect(text))
            rows = [(reader.line_num, row) for row in reader]
        except csv.Error as exc:
            return ParsedRecords(errors=[f"Could not read the CSV records file: {exc}."])

    if not rows:
        return ParsedRecords(errors=[(
            "No application records were found in that file. It needs a heading row with "
            "at least a COLA ID column and a brand name column.")])

    out = ParsedRecords()
    seen: set[str] = set()
    for i, row in rows:
        record, image, error = _coerce(row, i)
        if error:
            out.errors.append(error)
            continue
        if record.cola_id in seen:
            out.errors.append(f"Row {i}: duplicate COLA ID {record.cola_id}; the first was kept.")
            continue
        seen.add(record.cola_id)
        out.records.append(record)
        if image:
            out.images[record.cola_id] = image
    return out
