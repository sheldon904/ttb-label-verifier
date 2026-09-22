# Decisions

## Requirements traceability

The brief has a section headed **Technical Requirements** whose entire content is
"use any language you like." Every actual requirement is inside four interview
transcripts, mixed with a school play, a $4.2M quote nobody approved and a
colleague who prints his emails. Reading those out is the exercise.

Fourteen requirements, where each came from and where it lives:

| # | Source | Requirement | Implementation |
|---|---|---|---|
| 1 | Sarah: "checks that what's on the label matches what's in the application" | Compare artwork against the application record, field by field | `app/rules/engine.py` |
| 2 | Sarah: **"If we can't get results back in about 5 seconds, nobody's going to use it."** | Interactive latency under 5s | Measured p95 **1.45 to 1.53 s** at concurrency 1, on three Tesseract builds: `eval/out/` |
| 3 | Sarah: "big importers who dump 200, 300 label applications on us at once" | Batch review | `app/web/static/app.js`; **219 labels/min** with 8 workers; referrals sorted by triage |
| 4 | Sarah: "something my mother could figure out... half our team is over 50" | Plain UI, large type, no hunting for buttons | One page, one action, 18px base, artwork beside the checklist with a box where each field was read, prints cleanly |
| 5 | Marcus: "our network blocks outbound traffic... our firewall blocked connections to their ML endpoints" | No dependency on an external inference endpoint | Local OCR; the default makes no outbound call; both model features are optional and fail safe when blocked |
| 6 | Marcus: "we're not looking to integrate with COLA directly" | Standalone proof of concept | No COLA client anywhere |
| 7 | Marcus: "We're not storing anything sensitive for this exercise" | No retention | In-memory only; cache is process-local |
| 8 | Marcus: FedRAMP, Azure, government infrastructure | Deployable inside a controlled boundary | Single container, no egress, unprivileged user: `Dockerfile` |
| 9 | Dave: "'STONE'S THROW' on the label but 'Stone's Throw' in the application... obviously the same thing" | Brand matching tolerant of case and punctuation | `check_brand_name`, normalised fuzzy match |
| 10 | Dave: "You need judgment" / has watched automation fail | Escalate rather than guess | Three verdicts; `Verdict.FLAG` |
| 11 | Dave: "Just don't make my life harder" | Explain every finding | Reason and CFR citation on every row |
| 12 | Jenny: "It has to be **exact**. Like, word-for-word" | Exact warning comparison | `check_warning_text`, 27 CFR 16.21 |
| 13 | Jenny: "'GOVERNMENT WARNING:' has to be in all caps and bold" | Verify prefix casing and weight | Casing hard-fails citing 16.22(b); weight measured by ink density, advisory |
| 14 | Jenny: "photographed at weird angles, or the lighting is bad, or there's glare" | Tolerate imperfect photographs | Deskew, upscale, Otsu binarisation; 6 degraded fixtures; an optional second reading for what OCR cannot recover |

Three more that are in the body text rather than an interview:

| # | Source | Requirement | Implementation |
|---|---|---|---|
| 15 | "common elements include..." (seven bullets) | All seven mandatory elements, not the three in the worked example | Brand, class/type, alcohol, net contents, bottler name and address, country of origin, warning |
| 16 | Sample reads `45% Alc./Vol. (90 Proof)` | Internal consistency: proof must equal 2 × ABV | `proof_consistency` |
| 17 | Deliverables: "Deployed Application URL" | A reviewer can open it | Container image, built and checked by CI; URL in the README |
| 18 | Title: "AI-Powered Alcohol Label Verification App" | Use AI where it helps | A vision model's second reading of referrals and Jev triage, both advisory and opt-in: decisions 9 and 10 |

Number 16 is not stated anywhere. The sample label is internally consistent, and a
label can match its application perfectly while contradicting itself.

---

## The decisions

### 1. The extractor reports; the rule engine decides

`app/extract/` says what is printed. `app/rules/` says what it means. Extraction
cannot return a verdict and the rule engine never touches an image.

This makes the whole decision layer testable with no image, no OCR and no I/O,
and it means a rejection can always be traced to a specific rule and a specific
CFR section rather than to a black box. For output that can cause a federal
rejection of an application, that traceability is the point.

### 2. No machine learning model

