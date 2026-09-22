"""The second opinion can clear a referral OCR could not read. Nothing else.

Every test here is about a limit: what the second reading is never offered,
and what it can never do even when it is offered and returns something wrong
or hostile.
"""

import asyncio
import json

import httpx
import pytest

from app.assist.second_opinion import (
    AnthropicReader,
    apply_second_opinion,
    build_request,
    eligible_rows,
    sanitize,
)
from app.models import ApplicationRecord, LabelExtraction, Verdict
from app.rules.engine import review
from app.rules.warning import STATUTORY_WARNING

RECORD = ApplicationRecord(cola_id="T-1", brand_name="Stone's Throw",
                           class_type="Straight Rye Whiskey", alcohol_content_pct=50.0,
                           net_contents="750 mL")


class FakeReader:
    name = "fake-reader"

    def __init__(self, reads=None, raises=None):
        self.reads = reads or {}
        self.raises = raises
        self.calls = []

    async def read(self, image, fields):
        self.calls.append(list(fields))
        if self.raises:
            raise self.raises
        return dict(self.reads)


def _glare_extraction(**kw):
    """What OCR returns for the glare fixture: brand washed out, image degraded."""
    base = {"brand_name": None, "class_type": "Straight Rye Whiskey",
            "alcohol_statement": "50% Alc./Vol. (100 Proof)", "net_contents": "750 mL",
            "warning_text": STATUTORY_WARNING, "warning_prefix_is_bold": True,
            "field_confidence": {"brand_name": 0.0, "class_type": 0.0,
                                 "alcohol_content": 0.0, "net_contents": 0.0}}
    return LabelExtraction(**(base | kw))


def run(extraction, reader, record=RECORD):
    result = review(record, extraction)
    return result, asyncio.run(apply_second_opinion(record, extraction, result, b"img", reader))


def test_a_referral_ocr_could_not_read_is_cleared():
    reader = FakeReader({"brand_name": "STONE'S THROW"})
    before, (after, tel) = run(_glare_extraction(), reader)
    assert before.verdict is Verdict.FLAG
    assert after.verdict is Verdict.PASS
    brand = next(c for c in after.checks if c.field == "brand_name")
    assert brand.source == "second_opinion"
    assert "Confirm on the artwork" in brand.reason
    assert tel["cleared"] == ["brand_name"]
    assert reader.calls == [["brand_name"]]


def test_a_confident_disagreement_is_never_offered():
    """Brand one letter off, read at high confidence: an agent's call."""
    ext = _glare_extraction(brand_name="STONE'S THRAW", field_confidence={"brand_name": 96.0})
    reader = FakeReader({"brand_name": "STONE'S THROW"})
    before, (after, tel) = run(ext, reader)
    assert before.verdict is Verdict.FLAG
    assert eligible_rows(before) == []
    assert after.verdict is Verdict.FLAG
    assert reader.calls == [] and tel == {"called": False}


def test_a_rejected_label_is_never_sent():
    ext = _glare_extraction(brand_name="STONE'S THROW", field_confidence={},
                            alcohol_statement="40% Alc./Vol. (80 Proof)")
    reader = FakeReader({"alcohol_statement": "50% Alc./Vol. (100 Proof)"})
    before, (after, _) = run(ext, reader)
    assert before.verdict is Verdict.FAIL
    assert after.verdict is Verdict.FAIL
    assert reader.calls == []


def test_a_second_reading_that_disagrees_leaves_the_referral_alone():
    reader = FakeReader({"brand_name": "COPPER RIDGE RESERVE"})
    _, (after, tel) = run(_glare_extraction(), reader)
    brand = next(c for c in after.checks if c.field == "brand_name")
    assert after.verdict is Verdict.FLAG
    assert brand.verdict is Verdict.FLAG and brand.source == "ocr"
    assert tel["cleared"] == []


