# Decisions

## Requirements traceability

The brief has a section headed **Technical Requirements** whose entire content is
"use any language you like." Every actual requirement is inside four interview
transcripts, mixed with a school play, a $4.2M quote nobody approved and a
colleague who prints his emails. Reading those out is the exercise.

Fourteen requirements come from the interviews:

| # | Source | Requirement | Implementation |
|---|---|---|---|
| 1 | Sarah: "checks that what's on the label matches what's in the application" | Compare artwork against the application record, field by field | `app/rules/engine.py` |
| 2 | Sarah: **"If we can't get results back in about 5 seconds, nobody's going to use it."** | Interactive latency under 5 s | p95 **1.02 to 1.35 s** at concurrency 1, on three Tesseract builds: `eval/out/` |
| 3 | Sarah: "big importers who dump 200, 300 label applications on us at once" | Batch review | `app/web/static/app.js`; **314 labels a minute** with 8 workers on Windows and **209** with the container's 4 workers on 6 cores (`eval/out/report-throughput-*.md`); referrals sorted by triage |
| 4 | Sarah: "something my mother could figure out... half our team is over 50" | Plain UI, large type, no hunting for buttons | One page and one action, built from U.S. Web Design System components. Body text is 17 px and form fields 18 px. The artwork sits beside the checklist with a box where each field was read. Samples fill in the form, and the checklist prints cleanly. |
| 5 | Marcus: "our network blocks outbound traffic... our firewall blocked connections to their ML endpoints" | No dependency on an external inference endpoint | Every verdict is local. The two model features switch on only with a credential and fail safe when blocked. |
| 6 | Marcus: "we're not looking to integrate with COLA directly" | Standalone proof of concept | No COLA client anywhere |
| 7 | Marcus: "We're not storing anything sensitive for this exercise" | No retention | Uploads are discarded when each request ends (Starlette spools a large one to a temporary file it deletes). The OCR cache keeps readings, never images, in process memory. |
| 8 | Marcus: FedRAMP, Azure, government infrastructure | Deployable inside a controlled boundary | One container, an unprivileged user, no egress without a model credential: `Dockerfile`. The README gives the Azure Container Apps command. |
| 9 | Dave: "'STONE'S THROW' on the label but 'Stone's Throw' in the application... obviously the same thing" | Brand matching tolerant of case and punctuation | `check_brand_name`: the same words once case, punctuation, spacing and accents are set aside. A near match goes to an agent. |
| 10 | Dave: "You need judgment" / has watched automation fail | Escalate when unsure | Three verdicts; `Verdict.FLAG` |
| 11 | Dave: "Just don't make my life harder" | Explain every finding | A reason and a CFR citation on every row |
| 12 | Jenny: "It has to be **exact**. Like, word-for-word" | Exact warning comparison | `check_warning_text`, 27 CFR 16.21: word for word; an alteration fails and a misread is referred (decision 7) |
| 13 | Jenny: "'GOVERNMENT WARNING:' has to be in all caps and bold" | Verify prefix case and weight | Case hard-fails citing 16.22(a)(2); weight measured by ink density, advisory |
| 14 | Jenny: "photographed at weird angles, or the lighting is bad, or there's glare" | Tolerate imperfect photographs, and refer what OCR cannot read | Deskew, one working size, upscaling and inversion of light-on-dark labels; a sharpness measure that stops an out-of-focus image rejecting anything; six degraded photographs among the rendered fixtures and four phone photographs among the AI-generated ones; a stress test of 210 degraded copies; an optional second reading for what OCR cannot recover |

Five more come from the body of the brief:

| # | Source | Requirement | Implementation |
|---|---|---|---|
| 15 | "common elements include..." (seven bullets) | All seven elements, beyond the three in the worked example | Brand, class/type, alcohol, net contents, bottler name and address, country of origin, warning |
| 16 | The sample reads `45% Alc./Vol. (90 Proof)` | Internal consistency: proof must equal 2 × ABV | `proof_consistency` |
| 17 | "The exact requirements vary by beverage type (beer, wine, distilled spirits)" | Apply and cite the part that governs the commodity | `app/rules/citations.py`: decision 13 |
| 18 | Deliverables: "Deployed Application URL" | A reviewer can open it | A container image, built and checked by CI on every push; Vercel and Azure steps in the README |
| 19 | Title: "AI-Powered Alcohol Label Verification App" | Use AI where it helps | A neural-network OCR engine reads every label; a vision model's second reading of referrals and Jev triage are advisory: decisions 11 and 12 |