Cost was not the deciding factor; inference for this whole exercise would have
been a few dollars. Three things decided it:

- **Appeals.** "The sixth word of your warning statement reads X, 27 CFR 16.21
  requires Y" is a defensible basis for a rejection. A model's judgement is not.
- **Marcus's firewall**, which killed the previous vendor's features. Nothing
  here needs egress, a key or a vendor.
- **Failure mode.** Tesseract fails by *losing* text; a language model fails by
  confidently producing plausible text. For a byte-exact comparison against a
  statute, losing text is by far the safer failure, because you can detect it.

The cost is weaker reads of badly degraded images, which are measured and
documented.

### 3. Three verdicts, not two

`PASS` / `FLAG` / `FAIL`. Dave has watched binary automation fail before. A system
that cannot say "I'm not sure, look at this one" pushes its own uncertainty onto
the applicant.

### 4. Matching policy is per field

Dave and Jenny appear to contradict each other: one wants tolerance, the other
demands exactness. They are describing different fields. A single global equality
check fails both of them. See the table in the README.

### 5. Safety is asymmetric, and the code says so

Escalating a compliant label costs an agent a minute. Rejecting one tells an
applicant they broke the law. Those are not the same error and the system never
treats them as equivalent:

- unreadable is not absent
- dropped words are not altered words
- punctuation noise is not altered wording
- a field read below 70% confidence cannot reject
- an image whose brand did not survive the photograph cannot reject anything

The evaluation reports the split alongside accuracy, and its exit code gates on
harmful outcomes. Current result on the container's Tesseract build: 26 of 30
correct, 3 compliant labels referred, 1 defective label referred, **0 outcomes that
harm anyone**.

### 6. Exact on what the regulation fixes, tolerant of what it does not

27 CFR 16.22(b) regulates the case of two words. Rejecting a label because the
body of the statement is set in capitals would be a rejection the regulation
never authorised. So the prefix is compared byte-exact and the body is compared
on wording. Each tolerance in `app/rules/warning.py` names the paragraph that
permits it, and every citation shown to an agent was checked against the
published text of the CFR on 2026-09-21.

### 7. Fixtures are rendered, not collected

The spec *is* the ground truth, so a failed check is unambiguously the extractor's
miss and never an annotation error. It also allows the warning prefix to be drawn
in genuine bold or genuine regular weight, which is the only way to actually test
the typography check.

### 8. Batch is client-orchestrated fan-out, bounded at both ends

Each label is an independent request against the single-label endpoint, so there
is no server-side job state to build, store or expire. The browser runs a bounded
worker pool and the server holds a semaphore of the same size, read from one
setting, so the two agree and a second open tab cannot double the load. A refresh
loses progress, which is acceptable for a prototype that persists nothing, and is
stated plainly.

### 9. The model is a second opinion; every verdict still comes from a rule

Two thirds of the public submissions to this brief put a vision model in charge of
reading the label. Here a model is consulted only after the rules have referred a
label, only for the fields whose doubt came from the image, and its reading is
adopted only where the rules then pass it. A reading that disagrees changes nothing.

That shape answers three things at once. It meets the "AI-Powered" title where a
model helps, on glare and soft focus. It keeps every rejection traceable to OCR text
and a CFR line, which is what an appeal needs. And it bounds the damage a wrong or
manipulated reading can do: the worst case is a referral cleared that OCR could not
read, marked on the row as a second reading for the agent to confirm. The model is
asked for a typed tool call with a fixed schema, so free text cannot come back.

### 10. Triage sees our findings, never the label

A label is artwork the applicant designed. Any text from it that reaches a model
which influences a decision is text the applicant wrote into that model's prompt.
Jev is documented to move under exactly that kind of text: injected "pre-approved"
wording moved a block probability from 0.76 to 0.48 in a published test. So the
state sent to Jev is our own typed output: field names, verdicts, similarity
scores, read confidence and word counts. A test pins that no label text reaches it.
Triage only sorts referrals, it runs only when gateway credentials are set, and a local
heuristic does the same job without one. That heuristic is the baseline: on the
fixtures it ranks genuine referrals above read problems in 75% of pairs.

### 11. A second artwork style, rendered the same way

Every threshold was tuned on one template. The second one (serif, left-aligned, a
wine and two malt beverages, small print under the warning) is rendered from spec
like the first, so its ground truth is exact too. It found four defects in one run,
listed below. New fixtures are rendered with `--new-only`, so adding them never
changes the pixels of the ones already measured.

