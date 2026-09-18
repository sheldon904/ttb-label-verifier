# TTB Label Verification Prototype

A prototype that checks alcohol beverage label artwork against the data in its COLA
application, and shows a compliance agent exactly what matched, what didn't, and why.

> **Status: in progress.** The deterministic rule engine and its test suite are
> complete and green. Extraction, the web UI, batch processing and the evaluation
> harness are not yet implemented. See [Build plan](#build-plan).

## Scope and time box

The brief did not set a time budget, so I set one: **~16 hours.** Everything below is
scoped to fit inside it. Where I cut something, it is listed under
[Limitations](#limitations) rather than left half-built.

## Approach

**The model extracts. Deterministic code decides.**

This is the central design decision and everything else follows from it. The vision
model is asked only to *observe* the label and return a strict JSON schema — the field
values it can see, a verbatim transcription of the government warning, and typographic
observations. It is never asked whether the label passes. A plain, offline, fully
unit-tested rule engine (`app/rules/`) makes that call.

Three reasons this matters more here than in a typical app:

1. **Auditable.** A rejection has a regulatory consequence for the applicant. An agent
   can be shown which rule fired and which CFR section it came from — not "the model
   said so."
2. **Testable.** The entire decision layer runs with no API key, no network and no
   images. The 14 tests in `tests/test_rules.py` execute in ~2s.
3. **Non-hallucinating by construction.** The model cannot invent a `PASS`, because it
   is never given a verdict to return.

### Matching policy is per field

The brief plants a deliberate contradiction between two stakeholders:

- Dave Morrison wants `STONE'S THROW` on the label to pass against `Stone's Throw` in
  the application — "obviously the same thing. You need judgment."
- Jenny Park wants the government warning byte-exact — she rejected one for using title
  case.

Both are right. They are describing **different fields**, so a single global equality
check fails both of them:

| Field | Policy |
|---|---|
| Brand name | Unicode-normalize → casefold → strip punctuation → fuzzy ratio, banded PASS / FLAG / FAIL |
| Alcohol content | Parse numeric, compare with a class-specific tolerance, **and** cross-check proof = 2 × ABV |
| Net contents | Unit-normalize (`750 mL` = `75 cl` = `0.75 L`), then compare |
| Government warning | Whitespace-normalize, then **exact** against 27 CFR 16.21, with a word-level diff on mismatch |
| Warning typography | Advisory flag only — see [Limitations](#limitations) |

### Three verdicts, not two

`PASS` / `FLAG` / `FAIL`. Dave has watched binary automation fail before; a system that
cannot say "I'm not sure, look at this one" pushes its uncertainty onto the applicant.
Advisory checks can raise a result to `FLAG` but can never cause a `FAIL`.

### Deployment constraints

Marcus Williams: *"our network blocks outbound traffic to a lot of domains... half their
features didn't work because our firewall blocked connections to their ML endpoints."*

Extraction is therefore an interface (`app/extract/base.py`), not a vendor dependency. A
cloud VLM is the default; a local OCR implementation is the air-gapped path. The rule
engine cannot tell which one produced its input. For a real deployment this is also
where Azure OpenAI in Azure Government would slot in, given TTB's existing Azure
footprint and FedRAMP posture.

### Latency

Sarah Chen gave the one hard number in the brief: **~5 seconds, or agents abandon the
tool.** That is an interactive-review target and is distinct from batch throughput —
a 300-label batch at 5s serial is 25 minutes, but at 10-way concurrency it is ~2.5.
Both numbers will be **measured over the fixture set and published here** (p50/p95, n,
and the hardware) rather than described with an adjective.

## Assumptions

The brief is deliberately written as stakeholder interviews with no formal requirements
section, so these are my readings of it:

1. **Application records arrive as JSON/CSV alongside the images**, joined on `cola_id`.
   The brief never states how the application data enters the system; this was the
   largest open question and I resolved it rather than blocking on it.
2. **Distilled spirits are the primary class in scope**, per the worked example. Wine
   and malt beverages have materially different requirements and tolerances.
3. **No COLA integration**, per Marcus — standalone proof of concept.
4. **Nothing is persisted.** Images are processed in memory and discarded.

## Limitations

- **Type size cannot be verified from an image.** 27 CFR 16.22 specifies minimums in
  millimetres. A photograph gives pixels; without container dimensions or image DPI the
  conversion is unavailable. Boldness and legibility are surfaced as advisory flags for
  agent review and never hard-fail.
- **ABV tolerance is left at 0.0 and must be set per beverage class before any real
  use.** Tolerances differ across 27 CFR Parts 4, 5 and 7. The constant is marked in
  `app/rules/fields.py` — it should be cited, not invented.
- **The statutory warning text in `app/rules/warning.py` must be verified verbatim
  against eCFR** before submission. It is marked accordingly.

## Build plan

- [x] Domain models and the `extract` / `decide` seam
- [x] Rule engine: brand, alcohol content + proof consistency, net contents, warning text, typography
- [x] Rule-engine test suite (14 tests, no network)
- [ ] VLM extractor with image downscaling and schema-constrained output
- [ ] Single-label web UI
- [ ] Deploy (early, while it is still trivial)
- [ ] Batch upload with bounded concurrency
- [ ] Labeled fixture set with seeded defects + `make eval` confusion matrix
- [ ] Measured p50/p95 published above

## Running it

```bash
make install     # venv + dependencies
make test        # rule engine, no API key required
make dev         # http://localhost:8000
```

Copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY` for extraction. `make test`
works without it.

## Regulatory references

- 27 CFR 16.21 — health warning statement text
- 27 CFR 16.22 — type size and legibility
- 27 CFR Part 5 — distilled spirits labeling (reorganized in the 2020 modernization rulemaking; verify current section numbers on eCFR)
- 27 CFR Part 4 (wine), Part 7 (malt beverages)
