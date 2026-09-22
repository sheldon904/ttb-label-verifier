"""Formatting for the evaluation report."""

from __future__ import annotations

from dataclasses import dataclass, field

VERDICTS = ("pass", "flag", "fail")


def classify_miss(expected: str, actual: str) -> str:
    """Not all misses cost the same thing.

      correct    the verdict the fixture was built to produce
      cautious   a compliant label referred to an agent: costs a minute
      referred   a defective label referred instead of rejected: an agent
                 sees it and the defect is on the checklist, so nobody is
                 harmed, but the tool did not finish the job
      unsafe     a verdict nobody will look at again that is wrong: a
                 compliant label rejected, a label needing review rejected,
                 or anything that should not pass passed

    The first version of this counted "referred" as harm. A referral is the
    tool handing a label to a person, which is what the middle verdict is for;
    the harm is a wrong verdict that no person reviews. Reporting a single
    accuracy figure hides all of these differences, so the report splits them.
    """
    if expected == actual:
        return "correct"
    if actual == "pass" or actual == "fail":
        return "unsafe"
    if actual == "flag" and expected == "pass":
        return "cautious"
    if actual == "flag" and expected == "fail":
        return "referred"
    return "unsafe"


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
    error: str | None = None
    triage_p: float | None = None
    cleared: list[str] = field(default_factory=list)
    wrong_fails: list[str] = field(default_factory=list)

    @property
    def verdict_correct(self) -> bool:
        return self.error is None and self.expected == self.actual


@dataclass
class EvalSummary:
    model: str
    outcomes: list[FixtureOutcome] = field(default_factory=list)
    concurrency: int = 1
    wall_clock_s: float = 0.0
    triage: str | None = None
    second_opinion: str | None = None
    engine_version: str | None = None

    @property
    def throughput_per_min(self) -> float:
        if not self.wall_clock_s:
            return 0.0
        return self.n / self.wall_clock_s * 60.0

    @property
    def n(self) -> int:
        return len(self.outcomes)

    @property
    def cautious_misses(self) -> list:
        return [o for o in self.outcomes
                if classify_miss(o.expected, o.actual) == "cautious"]

    @property
    def referred_defects(self) -> list:
        return [o for o in self.outcomes
                if classify_miss(o.expected, o.actual) == "referred"]

    @property
    def unsafe_misses(self) -> list:
        """Wrong verdicts nobody will review, plus any row failed in error."""
        return [o for o in self.outcomes
                if o.error or o.wrong_fails or classify_miss(o.expected, o.actual) == "unsafe"]

    @property
    def accuracy(self) -> float:
        return sum(o.verdict_correct for o in self.outcomes) / self.n if self.n else 0.0

    def latencies(self) -> list[int]:
        return sorted(o.total_ms for o in self.outcomes if o.error is None)

    def pct(self, p: float) -> int:
        lat = self.latencies()
        if not lat:
            return 0
        idx = min(round(p / 100 * (len(lat) - 1)), len(lat) - 1)
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


def render_assist(summary: EvalSummary, a) -> None:
    """How the two advisory steps did. Neither can change a FAIL, so this is
    about referrals only: were the ones a second reading cleared really fine,
    and does triage rank genuine referrals above read problems?"""
    if summary.second_opinion:
        cleared = [o for o in summary.outcomes if o.cleared]
        a(f"## Second opinion (`{summary.second_opinion}`)\n")
        a(f"Cleared {len(cleared)} referral(s). A cleared row is a PASS the agent confirms on the "
          "artwork; a second reading can never produce a FAIL.\n")
        if cleared:
            a("| fixture | expected | rows cleared |")
            a("|---|---|---|")
            for o in cleared:
                a(f"| `{o.id}` | {o.expected} | {', '.join(o.cleared)} |")
            a("")
    scored = [o for o in summary.outcomes if o.actual == "flag" and o.triage_p is not None]
    if summary.triage and scored:
        genuine = [o for o in scored if o.expected != "pass"]
        noise = [o for o in scored if o.expected == "pass"]
        a(f"## Referral triage (`{summary.triage}`)\n")
        a("Triage orders referrals; it never changes a verdict. A referral of a label that should "
          "have passed is a read problem, and should score low. A referral of a label that "
          "genuinely needs a person should score high.\n")
        a("| fixture | referral is | chance of a genuine defect |")
        a("|---|---|---|")
        for o in sorted(scored, key=lambda o: -(o.triage_p or 0)):
            kind = "a read problem" if o.expected == "pass" else "genuine"
            a(f"| `{o.id}` | {kind} | {o.triage_p:.2f} |")
        a("")
        if genuine and noise:
            separated = min(o.triage_p for o in genuine) > max(o.triage_p for o in noise)
            pairs = [(g, n) for g in genuine for n in noise]
            ordered = sum(g.triage_p > n.triage_p for g, n in pairs) / len(pairs)
            a(f"Genuine referrals ranked above read problems in **{ordered:.0%}** of pairs"
              + (" (complete separation)." if separated else ".") + "\n")