### 12. Three Tesseract builds, one gate

The same fixtures run on Tesseract 5.4 (Windows), 5.5 (Debian, inside the shipped
container) and 5.3.4 (Ubuntu, in CI). The builds disagree on individual reads, and
the first cross-build run found a false rejection the original build never showed.
CI now runs the full evaluation on every push and fails on any harmful outcome.

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
for regular against 1.33 to 1.48 for bold, much narrower than assumed, because the
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

**The warning block had no end.** It ran until the type size changed, and every
fixture put the warning last, so nothing caught it. A synthetic layout with a web
address under the warning failed the label with "unexpected
'www.oldtomdistillery.com'". The block now closes on the statute's final words,
and text that follows an exact statement flags under 16.22(a) instead of failing
under 16.21.

**Body case was a rejection.** The first rule failed any case-only difference and
blamed the prefix. 16.22(b) regulates the prefix alone; a label with the body in
capitals was compliant and the tool rejected it.

**"Zero harmful" was true on one Tesseract build.** Re-running on Windows with
Tesseract 5.4 read the compressed photo with a stray glyph and two punctuation
changes, and the rule rejected a compliant label. The rule now compares words
before punctuation. The real transcription is pinned in `tests/test_warning_noise.py`
so the next build difference shows up as a test, not a rejection.

**Two settings were dead.** `MAX_BATCH_CONCURRENCY` was documented and never
read; `TESSERACT_CMD` likewise. Both are wired now, and the batch page reads the
limit from the server so they cannot drift.

**The evaluation failed itself.** Its accuracy floor was 0.90 and the measured
figure was 0.864, so the command the README told reviewers to run exited non-zero
on a result the README called a success. It now gates on the metric the whole
design argues for: harmful outcomes, of which there must be none.

**The ABV tolerance question was framed backwards.** I had marked it "must be set
per beverage class". 5.65(c)'s 0.3 points is between the label and the product in
the bottle, a laboratory matter. Between the label and the application there is
no tolerance to set.


**Harm was defined too broadly, then too narrowly.** The first definition counted
a defective label referred to an agent as harm. A referral is the tool handing the
label to a person, which is what the middle verdict is for. But the same pass showed
the definition also missed something: a label that fails for the right reason can
still carry a row that fails for the wrong one, and that row tells an applicant
something false. Harm is now a wrong verdict nobody reviews, or any row failed in
error.

**A two-line brand was read as its first line.** "COPPER RIDGE" over "RESERVE" came
back as "COPPER RIDGE" and failed against "Copper Ridge Reserve". The label also
had the wrong country, so the verdict was right and the evaluation passed it. Lines
in the brand's type size directly above or below it now join the brand.

**A unit read correctly was thrown away.** Tesseract returned "12" at 96% and "FL",
"OZ" at 0%, below the detection floor, so a compliant malt beverage failed for a
missing net contents statement and "12" became the bottler's name. A unit next to a
bare number is now re-attached at its low score, a bare number alone reads as a
half-read volume, and a line without letters is never a name.

**The bold band assumed a mixed-case body.** Capitals are denser than lower case in
any weight, so about 0.2 of the prefix-to-body ratio was case. A bold prefix over a
body set in capitals measured 1.20 and read as regular. Matching cases now use their
own band, measured at 1.08 to 1.20 bold and 0.96 regular.

**A blank image was rotated twelve degrees.** With nothing to measure every angle
tied, and the search kept the first one it tried. It now starts level and moves only
for a strictly better score.

---

## What I would do next

1. **Measure the two model features with credentials.** Both are built to documented
   contracts and tested against mocked responses. The evaluation reports what each
   did as soon as it runs with credentials.
2. **Calibrate the thresholds on real COLA artwork.** Every number here is tuned
   against 30 rendered labels in two styles. The bold bands rest on one regular
   sample each.
3. **Region-of-interest OCR.** A second targeted pass over the warning block at
   higher resolution would likely close the soft-focus gap without a model.
4. **Class and type vocabulary.** Check the designation against subpart I rather
   than against the application's text alone.
5. **Human feedback loop.** Every FLAG an agent resolves is a labelled example;
   that is the dataset nobody has today, and the data triage would learn from.
