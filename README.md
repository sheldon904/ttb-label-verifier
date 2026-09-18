# TTB Label Verification Prototype

Checks alcohol beverage label artwork against the data in its COLA application and
shows a compliance agent exactly what matched, what didn't, and why.

**No machine learning model, no API key, no outbound network call.** Every field is
read with local OCR and every determination comes from an inspectable rule.

> **Status: in progress.** Rule engine, OCR extraction, evaluation harness and the
> single-label UI are complete. Batch upload and deployment are not yet built.

## Measured results

22 fixture labels, full pipeline, on a 2024 Apple silicon laptop:

| | |
|---|---|
| Verdict accuracy | **86.4%** (19/22) |
| Referred to a human unnecessarily | 3 |
| **Wrong in a way that harms someone** | **0** |
| Latency p50 / p95 | **1.75 s / 2.34 s** (budget: 5 s) |
| Cost per label | $0.00 |

Regenerate with `make eval`; the full report lands in `eval/out/report.md`.

A single accuracy figure would hide the distinction that matters. Escalating a
compliant label to an agent costs a minute. Rejecting one tells an applicant they
broke the law when they did not. All three misses are the first kind — degraded
photographs of compliant labels referred for human review. There are no false
rejections and no missed violations.

## Scope and time box

The brief set no time budget, so I set one: **~16 hours.** Where something was cut it
is listed under [Limitations](#limitations) rather than left half-built.

## Approach

### Why not a vision model

The centrepiece of this tool is a byte-exact comparison against a statutory text, and
its output can cause a federal rejection of someone's application. That argues for a
pipeline where every step can be quoted back in an appeal — "the sixth word of your
warning statement reads X, 27 CFR 16.21 requires Y" — rather than one that ultimately
rests on a model's judgement.

It also answers Marcus Williams directly. His firewall blocked the last vendor's ML
endpoints and killed half their features; nothing here needs to leave the building.
There is no key to rotate, no per-label cost, and no vendor to depend on.

### The extraction / decision split

`app/extract/` reports what is printed on the label. `app/rules/` decides what that
means. The two never mix: extraction cannot return a verdict, and the rule engine
never touches an image. That keeps the entire decision layer unit-testable with no
image, no OCR and no I/O — it runs in about a second.

### Matching policy is per field

The brief plants a deliberate contradiction between two stakeholders. Dave Morrison
wants `STONE'S THROW` to pass against `Stone's Throw` — "obviously the same thing."
Jenny Park rejected a label for setting `Government Warning` in title case. Both are
right, because they are describing different fields:

| Field | Policy |
|---|---|
| Brand name | Unicode-normalise → casefold → strip punctuation → fuzzy ratio, banded PASS / FLAG / FAIL |
| Alcohol content | Parse numeric, compare to the application, **and** cross-check proof = 2 × ABV |
| Net contents | Unit-normalise (`750 mL` = `75 cl` = `0.75 L`), then compare |
| Government warning | Whitespace-normalise, then **exact** against 27 CFR 16.21, with a word-level diff |
| Warning typography | Ink-density measurement, advisory only — see [Limitations](#limitations) |

### Three verdicts, not two

`PASS` / `FLAG` / `FAIL`. Dave has watched binary automation fail before; a system that
cannot say "I'm not sure, look at this one" pushes its own uncertainty onto the
applicant.

### Making OCR safe enough to reject on

Tesseract's characteristic failure is losing text, not inventing it. Four rules keep
that failure mode from ever being reported as a violation:

1. **Unreadable is not absent.** Small print detected but not resolved reports
   `illegible`, which flags. Only genuine absence fails.
2. **Dropped words are not altered words.** A near-perfect match that differs only by
   deletion is treated as an imperfect read and flagged. Substitutions — a title-case
   prefix, a softened phrase — stay hard failures.
3. **Low confidence cannot reject.** A field read below 70% confidence downgrades any
   failure to a flag.
4. **A degraded image cannot reject anything.** Every label sets its brand as the most
   prominent element. If nothing on the page is substantially larger than the body copy
   the brand did not survive the photograph, and no field from that image is trusted.
   This is what stops glare from promoting a bottler's name into the brand field and
   confidently mismatching it.

### What recovered the most accuracy

Two preprocessing steps, both found by measuring rather than assuming:

- **Deskew.** A 7° tilt made Tesseract miss the warning statement *entirely* — not
  misread it, miss it. Estimated by projecting an edge map and maximising the squared
  gradient of the horizontal profile. Projecting raw ink instead lets dark background
  at the corners dominate and the estimate collapses to zero; that regression is pinned
  by a test.
- **Upscale.** Small type sits below Tesseract's reliable floor until enlarged to
  roughly 300 DPI equivalent.

Together these took exact warning transcription from 17/22 to 20/22.

## Assumptions

The brief is written as stakeholder interviews with no formal requirements section, so
these are my readings of it:

1. **Application records arrive as JSON/CSV alongside the images**, joined on `cola_id`.
   The brief never says how application data enters the system; this was the largest
   open question and I resolved it rather than blocking.
2. **Distilled spirits are the primary class in scope**, per the worked example.
3. **No COLA integration**, per Marcus — standalone proof of concept.
4. **Nothing is persisted.** Images are processed in memory and discarded.

## Limitations

- **Type size cannot be verified from an image.** 27 CFR 16.22 specifies minimums in
  millimetres; a photograph carries pixels. Relative weight *is* measured (ink density
  of the prefix against the body copy), but it is advisory and never fails a label.
- **The bold/regular boundary is weakly calibrated.** Measured separation is 1.21 for
  regular against 1.33–1.48 for bold, from a single negative sample. Because the prefix
  is set in capitals either way, the gap is inherently narrow. The band leaves an
  explicit undecided zone that reports "cannot tell" rather than guessing.
- **Severe glare defeats field reading.** The tool detects this and refers the label to
  a human; it does not recover the text.
- **ABV tolerance is 0.0 and must be set per beverage class before real use.**
  Tolerances differ across 27 CFR Parts 4, 5 and 7. Marked in `app/rules/fields.py` —
  it should be cited, not invented.
- **The statutory warning text must be verified verbatim against eCFR** before
  submission. Marked in `app/rules/warning.py`.

## Build plan

- [x] Domain models and the extract / decide seam
- [x] Rule engine: brand, alcohol + proof consistency, net contents, warning, typography
- [x] OCR extraction: deskew, upscale, Otsu binarisation, layout-based field assignment
- [x] Safety rules that keep a read failure from becoming a rejection
- [x] 22-fixture evaluation harness with safety-classified outcomes
- [x] Single-label review UI
- [ ] Batch upload with bounded concurrency
- [ ] Deployment

## Running it

```bash
brew install tesseract     # the only system dependency
make install
make test                  # 100 tests, no network
make eval                  # full fixture sweep -> eval/out/report.md
make dev                   # http://localhost:8000
```

`make fixtures` regenerates the label set; it needs Arial, so the rendered PNGs are
committed to keep the eval set reproducible without it.

## Regulatory references

- 27 CFR 16.21 — health warning statement text
- 27 CFR 16.22 — type size and legibility
- 27 CFR Part 5 — distilled spirits labeling (reorganised in the 2020 modernisation rulemaking; verify current section numbers on eCFR)
- 27 CFR Part 4 (wine), Part 7 (malt beverages)