def render(summary: EvalSummary) -> str:
    L: list[str] = []
    a = L.append

    a(f"# Evaluation report: `{summary.model}`\n")
    a(f"**{summary.n} fixtures · {summary.accuracy:.1%} verdict accuracy**\n")
    if summary.engine_version:
        a(f"OCR engine: Tesseract {summary.engine_version}.\n")

    a("## Outcome safety\n")
    a("A single accuracy number hides the distinction that matters here: "
      "escalating a compliant label costs an agent a minute, whereas rejecting "
      "one tells an applicant they broke the law when they did not.\n")
    a("| outcome | count |")
    a("|---|---|")
    a(f"| Correct | {sum(o.verdict_correct for o in summary.outcomes)} |")
    a(f"| Referred to a human when not strictly needed | {len(summary.cautious_misses)} |")
    a(f"| Defective, referred to a human instead of rejected | {len(summary.referred_defects)} |")
    a(f"| **Wrong in a way that harms someone** | **{len(summary.unsafe_misses)}** |")
    a("")

    a("## Latency and throughput\n")
    a("These are two different numbers and conflating them is misleading. Sarah "
      "Chen's five second budget is about an agent waiting on **one** label, so it "
      "must be measured without contention. Batch is a throughput question: under "
      "load, per-label wall clock rises while labels per minute improves.\n")
    a(f"Measured at concurrency **{summary.concurrency}** "
      f"({'interactive' if summary.concurrency == 1 else 'under load'}).\n")
    a("| p50 | p95 | p99 | max |")
    a("|---|---|---|---|")
    a(f"| {summary.pct(50)} ms | {summary.pct(95)} ms | {summary.pct(99)} ms | "
      f"{summary.pct(100)} ms |\n")
    if summary.concurrency == 1:
        budget = "MET" if summary.pct(95) < 5000 else "MISSED"
        a(f"Interactive target is < 5 000 ms. **p95 {budget}.**\n")
    if summary.wall_clock_s:
        a(f"Throughput: **{summary.throughput_per_min:.0f} labels/min** "
          f"({summary.n} in {summary.wall_clock_s:.1f}s). A 300-label batch would take "
          f"about **{300 / max(summary.throughput_per_min, 1e-9):.1f} minutes** at this "
          "concurrency.\n")

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

    render_assist(summary, a)

    a("## Cost\n")
    a("Nothing per label. There is no model, no API and no token. The only cost is "
      "local CPU time, which the latency table above already states.\n")

    wrong = [o for o in summary.outcomes if o.wrong_fails]
    a("## Rows failed in error" + "\n")
    a("A row that fails when the fixture was not built to fail it tells an applicant "
      "something is wrong that is not, even if the label fails for another reason. "
      "Counted as harmful above." + "\n")
    if not wrong:
        a("None." + "\n")
    else:
        a("| fixture | rows failed in error |")
        a("|---|---|")
        for o in wrong:
            a(f"| `{o.id}` | {', '.join(o.wrong_fails)} |")
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