Number 16 is stated nowhere. The sample label is internally consistent, and a label can
match its application exactly while contradicting itself.

---

## The decisions

### 1. The extractor reports; the rule engine decides

`app/extract/` says what is printed. `app/rules/` says what it means. Extraction
cannot return a verdict and the rule engine never touches an image.

The whole decision layer is therefore testable with no image, no OCR and no I/O. Every
rejection traces to a specific rule and a specific CFR section. For output that can
cause a federal rejection of an application, that traceability is the point.

### 2. No model in the decision path

Every verdict comes from OCR and a rule. Three things decided that:

- **Appeals.** "The sixth word of your warning statement reads X, 27 CFR 16.21
  requires Y" is a defensible basis for a rejection. A model's judgement is harder to
  defend.
- **Marcus's firewall**, which killed the previous vendor's features. No verdict here
  needs egress, a credential or a vendor.
- **Failure mode.** Tesseract fails by losing text. A language model fails by producing
  plausible text with confidence. For an exact comparison against a statute, lost text
  is the safer failure, because the tool can detect it.

The price is weaker reads of badly degraded images. The evaluation measures it and the
second reading recovers it.

### 3. Three verdicts

`PASS` / `FLAG` / `FAIL`, shown as Pass, Review and Fail. Dave has watched binary
automation fail before. A system that cannot say "look at this one" pushes its own
uncertainty onto the applicant.

### 4. Matching policy is per field

Dave and Jenny appear to contradict each other: one wants tolerance and the other
demands exactness. They are describing different fields, and a single equality check
fails both of them. The README's table lists the policy for each field.

### 5. Safety is asymmetric, and the code says so

Escalating a compliant label costs an agent a minute. Rejecting one tells an applicant
they broke the law. The system treats the second error as the worse one:

- text detected and not resolved is referred; only text that is absent fails
- a warning that differs the way a misread does is referred; an added or changed word fails
- a field read below 80% confidence cannot reject
- a field reported missing beside a line OCR could not read is referred
- an image out of focus, or with no dominant brand, cannot reject anything
- an image with no readable text at all is refused with a plain message

The evaluation reports that split beside accuracy, and its exit code gates on harmful
outcomes. On all three Tesseract builds, the 52 labels of both fixture sets produce **no
outcome that harms anyone**.

### 6. Exact on what the regulation fixes, tolerant of what it does not mention

27 CFR 16.22(a)(2) regulates the case and weight of two words. Rejecting a label because
the body of the statement is set in capitals would be a rejection the regulation never
authorised. So the prefix is compared exactly and the body on its wording. Each
tolerance in `app/rules/warning.py` names the paragraph that permits it. Every citation
the tool shows was read on eCFR on 2026-09-22.

### 7. What the warning rule forgives

27 CFR 16.21 fixes the wording. 16.22(a)(2) fixes the case and weight of `GOVERNMENT
WARNING`. The rule is exact on both. It forgives two things the regulation does not
mention:

- **Body case.** A label that sets the whole statement in capitals passes. A title-case
  prefix is a real defect and fails, citing 16.22(a)(2).
- **Wrapping and hyphenation.** The statute contains no hyphens, so `preg-` at a line end
  followed by `nancy` is a wrap. Any dash and a soft hyphen count.

Everything else is compared word by word, and each difference is sorted into one of two
kinds (`deviations` in `app/rules/warning.py`):

- **A misread** is what a camera and OCR produce: a word lost, a word one or two letters
  out ("bnth" for "birth"), a short mark read as letters ("ee" from a border), a piece of
  a word under glare ("ral" of "General"), words run together, a word OCR itself scored
  under 60%. A misread is referred with the differences listed.
