"""Core domain types.

Design rule for this whole codebase: the model EXTRACTS, this code DECIDES.
Nothing in app/extract/ ever returns a verdict -- it reports what it observed on
the label. Everything in app/rules/ is deterministic, offline-testable, and is
the only thing allowed to produce a Verdict.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Verdict(str, Enum):
    """Three states, not two.

    Dave Morrison (28y agent) asked for judgment, not a binary gate: a brand of
    "STONE'S THROW" against an application record of "Stone's Throw" is a PASS,
    not a rejection. Anything genuinely ambiguous escalates to a human rather
    than guessing.
    """

    PASS = "pass"
    FLAG = "flag"
    FAIL = "fail"


class ApplicationRecord(BaseModel):
    """The COLA application data an agent is checking the artwork against.

    ASSUMPTION (the take-home never specifies how this enters the system): it is
    supplied as JSON/CSV alongside the images and joined on `cola_id`. Documented
    in README under Assumptions.
    """

    cola_id: str
    brand_name: str
    class_type: str | None = None
    alcohol_content_pct: float | None = None
    net_contents: str | None = None
    bottler_name: str | None = None
    bottler_address: str | None = None
    country_of_origin: str | None = None


class LabelExtraction(BaseModel):
    """What was observed on the label artwork. Observations only -- no judgments."""

    brand_name: str | None = None
    class_type: str | None = None
    alcohol_statement: str | None = None  # verbatim, e.g. "45% Alc./Vol. (90 Proof)"
    net_contents: str | None = None
    bottler_name: str | None = None
    bottler_address: str | None = None
    country_of_origin: str | None = None

    warning_text: str | None = Field(
        default=None,
        description="Verbatim transcription of the government warning, including the prefix.",
    )
    warning_prefix_is_bold: bool | None = Field(
        default=None,
        description="Advisory typographic observation; None when not determinable.",
    )
    warning_small_type: bool = Field(
        default=False,
        description=(
            "The warning is set in type too small to measure from the image. That is "
            "a type-size question under 27 CFR 16.22(b), which no reading of the text "
            "can settle, so it stays with an agent."
        ),
    )
    warning_legibility: Literal["read", "illegible", "absent"] = Field(
        default="absent",
        description=(
            "Whether the warning was read, detected but unreadable, or genuinely "
            "not present. The middle state exists so that a bad photograph of a "
            "compliant label is never reported as a violation."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _infer_legibility(cls, data):
        """Default legibility from whether warning text is present.

        An extractor that reports text has by definition read it, and one that
        reports none has not. Only a caller with better information -- OCR that
        detected small print it could not resolve -- states it explicitly, and
        an explicit value always wins.
        """
        if isinstance(data, dict) and "warning_legibility" not in data:
            data = {**data,
                    "warning_legibility": "read" if data.get("warning_text") else "absent"}
        return data

    field_confidence: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Per-field read confidence, 0-100. The rule engine refuses to reject a "
            "label on a field it could not read reliably."
        ),
    )
    notes: list[str] = Field(default_factory=list)
    field_boxes: dict[str, list[list[float]]] = Field(
        default_factory=dict,
        description=(
            "Where each field was read, as a four-corner polygon in fractions of the "
            "image as the agent sees it (EXIF orientation applied). Evidence for the "
            "agent, never an input to a verdict."
        ),
    )


class CheckResult(BaseModel):
    """One row of the agent's checklist."""

    field: str
    verdict: Verdict
    expected: str | None = None
    observed: str | None = None
    reason: str = ""
    citation: str | None = None
    advisory: bool = False
    # Which question this row answers: does the label match its application,
    # or does the label meet the regulation on its own terms?
    layer: Literal["application", "regulation"] = "application"
    # True when a FLAG exists because the image could not be read reliably,
    # rather than because a confident read disagreed. Only these rows are ever
    # offered to a second opinion; a confident disagreement is an agent's call.
    read_uncertain: bool = False
    # "ocr" for every row the rules produced from the OCR read; "second_opinion"
    # for a row a second reading cleared. Never set on a FAIL.
    source: Literal["ocr", "second_opinion"] = "ocr"


class Triage(BaseModel):
    """How likely a referral is to be a genuine defect rather than a read error.

    Advisory ordering for a queue of referrals. It never changes a verdict.
    """

    probability: float = Field(ge=0.0, le=1.0)
    provider: str


class ReviewResult(BaseModel):
    cola_id: str
    verdict: Verdict
    checks: list[CheckResult]
    elapsed_ms: int | None = None
    triage: Triage | None = None
