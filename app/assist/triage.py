"""Referral triage: which referred labels should an agent look at first?

Sarah Chen's peak-season problem is 200 to 300 labels arriving at once. After
a batch run the agent faces a pile of referrals. Some are genuine questions (a
brand one letter off, a prefix that measures regular weight); some exist only
because the photograph was poor. Triage estimates which is which and orders
the queue. It never changes a verdict.

The state sent to a triage model contains no text from the label: field
names, verdicts, similarity scores and word counts only. A label is artwork
the applicant designed, so any label text that reached a decision model would
be text the applicant wrote into its prompt. Sending only our own typed
findings removes that surface.
"""

from __future__ import annotations

import re
from typing import Protocol

import httpx

from app.models import CheckResult, ReviewResult, Triage, Verdict

_SIMILARITY = re.compile(r"similarity (\d+)%")
_CONFIDENCE = re.compile(r"low confidence \((\d+)%\)")


def _count(reason: str, marker: str) -> int:
    return reason.count(marker)


def finding(c: CheckResult) -> dict:
    """One row of the checklist as typed facts. Never a quoted label value."""
    out: dict[str, object] = {
        "field": c.field,
        "verdict": c.verdict.value,
        "layer": c.layer,
        "advisory": c.advisory,
        "read_uncertain": c.read_uncertain,
        "cleared_by_second_reading": c.source == "second_opinion",
    }
    if m := _SIMILARITY.search(c.reason):
        out["similarity_pct"] = int(m.group(1))
    if m := _CONFIDENCE.search(c.reason):
        out["read_confidence_pct"] = int(m.group(1))
    if c.field == "government_warning" and c.verdict is not Verdict.PASS:
        out["words_missing"] = _count(c.reason, "missing '")
        out["words_unexpected"] = _count(c.reason, "unexpected '")
        # "unexpected '" contains "expected '", so substitutions are the difference.
        out["words_substituted"] = _count(c.reason, "expected '") - out["words_unexpected"]
    return out


def triage_state(result: ReviewResult) -> dict:
    return {
        "overall_verdict": result.verdict.value,
        "findings": [finding(c) for c in result.checks
                     if c.verdict is not Verdict.PASS or c.source == "second_opinion"],
    }


class TriageProvider(Protocol):
    name: str

    async def score(self, result: ReviewResult) -> Triage | None: ...


class HeuristicTriage:
    """The local baseline, and what a model has to beat to earn its place.

    A referral that exists only because of the read scores low; a confident
    disagreement scores high; a measured-but-advisory finding sits between.
    The label takes its most serious row.
    """

    name = "heuristic"

    async def score(self, result: ReviewResult) -> Triage | None:
        if result.verdict is not Verdict.FLAG:
            return None
        weights = []
        for c in result.checks:
            if c.verdict is not Verdict.FLAG:
                continue
            if c.read_uncertain:
                weights.append(0.2)
            elif c.advisory:
                weights.append(0.55)
            else:
                weights.append(0.85)
        if not weights:
            return None
        return Triage(probability=max(weights), provider=self.name)


GATEWAY_URL = "https://ai-gateway.vercel.sh/v1/evaluate"

QUESTION = {
    "type": "boolean",
    "instructions": (
        "These are the findings of an automated check of an alcohol beverage label "
        "against its application and 27 CFR. The label was referred to a human. Is the "
        "referral more likely caused by a genuine problem with the label than by the "
        "image being hard to read?"
    ),
    "criteria": {
        "true": ("at least one finding is a confident disagreement: read_uncertain is "
                 "false and the similarity or measurement still falls short"),
        "false": ("every referred finding is read_uncertain, cleared by a second reading, "
                  "or advisory with nothing else wrong"),
    },
}


class JevTriage:
    """TypeSafe's Jev through Vercel AI Gateway's evaluation endpoint."""

    def __init__(self, api_key: str, model: str = "typesafe-ai/jev",
                 transport: httpx.AsyncBaseTransport | None = None,
                 timeout_s: float = 5.0) -> None:
        self._key = api_key
        self._model = model
        self._transport = transport
        self._timeout = timeout_s
        self.name = model

    def build_request(self, result: ReviewResult) -> dict:
        # No zero-data-retention option: on AI Gateway it is a paid-plan
        # feature, and the state carries no label content to retain anyway.
        return {
            "model": self._model,
            "state": triage_state(result),
            "questions": {"genuine_defect": QUESTION},
        }

    async def score(self, result: ReviewResult) -> Triage | None:
        """Jev's estimate, or the local heuristic's when Jev cannot answer.

        A blocked network (Marcus's firewall), an expired credential or a
        spent balance all end the same way: the queue is still ordered, and
        the row says which estimator ordered it.
        """
        if result.verdict is not Verdict.FLAG:
            return None
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                r = await client.post(GATEWAY_URL, json=self.build_request(result), headers={
                    "Authorization": f"Bearer {self._key}",
                    "Content-Type": "application/json",
                })
                r.raise_for_status()
                p = r.json()["answers"]["genuine_defect"]["probability"]
            return Triage(probability=float(p), provider=self.name)
        except Exception:  # noqa: BLE001 - triage is advisory; fall back rather than go blank
            return await HeuristicTriage().score(result)


def build_triage(settings) -> TriageProvider | None:
    if settings.triage == "jev" and settings.ai_gateway_api_key:
        return JevTriage(settings.ai_gateway_api_key, settings.triage_model)
    if settings.triage in ("heuristic", "jev"):
        # "jev" without a key falls back to the local baseline rather than to nothing.
        return HeuristicTriage()
    return None