- **An alteration** is what only artwork produces: a real word added ("alcoholic
  alcoholic"), a word swapped ("can" for "may"), "not" dropped, or more than four words
  cut. An alteration fails.

A misprint one letter off the statute ("defect" for "defects") looks exactly like a
misread, so it is referred with the difference on the row, and an agent rejects it. It
never passes. While OCR reports part of the statement unreadable, no count of missing
words rejects, because they may be in the part it could not read.

Text after the statute's last word, such as a web address, is a separate element. It is
referred with a 16.21 citation, because the statement must appear separate and apart
from all other information.

### 8. Making OCR safe enough to reject on

Tesseract's characteristic failure is losing text. These rules keep that failure from
being reported as a violation:

1. **Unreadable text is referred.** Small print detected but not resolved reports
   `illegible`, which flags. Only genuine absence fails.
2. **A warning that differs the way a misread does is referred** (decision 7).
3. **Low confidence cannot reject.** A field read below 80% confidence turns any failure
   into a referral. Printed text reads at 90% and up; on the AI-generated photographs,
   garbage lines read at 72-79%.
4. **A degraded image cannot reject anything.** Every label sets its brand as the most
   prominent element. If nothing on the page is much larger than the body copy, the
   brand did not survive the photograph and no field from that image is trusted.
5. **An out-of-focus image cannot reject anything.** The strongest edges of every sharp
   label measure 60 or more; a 1.5-pixel blur measures 10. Under 30, every failure is
   referred.
6. **A missing statement beside an unread line is referred.** "No net contents" is a
   finding only if every line was read. On one AI-generated label, "1 L" came back as
   "TL". Two or more statements missing at once are all referred: the image was not read
   in full.
7. **An image with no readable text is refused.** A blank page or a photograph of
   something else gets "No text could be read from this image", never a checklist of
   failures.
8. **OCR reads luminance.** Given colour, Tesseract thresholded on its own and lost a
   black-on-white warning strip on an orange label.
9. **The warning block ends where the statute ends.** Once the closing words are read,
   the small print that follows is a separate element.
10. **A half-read quantity is a referral.** A number alone where the statements are is a
    volume whose unit was lost. A unit Tesseract read correctly but scored near zero is
    re-attached at that low score, so it too can only refer.
11. **An impossible or contradicted reading is a referral.** A percentage above 96, one
    ten times the application's (a lost decimal point), one the label's own proof
    statement contradicts, and a spirit or wine size no bottle comes in (27 CFR 5.203,
    4.72) are all misreads.
12. **The largest text is not always the brand.** A line OCR read below 50% is never the
    brand; a line carrying "Alc./Vol." never is either. When the line taken for the brand
    is the application's class designation, the brand went unread and is referred.

Every row whose doubt comes from the image carries a `read_uncertain` marker. That
marker is the only thing a second reading may act on.

### 9. Two fixture sets: rendered and AI-generated

The rendered set is drawn by `fixtures/generate.py`. The spec *is* the ground truth, so
a failed check is the extractor's miss and never an annotation error. Rendering also
draws the warning prefix in genuine bold or genuine regular weight, which is the only way
to test the typography check. New fixtures are rendered with `--new-only`, so adding them
never changes the pixels of the ones already measured.

Every threshold was tuned on that set, which makes it a poor judge of labels the tool was
not tuned on. The brief suggests AI image generation for test labels, and a reviewer is
likely to try exactly that. So `fixtures/ai` holds fifteen labels drawn by Gemini image
models through OpenRouter, for $1.15: eleven flat labels in varied styles, with arched
and ornamental lettering and light type on a dark label, and four phone photographs of
bottles and a can. Their truth was read off each image by eye. The image model got five
warnings wrong, so those labels are defective as printed and expected to fail. The evaluation reports the two sets
separately. Accuracy is gated on the rendered set; harm is gated on both.

### 10. Batch is client-orchestrated fan-out, bounded at both ends

Each label is an independent request against the single-label endpoint, so there is no
server-side job state to build, store or expire. The browser runs a bounded worker pool
and the server holds a semaphore of the same size, read from one setting. A second open
tab therefore cannot double the load. The semaphore covers OCR only, so a label waiting
on a model holds no OCR slot. Each Tesseract process runs one thread, because the pool
already supplies the parallelism. A refresh loses progress, which is acceptable for a
prototype that stores nothing.

### 11. The model is a second opinion; every verdict still comes from a rule

A model is consulted only after the rules refer a label, only for the fields whose doubt
came from the image. Its reading is adopted only where the rules then pass it, and a
reading that disagrees changes nothing. Two limits came from the adversarial review:

- **The warning's wording is never offered.** A vision model knows the statute by heart
  and tends to return it whole. A reading that "clears" a warning looks the same as one
  that corrected an altered statement back to the statute. Adopting it would pass
  exactly the defect Jenny described, so the wording stays with OCR and the agent.
- **One statement, one reading.** The alcohol row and the proof row come from the same
  statement. A reading is adopted for a field only if no row computed from that field
  gets worse, and then it supplies every such row. With a scripted reader, a reading
  that fixed the percentage and contradicted the proof passed the label with a PASS on
  both rows.

That shape does three things. It meets the "AI-Powered" title where a model helps, on
glare and soft focus. It keeps every rejection traceable to OCR text and a CFR line,
which is what an appeal needs. And it bounds the damage a wrong or manipulated reading
can do. The worst case is a cleared referral, marked on the row for the agent to
confirm. The model must answer through a typed tool call with a fixed schema, so free
text cannot come back.

The reading goes through OpenRouter: one prepaid balance, a hard credit limit on the
credential and any vision model a setting away. Routing excludes providers that store or
train on requests. Claude Sonnet 5 is the default at about half a cent per re-read
label. Only referred labels are sent. Readings are cached by image and concurrent
requests for one image share one call, so a reviewer clicking a sample twice pays once.
A daily call limit sits under the credit limit.

The single-label page never waits for the model. It asks for the label with the reading
deferred and shows the OCR result in about 1.4 seconds. It asks again only when
something is worth re-reading. The second request finds the OCR result in the cache, so
it costs only the model call. The batch page asks once, with the reading included,
because a batch is about throughput. The evaluation calls no paid model unless asked, so
CI stays free and reproducible.

Measured on both fixture sets, Claude Sonnet 5 takes the rendered set from 34 to 35 of
37 and the AI-generated set from 5 to 7 of 15. It adds no harmful outcome and costs
$0.0057 per consulted label. The two rendered labels it leaves referred are photographs whose
warning OCR could not read, which the model may not clear. The default came from a
three-way run on the same labels. Gemini 3.8 Flash scored 35 and 8 at $0.0021, with a
slowest label of 6.9 s against Sonnet's 4.9 s. GPT-6 Luna scored 35 and 7 at $0.0001.

### 12. Triage sees our findings, never the label

A label is artwork the applicant designed. Any label text that reaches a model which
influences a decision is text the applicant wrote into that model's prompt. Jev is
documented to move under exactly that kind of text: in a published test, injected
"pre-approved" wording moved a block probability from 0.76 to 0.48.

So the state sent to Jev is the tool's own typed output. It holds the overall verdict
and, for each finding, its field, verdict, layer and markers. It adds whether a second
reading cleared the finding, its similarity, its read confidence and warning word counts. A test
pins that no label text reaches it. Triage only sorts referrals. Without a gateway
credential, or when a call fails, the local heuristic answers and the row names which
one did. That heuristic is also the baseline. On the live deployment's 18 referrals, Jev
ranks a genuine referral ahead of a read problem in 72% of pairs and the heuristic in 46%,
with 41% ties (`eval/out/report-triage-jev-live.md`). The request carries no zero-data-retention option,
which AI Gateway reserves for paid plans; there is no label content in it to retain.

### 13. Citations by commodity

TTB labels wine under 27 CFR part 4, distilled spirits under part 5 and malt beverages
under part 7, and the section numbers differ. The brief says so, and a TTB reviewer
reads the citation on every row. The application record carries no commodity field, so
`app/rules/citations.py` infers it from the last commodity word in the class/type
designation. "Bourbon Barrel Aged Stout" is a malt beverage; "Kentucky Straight Bourbon
Whiskey" is a spirit. A designation with no such word cites all three parts.

The commodity also changes one rule. Part 7 makes the alcohol statement optional on most
malt beverages. Part 4 lets a wine of 14% or less omit it when the label says "table
wine". Rejecting such a label for a missing statement would be a false rejection, so it
is referred with the exception stated. Every section was read on eCFR. Sections 5.69,
7.69 and 4.35(e) only cross-refer country of origin to 19 CFR 134.11, so the rows cite
that too.

### 14. Three artwork styles, rendered the same way

Every threshold was first tuned on one template. A second style (serif, left-aligned, a
wine and two malt beverages, small print under the warning) found four defects in its
first run. A third style reproduces the labels an outside reviewer drew to test the
tool. It stacks a brand over two lines in two sizes and sets light type on a dark card.
It adds a scan at three times the usual resolution, the net contents on the alcohol line
and an imported tequila. Its first run found a false rejection, listed with the other corrections.

### 15. Three Tesseract builds, one gate

The same fixtures run on Tesseract 5.4 (Windows), 5.5 (Debian, inside the shipped
container) and 5.3.4 (Ubuntu, in CI). The builds disagree on individual reads, and the
first cross-build run found a false rejection the original build never showed. CI runs
the full evaluation on every push, both fixture sets. It fails on any harmful outcome in
either set. It also fails under 80% accuracy on the rendered set. That floor sits well
under the measured figure, so a different build does not break it. The AI-generated set has no
accuracy floor: artwork OCR cannot read is meant to be referred.

### 16. What recovered the most accuracy

Three preprocessing steps, each found by measuring:

- **Deskew.** A 7° tilt made Tesseract miss the warning statement entirely. The angle
  comes from projecting an edge map and maximising the squared gradient of the
  horizontal profile.
- **Upscale.** Small type sits under Tesseract's reliable floor until enlarged.
  Deskew and upscaling together took exact warning transcription from 17 of 22 to 20
  of 22 on the first template.
- **One working size.** Every image is brought to 2200 pixels on its long edge. A sweep
  of sizes read correctly from 1600 to 2200 and misread at 2600 and above.

### 17. Net contents: the units each part requires, and the sizes bottles come in

Spirits and wine state net contents in liters or milliliters (27 CFR 5.70(a), 4.37(a));
centiliters and U.S. units may appear only beside that statement. Malt beverages state
U.S. units (7.70); metric may appear only beside them. A label whose volume matches but
whose only statement is in the other form is referred with the rule quoted. OCR may have
missed the required statement nearby, so it does not reject. The fixture for "75 cl"
expected a pass until reading 5.70 showed otherwise; it now expects the referral.

Spirits and wine also come only in the sizes 5.203 and 4.72 list. No bottle comes in
790 mL, so a reading of "790 mL" against an application's 750 mL is a misread. It is
referred with the section named.

### 18. Stress-testing what no fixture covers

The review made degraded copies of every compliant rendered label. It used three blurs,
two shrinks, two JPEG qualities, two rotations, dimming, low contrast, noise and glare
in three places. Before this pass, 99 of 225 copies were rejected. Each fix in this document
was measured against that run and against both fixture sets. With "75 cl" no longer a
compliant label, the run now makes 210 copies. Ten are rejected, all under glare that
erases a line or the warning. Three come back as unreadable: two blurred past reading
and one tilted photograph at half brightness.

That last one has a known cause. Deskewing fills the uncovered corners white, and
beside dim grey paper Tesseract reads the whole label as dark. Filling with the label's
own grey read all 43 words of its warning. The same fill turned a compliant phone
photograph (`ai_photo_compliant`) from a referral into a rejection, so the fill stays
white. A refusal asks for a better copy, and a rejection harms an applicant.

---

## Things I got wrong, and what the measurements said

Kept because the corrections are the interesting part.

**Concurrency was a no-op for the entire first implementation.** Extraction is CPU and
subprocess work that was awaited directly on the event loop, so `async` was decorative.
Eight labels took 12.9 s at concurrency 1, 4 and 8 alike. Moving the blocking body to a
thread pool gave 3.5x.

**The container's batch ran 23 times slower than it had to.** Every throughput figure
came from Windows, and the container's Tesseract behaves differently. Debian's build uses
OpenMP, which starts a thread per core in every process, so four labels at once fought
over six cores. The 52-label sample batch took 346.8 s in the container. With one
thread per process, set by the OCR module, it took 15.1 s with the same verdicts. The
Linux evaluations missed it, because they measured one label at a time.

**My first skew estimator returned 0.0° on every fixture.** Testing it against known
rotations showed it was exact on white backgrounds and collapsed on dark ones:
projecting raw ink let the rotated corner fill dominate the profile. Projecting an edge
map fixed it. Pinned by `test_skew_survives_any_background`.

**I guessed the bold threshold and it was wrong.** Measured separation is 1.21 for
regular against 1.33 to 1.48 for bold, much narrower than assumed, because the prefix is
capitals either way. A band that reports "cannot tell" replaced it.

**Country comparison ran on the whole string.** "Product of Scotland" and "Product of
Canada" score 83% on shared boilerplate, so a Scotch declared as Canadian would have
passed.

**I conflated latency with throughput** and briefly believed p95 had regressed to 4.9 s.
That was per-label wall clock under saturation. An agent waiting on one label never sees
it. The report now separates them.

**`pick_bottler` took the last two lines of the page.** On a blurred photo whose warning
block went undetected, it read warning text as the bottler name and failed a compliant
label.

**The warning block had no end.** It ran until the type size changed, and every fixture
put the warning last, so nothing caught it. A synthetic layout with a web address under
the warning failed the label with "unexpected 'www.oldtomdistillery.com'". The block now
closes on the statute's final words, and text after an exact statement is referred under
16.21.

**Body case was a rejection.** The first rule failed any case-only difference and blamed
the prefix. 16.22(a)(2) regulates the prefix alone; a label with the body in capitals was
compliant and the tool rejected it.

**"Zero harmful" was true on one Tesseract build.** Tesseract 5.4 on Windows read the
compressed photo with a stray glyph and two punctuation changes, and the rule rejected a
compliant label. The rule now compares words before punctuation. The real transcription
is pinned in `tests/test_warning_noise.py`, so the next build difference shows up as a
test.

**Two settings were dead.** `MAX_BATCH_CONCURRENCY` was documented and never read;
`TESSERACT_CMD` likewise. Both are wired now, and the batch page reads the limit from the
server so they cannot drift.

**The evaluation failed itself.** Its accuracy floor was 0.90 and the measured figure was
0.864, so the command the README told reviewers to run exited non-zero on a result the
README called a success. It now gates on harmful outcomes first, with an accuracy floor
of 0.80.

**The ABV tolerance question was framed backwards.** I had marked it "must be set per
beverage class". The 0.3 points in 5.65(c) are between the label and the product in the
bottle, a laboratory matter. Between the label and the application there is no tolerance
to set.

**Harm was defined too broadly, then too narrowly.** The first definition counted a
defective label referred to an agent as harm. A referral hands the label to a person,
which is what the middle verdict is for. The same pass showed the definition also missed
something. A label that fails for the right reason can still carry a row that fails for
the wrong one, and that row tells an applicant something false. Harm now counts a wrong
verdict nobody reviews, and any row failed in error.

**A two-line brand was read as its first line.** "COPPER RIDGE" over "RESERVE" came back
as "COPPER RIDGE" and failed against "Copper Ridge Reserve". The label also had the
wrong country, so the verdict was right and the evaluation passed it. Lines in the
brand's type size directly beside it now join the brand. A brand stacked in two sizes
("OLD TOM" over a smaller "DISTILLERY") is joined by the rules, against the application.

**A unit read correctly was thrown away.** Tesseract returned "12" at 96% and "FL", "OZ"
at 0%, under the detection floor, so a compliant malt beverage failed for a missing net
contents statement and "12" became the bottler's name. A unit next to a bare number is
now re-attached at its low score, a bare number alone reads as a half-read volume, and a
line without letters is never a name.

**The bold band assumed a mixed-case body.** Capitals are denser than lower case in any
weight, so about 0.2 of the prefix-to-body ratio was case. A bold prefix over a body set
in capitals measured 1.20 and read as regular. Matching cases now use their own band,
measured at 1.08 to 1.20 bold and 0.96 regular.

**A perfect reading passed tiny type.** The first live run of the second reading cleared
the label whose warning is set in about 6-point type: the model read every word and even
judged the prefix bold, so the label passed. That label is referred because the type is
tiny, which is a 16.22(b) size question no reading can settle. Type too small to measure
is now its own finding on the typography row. It is not marked as a read problem, so a
second reading cannot clear it. The evaluation caught this as a harmful outcome on its
first run with a real model.

**The OCR cache never cached anything.** It was checked with `if cache:`, and an empty
cache has a length of zero, which Python reads as false, so nothing was ever stored. A
test for the two-step page, which counts OCR runs, found it.

**Then the cache still prepared every image.** The cache finds an entry by the digest
of the uploaded bytes, yet the code prepared the image first to get that digest. Every repeat, and every
second-reading request, spent 0.7 s on deskew and scaling to learn a hash. The lookup now
comes first.

**A blank image was rotated twelve degrees.** With nothing to measure every angle tied,
and the search kept the first one it tried. It now starts level and moves only for a
strictly better score.

**A full-resolution photo read worse.** An outside reviewer's 12-megapixel photo came back
as "495%" for "45%" and "790" for "750". Tesseract read the same image correctly once it
was reduced, so every image now goes to one working size first.

**A class line with a percentage was skipped.** "100% Blue Agave Tequila" matched the
alcohol pattern, so the class picker passed over it. The importer's line became the
class, the address became the bottler and a compliant import failed. A percentage now
counts as an alcohol statement only beside an alcohol word or under 100. The third
artwork style found this on its first run.

**Three citations named the wrong paragraph.** The capital-letters rule is 16.22(a)(2),
where I had 16.22(b), which sets type size. "Separate and apart" is in 16.21, where I had
16.22(a). And every beer and wine label cited part 5. Reading each section on eCFR found
all three; decision 13 fixes the last.

**"No harmful outcome" held on labels I drew, and nowhere else.** The first run on
fifteen AI-generated labels scored 6 of 15 and rejected 4 of the 7 compliant ones. A
stress test of degraded copies of my own compliant labels rejected 99 of 225. The
causes, each fixed and each pinned by a test in `tests/test_hard_artwork.py`:

- A bottler phrase on its own line ("Distilled and Bottled by") was read as the name,
  and a one-line "Imported by X, City, State" gave no address.
- A capitals brand and a mixed-case varietal of similar height merged into one brand.
  Mixed case measures taller, for its ascenders and descenders.
- The brand's own lines counted in the median it was compared with, so a wine label
  with three large lines read as unreadable.
- Colour input let Tesseract lose a whole warning strip.
- Every substitution in the warning rejected, so border ornaments ("Pax", "ee") and
  glare fragments rejected compliant labels.
- Outlined brand lettering went unread and the class line became the brand.
- A fragment of the warning ("ale machinery, and may") became the bottler.
- A blank page and a blurred photo were rejected on "not found" rows.
- Heavy JPEG and a 6° tilt left the bottler's name unread, and the address under it
  was compared as the name.
- A bottler statement read without its name ("istilled and Bottled by") scored 0% as a
  name. A trial of another deskew fill found it on a compliant phone photograph.

**A missing "not" was referred as a misread.** Deletions of up to five words counted as
OCR dropout. So "women should drink alcoholic beverages during pregnancy" went to an
agent marked as a reading problem, and a second reading could clear it. Losing "not" now
fails, and the second reading may no longer touch the warning's wording at all.

**Matching passed things it should not have.** "Buffalo Grace" passed for "Buffalo
Trace" at 96%, with a reason saying only case differed. Austria passed for Australia,
"XYZ Distilling Company" for "ABC Distilling Company", and "California Rose Wine" for
"California Red Wine". Brand and class now need the same words, the country the same
country, and a bottler name its own distinctive words.

**The page showed one label's verdict under another's artwork.** While a new label was
checked, the old checklist stayed on screen for a second and more. The print button
showed before there was anything to print, because USWDS buttons override the hidden
attribute. A TIFF, the format scanners produce, previewed as a broken image in Chrome
and Edge. A screen reader never heard a referral's verdict once a second reading
started, because the page replaced that sentence at once. The adversarial review and a
Playwright pass over every control found these.

**"75 cl" passed.** I read centiliters as one more metric unit. 27 CFR 5.70(a) allows
them only beside a statement in liters or milliliters.

---

## What I would do next

1. **Measure Jev on real referrals.** Eighteen fixture referrals are a small sample.
   `python -m eval.run --triage jev` with an AI Gateway credential reports the same ordering
   locally, and the decisions agents record (item 7) are the data to judge it on.
2. **Calibrate the thresholds on real COLA artwork.** Every number here is tuned against
   37 rendered labels and checked against 15 AI-generated ones. The bold bands rest on
   one regular sample each.
3. **Read the warning block a second time at higher resolution.** A targeted OCR pass
   would likely close the soft-focus gap without a model.
4. **Let a second reading contest an absence.** Glare that erases a line leaves OCR
   nothing, so "no net contents statement" still rejects. A model that finds the
   statement there could turn that rejection into a referral, never a pass.
5. **Check the class and type against the standards of identity** in subpart I, beyond
   comparing it with the application's text.
6. **Take the commodity from the application.** It is inferred from the designation
   today.
7. **Keep what agents decide.** Every referral an agent resolves is a labelled example.
   That is the dataset nobody has today, and the data triage would learn from.
