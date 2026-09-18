"""Core domain types.

Design rule for this whole codebase: the model EXTRACTS, this code DECIDES.
Nothing in app/extract/ ever returns a verdict -- it reports what it observed on
the label. Everything in app/rules/ is deterministic, offline-testable, and is
the only thing allowed to produce a Verdict.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


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

    confidence: dict[str, float] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class CheckResult(BaseModel):
    """One row of the agent's checklist."""

    field: str
    verdict: Verdict
    expected: str | None = None
    observed: str | None = None
    reason: str = ""
    citation: str | None = None
    advisory: bool = False


class ReviewResult(BaseModel):
    cola_id: str
    verdict: Verdict
    checks: list[CheckResult]
    elapsed_ms: int | None = None