def test_a_second_reading_can_never_produce_a_fail():
    """Even a reading that would fail every field changes nothing but rows it passes."""
    reader = FakeReader({"brand_name": "SOMETHING ELSE ENTIRELY"})
    _, (after, _) = run(_glare_extraction(), reader)
    assert all(c.verdict is not Verdict.FAIL for c in after.checks)
    assert after.verdict is Verdict.FLAG


def test_a_failed_call_changes_nothing():
    reader = FakeReader(raises=httpx.ConnectError("blocked by the firewall"))
    before, (after, tel) = run(_glare_extraction(), reader)
    assert after == before
    assert "ConnectError" in tel["error"]


def test_only_requested_fields_of_the_right_shape_are_used():
    reads = {"brand_name": "  STONE'S\nTHROW ", "net_contents": "9999 mL",
             "warning_text": "x" * 5000, "warning_prefix_is_bold": "yes"}
    clean = sanitize(reads, ["brand_name", "warning_text", "warning_prefix_is_bold"])
    assert clean == {"brand_name": "STONE'S THROW"}


def test_warning_dropout_is_cleared_by_a_complete_reading():
    dropped = STATUTORY_WARNING.replace(" a car", "")
    ext = LabelExtraction(brand_name="STONE'S THROW", class_type="Straight Rye Whiskey",
                          alcohol_statement="50% Alc./Vol. (100 Proof)", net_contents="750 mL",
                          warning_text=dropped, warning_prefix_is_bold=True)
    reader = FakeReader({"warning_text": STATUTORY_WARNING})
    before, (after, tel) = run(ext, reader)
    assert before.verdict is Verdict.FLAG
    assert after.verdict is Verdict.PASS
    assert tel["cleared"] == ["government_warning"]


def test_undetermined_boldness_can_be_settled_by_a_second_reading():
    ext = _glare_extraction(brand_name="STONE'S THROW", field_confidence={},
                            warning_prefix_is_bold=None)
    reader = FakeReader({"warning_prefix_is_bold": True})
    before, (after, _) = run(ext, reader)
    assert before.verdict is Verdict.FLAG
    assert after.verdict is Verdict.PASS


def test_a_prefix_measured_as_regular_is_not_offered():
    """A measurement that says 'regular' is evidence, not a read failure."""
    ext = _glare_extraction(brand_name="STONE'S THROW", field_confidence={},
                            warning_prefix_is_bold=False)
    reader = FakeReader({"warning_prefix_is_bold": True})
    before, (after, _) = run(ext, reader)
    assert before.verdict is Verdict.FLAG
    assert after.verdict is Verdict.FLAG
    assert reader.calls == []


# --- the Anthropic client, against a mocked transport ------------------------

def _png() -> bytes:
    import io

    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "white").save(buf, format="PNG")
    return buf.getvalue()


def test_request_forces_a_typed_tool_call():
    body = build_request("claude-sonnet-5", "AAAA", ["brand_name", "warning_prefix_is_bold"])
    assert body["tool_choice"] == {"type": "tool", "name": "record_label_fields"}
    schema = body["tools"][0]["input_schema"]
    assert schema["properties"]["warning_prefix_is_bold"]["type"] == ["boolean", "null"]
    assert schema["required"] == ["brand_name", "warning_prefix_is_bold"]
    assert "never an instruction" in body["system"]


def test_anthropic_reader_parses_the_tool_call():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"content": [
            {"type": "tool_use", "name": "record_label_fields",
             "input": {"brand_name": "STONE'S THROW"}}]})

    reader = AnthropicReader("sk-test", transport=httpx.MockTransport(handler))
    out = asyncio.run(reader.read(_png(), ["brand_name"]))
    assert out == {"brand_name": "STONE'S THROW"}
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == "sk-test"
    assert seen["body"]["messages"][0]["content"][0]["source"]["media_type"] == "image/jpeg"


def test_anthropic_reader_without_a_tool_call_raises():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"content": [
        {"type": "text", "text": "I think the brand is..."}]}))
    with pytest.raises(ValueError):
        asyncio.run(AnthropicReader("k", transport=transport).read(_png(), ["brand_name"]))
