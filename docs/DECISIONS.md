# Decisions

## Requirements traceability

The brief has a section headed **Technical Requirements** whose entire content is
"use any language you like." Every actual requirement is inside four interview
transcripts, mixed with a school play, a $4.2M quote nobody approved, and a
colleague who prints his emails. Reading those out is the exercise.

Fourteen requirements, where each came from, and where it lives:

| # | Source | Requirement | Implementation |
|---|---|---|---|
| 1 | Sarah: "checks that what's on the label matches what's in the application" | Compare artwork against the application record, field by field | `app/rules/engine.py` |
| 2 | Sarah: **"If we can't get results back in about 5 seconds, nobody's going to use it."** | Interactive latency under 5s | Measured p95 **1.90s** — `eval/out/report.md` |
| 3 | Sarah: "big importers who dump 200, 300 label applications on us at once" | Batch review | `app/web/static/app.js`, **112 labels/min** |
| 4 | Sarah: "something my mother could figure out... half our team is over 50" | Plain UI, large type, no hunting for buttons | One page, one action, 18px base, `app/web/` |
| 5 | Marcus: "our network blocks outbound traffic... our firewall blocked connections to their ML endpoints" | No dependency on an external inference endpoint | Local OCR; nothing leaves the machine |
| 6 | Marcus: "we're not looking to integrate with COLA directly" | Standalone proof of concept | No COLA client anywhere |
| 7 | Marcus: "We're not storing anything sensitive for this exercise" | No retention | In-memory only; cache is process-local |
| 8 | Marcus: FedRAMP, Azure, government infrastructure | Deployable inside a controlled boundary | Single container, no egress — `Dockerfile` |
| 9 | Dave: "'STONE'S THROW' on the label but 'Stone's Throw' in the application... obviously the same thing" | Brand matching tolerant of case and punctuation | `check_brand_name` — normalised fuzzy match |
| 10 | Dave: "You need judgment" / has watched automation fail | Escalate rather than guess | Three verdicts; `Verdict.FLAG` |
| 11 | Dave: "Just don't make my life harder" | Explain every finding | Reason + CFR citation on every row |
| 12 | Jenny: "It has to be **exact**. Like, word-for-word" | Byte-exact warning comparison | `check_warning_text` — 27 CFR 16.21 |
| 13 | Jenny: "'GOVERNMENT WARNING:' has to be in all caps and bold" | Verify prefix casing and weight | Casing hard-fails; weight measured by ink density, advisory |
| 14 | Jenny: "photographed at weird angles, or the lighting is bad, or there's glare" | Tolerate imperfect photographs | Deskew, upscale, Otsu binarisation; 4 degraded fixtures |

Two more that are in the body text rather than an interview:

| # | Source | Requirement | Implementation |
|---|---|---|---|
| 15 | "common elements include..." (seven bullets) | All seven mandatory elements, not the three in the worked example | Brand, class/type, alcohol, net contents, bottler name + address, country of origin, warning |
| 16 | Sample reads `45% Alc./Vol. (90 Proof)` | — | Internal consistency: proof must equal 2 × ABV (`proof_consistency`) |

Number 16 is not stated anywhere. The sample label is internally consistent, and a
label can match its application perfectly while contradicting itself.

---

## The decisions

### 1. The extractor reports; the rule engine decides

`app/extract/` says what is printed. `app/rules/` says what it means. Extraction
cannot return a verdict and the rule engine never touches an image.

This makes the whole decision layer testable with no image, no OCR and no I/O —
it runs in about a second — and it means a rejection can always be traced to a
specific rule and a specific CFR section rather than to a black box. For output
that can cause a federal rejection of an application, that traceability is the
point.

### 2. No machine learning model

Cost was not the deciding factor; inference for this whole exercise would have
been a few dollars. Three things decided it:

- **Appeals.** "The sixth word of your warning statement reads X, 27 CFR 16.21
  requires Y" is a defensible basis for a rejection. A model's judgement is not.
