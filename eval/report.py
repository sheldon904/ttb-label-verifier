"""Formatting for the evaluation report."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

VERDICTS = ("pass", "flag", "fail")

# Approximate published rates, USD per million tokens. VERIFY BEFORE QUOTING --
# pricing changes and a stale number in a submission is worse than no number.
PRICING = {
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-sonnet-5": (3.00, 15.00),
}


@dataclass
class FixtureOutcome:
    id: str
    description: str
    expected: str
    actual: str
    expected_fields: list[str]
    actual_failing_fields: list[str]
    field_hits: dict[str, bool]
    total_ms: int
    input_tokens: int
    output_tokens: int
    error: str | None = None

    @property
    def verdict_correct(self) -> bool:
        return self.error is None and self.expected == self.actual


@dataclass
class EvalSummary:
    model: str
    outcomes: list[FixtureOutcome] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.outcomes)

    @property
    def accuracy(self) -> float:
        return sum(o.verdict_correct for o in self.outcomes) / self.n if self.n else 0.0

    def latencies(self) -> list[int]:
        return sorted(o.total_ms for o in self.outcomes if o.error is None)

    def pct(self, p: float) -> int:
        lat = self.latencies()
        if not lat:
            return 0
        idx = min(int(round(p / 100 * (len(lat) - 1))), len(lat) - 1)
        return lat[idx]

    def confusion(self) -> dict[tuple[str, str], int]:
        m = {(e, a): 0 for e in VERDICTS for a in VERDICTS}
        for o in self.outcomes:
            if o.error is None:
                m[(o.expected, o.actual)] = m.get((o.expected, o.actual), 0) + 1
        return m

    def field_accuracy(self) -> dict[str, float]:
        totals: dict[str, list[bool]] = {}
        for o in self.outcomes:
            for k, v in o.field_hits.items():
                totals.setdefault(k, []).append(v)
        return {k: sum(v) / len(v) for k, v in sorted(totals.items()) if v}

    def mean_tokens(self) -> tuple[float, float]:
        ok = [o for o in self.outcomes if o.error is None]
        if not ok:
            return (0.0, 0.0)
        return (statistics.mean(o.input_tokens for o in ok),
                statistics.mean(o.output_tokens for o in ok))

    def cost_per_label(self) -> float | None:
        rates = PRICING.get(self.model)
        if not rates:
            return None
        inp, out = self.mean_tokens()
        return (inp / 1e6) * rates[0] + (out / 1e6) * rates[1]


def render(summary: EvalSummary) -> str:
    L: list[str] = []
    a = L.append

    a(f"# Evaluation report — `{summary.model}`\n")
    a(f"**{summary.n} fixtures · {summary.accuracy:.1%} verdict accuracy**\n")

    a("## Latency\n")
    a("Wall clock for the full operation: preprocessing, extraction and rule evaluation.\n")
    a("| p50 | p95 | p99 | max |")
    a("|---|---|---|---|")
    a(f"| {summary.pct(50)} ms | {summary.pct(95)} ms | {summary.pct(99)} ms | "
      f"{summary.pct(100)} ms |\n")
    budget = "MET" if summary.pct(95) < 5000 else "MISSED"
    a(f"Target is < 5 000 ms (Sarah Chen). **p95 {budget}.**\n")

    a("## Verdict confusion matrix\n")
    m = summary.confusion()
    a("| expected \\ actual | pass | flag | fail |")
    a("|---|---|---|---|")
    for e in VERDICTS:
        cells = " | ".join(str(m.get((e, x), 0)) for x in VERDICTS)
        a(f"| **{e}** | {cells} |")
    a("")

    a("## Field extraction accuracy\n")
    a("| field | correct |")
    a("|---|---|")
    for k, v in summary.field_accuracy().items():
        a(f"| `{k}` | {v:.0%} |")
    a("")

    inp, out = summary.mean_tokens()
    cost = summary.cost_per_label()
    a("## Cost\n")
    a(f"Mean {inp:.0f} input / {out:.0f} output tokens per label.")
    if cost is not None:
        a(f" Approximately **${cost:.4f} per label**, ${cost * 150_000:,.0f} "
          f"at TTB's stated 150 000 applications per year.")
        a("\n_Rates are approximate and must be re-checked before being quoted._")
    a("")

    misses = [o for o in summary.outcomes if not o.verdict_correct]
    a(f"## Misses ({len(misses)})\n")
    if not misses:
        a("None.\n")
    else:
        a("| fixture | expected | actual | note |")
        a("|---|---|---|---|")
        for o in misses:
            note = o.error or f"flagged {', '.join(o.actual_failing_fields) or 'nothing'}"
            a(f"| `{o.id}` | {o.expected} | {o.actual} | {note} |")
        a("")

    a("## All fixtures\n")
    a("| fixture | expected | actual | ms | description |")
    a("|---|---|---|---|---|")
    for o in summary.outcomes:
        mark = "" if o.verdict_correct else " ⚠"
        a(f"| `{o.id}` | {o.expected} | {o.actual}{mark} | {o.total_ms} | {o.description} |")
    a("")
    return "\n".join(L)