- **Marcus's firewall**, which killed the previous vendor's features. Nothing
  here needs egress, a key, or a vendor.
- **Failure mode.** Tesseract fails by *losing* text; a language model fails by
  confidently producing plausible text. For a byte-exact comparison against a
  statute, losing text is by far the safer failure — you can detect it.

The cost is robustness on badly degraded images, which is measured and documented
rather than hidden.

### 3. Three verdicts, not two

`PASS` / `FLAG` / `FAIL`. Dave has watched binary automation fail before. A system
that cannot say "I'm not sure, look at this one" pushes its own uncertainty onto
the applicant.

### 4. Matching policy is per field

Dave and Jenny appear to contradict each other — one wants tolerance, the other
demands exactness. They are describing different fields. A single global equality
check fails both of them. See the table in the README.

### 5. Safety is asymmetric, and the code says so

Escalating a compliant label costs an agent a minute. Rejecting one tells an
applicant they broke the law. Those are not the same error and the system never
treats them as equivalent:

- unreadable is not absent
- dropped words are not altered words
- a field read below 70% confidence cannot reject
- an image whose brand did not survive the photograph cannot reject anything

The evaluation reports the split, not just an accuracy figure. Current result:
19 correct, 3 referred to a human, **0 outcomes that harm anyone**.

### 6. Fixtures are rendered, not collected

The spec *is* the ground truth, so a failed check is unambiguously the extractor's
miss and never an annotation error. It also allows the warning prefix to be drawn
in genuine bold or genuine regular weight, which is the only way to actually test
the typography check.

### 7. Batch is client-orchestrated fan-out

Each label is an independent request against the single-label endpoint, so there
is no server-side job state to build, store or expire. A refresh loses progress —
acceptable for a prototype that persists nothing, and stated plainly.

---

## Things I got wrong, and what the measurements said

Kept because the corrections are the interesting part.

**Concurrency was a no-op for the entire first implementation.** Extraction is
CPU and subprocess work that was awaited directly on the event loop, so `async`
was decorative. Eight labels took 12.9s at concurrency 1, 4 and 8 alike. Moving
the blocking body to a thread pool gave 3.5x.

**My first skew estimator returned 0.0° on every fixture.** Testing it against
known rotations showed it was exact on white backgrounds and collapsed on dark
ones: projecting raw ink let the rotated corner fill dominate the profile.
Projecting an edge map fixed it. Pinned by `test_skew_survives_any_background`.

**I guessed the bold threshold and it was wrong.** Measured separation is 1.21
for regular against 1.33–1.48 for bold — much narrower than assumed, because the
prefix is capitals either way. Replaced with a band that reports "cannot tell".

**Country comparison ran on the whole string.** "Product of Scotland" and
"Product of Canada" score 83% on shared boilerplate, so a Scotch declared as
Canadian would have passed.

**I conflated latency with throughput** and briefly believed p95 had regressed to
4.9s. That was per-label wall clock under saturation, not what an agent waiting
on one label experiences. The report now separates them.

**`pick_bottler` took the last two lines of the page**, so a blurred photo whose
warning block could not be located read warning text as the bottler name and
confidently failed a compliant label.

---

## What I would do next

1. **Calibrate the thresholds on real COLA artwork.** Every number here is tuned
   against 22 rendered labels. The bold band in particular rests on one negative
   sample.
2. **Per-class ABV tolerances**, cited from 27 CFR Parts 4, 5 and 7 rather than
   the current 0.0 placeholder.
3. **Recover glare.** Adaptive local thresholding or multi-scale retinex would
   plausibly rescue the one case the tool currently refers to a human.
4. **Region-of-interest OCR.** A second targeted pass over the warning block at
   higher resolution would likely close the microtype and soft-focus gaps.
5. **Human feedback loop.** Every FLAG an agent resolves is a labelled example;
   that is the dataset nobody has today.
