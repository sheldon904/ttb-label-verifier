# Decisions

## Requirements traceability

The brief's **Technical Requirements** section leaves the stack open and says what it
judges: "We want to see what kind of engineering, design, and integration decisions you
make." Most requirements sit inside four interview transcripts, mixed with a school play,
a $4.2M quote nobody approved and a colleague who prints his emails. Reading those out
is the exercise.

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
| 10 | Dave: "You need judgment"; he watched automation fail before | Escalate when unsure | Three verdicts; `Verdict.FLAG` |
| 11 | Dave: "Just don't make my life harder" | Explain every finding | A reason and a CFR citation on every row |
| 12 | Jenny: "It has to be **exact**. Like, word-for-word" | Exact warning comparison | `check_warning_text`, 27 CFR 16.21: word for word; an alteration fails and a misread is referred (decision 6) |
| 13 | Jenny: "'GOVERNMENT WARNING:' has to be in all caps and bold" | Verify prefix case and weight | Case fails citing 16.22(a)(2); weight measured by ink density, advisory |
| 14 | Jenny: "photographed at weird angles, or the lighting is bad, or there's glare" | Tolerate imperfect photographs, and refer what OCR cannot read | Deskew, one working size, upscaling and inversion of light-on-dark labels; a sharpness measure that stops an out-of-focus image rejecting anything; degraded photographs in both fixture sets; a stress test of 210 degraded copies; an optional second reading for what OCR cannot recover |

Five more come from the body of the brief:

| # | Source | Requirement | Implementation |
|---|---|---|---|
| 15 | "common elements include..." (seven bullets) | All seven elements, beyond the three in the worked example | Brand, class/type, alcohol, net contents, bottler name and address, country of origin, warning |
| 16 | The sample reads `45% Alc./Vol. (90 Proof)` | Internal consistency: proof must equal 2 × ABV | `proof_consistency` |
| 17 | "The exact requirements vary by beverage type (beer, wine, distilled spirits)" | Apply and cite the part that governs the commodity | `app/rules/citations.py`: decision 12 |
| 18 | Deliverables: "Deployed Application URL" | A reviewer can open it | Live on Vercel, built from the Dockerfile CI tests; Azure steps in the README |
| 19 | Title: "AI-Powered Alcohol Label Verification App" | Use AI where it helps | A neural-network OCR engine reads every label; a vision model's second reading of referrals and Jev triage are advisory: decisions 10 and 11 |

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
- **Marcus's firewall**, which broke half the previous vendor's features. No verdict
  here needs egress, a credential or a vendor.
- **Failure mode.** Tesseract fails by losing text. A language model fails by producing
  plausible text with confidence. For an exact comparison against a statute, lost text
  is the safer failure, because the tool can detect it.

The price is weaker reads of badly degraded images. The evaluation measures it and the
second reading recovers part of it.

### 3. Three verdicts

`PASS` / `FLAG` / `FAIL`, shown as Pass, Review and Fail. Dave watched automation fail
before: a phone system meant to cut calls brought more. A system that cannot say "look at
this one" pushes its own uncertainty onto the applicant.

### 4. Matching policy is per field

Dave and Jenny appear to contradict each other: one wants tolerance and the other
demands exactness. They describe different fields, and a single equality check fails
both of them. The README's table lists the policy for each field.

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

### 6. The warning: exact where the regulation is exact

27 CFR 16.21 fixes the wording, and 16.22(a)(2) fixes the case and weight of `GOVERNMENT
WARNING`. The rule is exact on both. It forgives two things the regulation does not
mention, and each tolerance in `app/rules/warning.py` names the paragraph that permits it:

- **Body case.** A label that sets the whole statement in capitals passes. A title-case
  prefix is a real defect and fails, citing 16.22(a)(2).
- **Wrapping and hyphenation.** The statute contains no hyphens, so `preg-` at a line end
  followed by `nancy` is a wrap. Any dash and a soft hyphen count.

The rule compares everything else word by word and sorts each difference into one of two
kinds (`deviations` in `app/rules/warning.py`):

- **A misread** is what a camera and OCR produce: a word lost, a word one or two letters
  out ("bnth" for "birth"), a short mark read as letters ("ee" from a border), a piece of
  a word under glare ("ral" of "General"), words run together, a word OCR itself scored
  under 60%. A misread is referred with the differences listed.
- **An alteration** is what only artwork produces. It is a real word added ("alcoholic
  alcoholic"), a word swapped ("can" for "may"), "not" dropped or more than four words
  cut. An alteration fails.

A misprint one letter off the statute ("defect" for "defects") looks exactly like a
misread. The rule refers it with the difference on the row, and an agent rejects it. It
never passes. While OCR reports part of the statement unreadable, no count of missing
words rejects, because they may be in the part it could not read.

Text after the statute's last word, such as a web address, is a separate element. It is
referred with a 16.21 citation, because the statement must appear separate and apart
from all other information. Every citation the tool shows was read on eCFR on 2026-09-22.

### 7. Making OCR safe enough to reject on

Tesseract's characteristic failure is losing text. These rules keep that failure from
being reported as a violation:

1. **Unreadable text is referred.** Small print detected but not resolved reports
   `illegible`, which flags. Only genuine absence fails.
2. **A warning that differs the way a misread does is referred** (decision 6).
3. **Low confidence cannot reject.** A field read below 80% confidence turns any failure
   into a referral. Printed text reads at 90% and up; on the AI-generated photographs,
   garbage lines read at 72-79%.
4. **A degraded image cannot reject anything.** Every label sets its brand as the most
   prominent element. If nothing on the page is much larger than the body copy, the
   brand did not survive the photograph. The rules then trust no field from that image.
5. **An out-of-focus image cannot reject anything.** The strongest edges of every sharp
   label measure 60 or more; a 1.5-pixel blur measures 10. Under 30, every failure is
   referred.
6. **A missing statement beside an unread line is referred.** "No net contents" is a
   finding only if every line was read. On one AI-generated label, "1 L" came back as
   "TL". Two or more statements missing at once are all referred: the image was not read
   in full.
7. **An image with no readable text is refused.** A blank page or a photograph of
   something else gets one message: "No text could be read from this image".
8. **OCR reads luminance.** Given colour, Tesseract thresholded on its own and lost a
   black-on-white warning strip on an orange label.
9. **The warning block ends where the statute ends.** Once the closing words are read,
   the small print that follows is a separate element.
10. **A half-read quantity is a referral.** A number alone where the statements are is a
    volume whose unit was lost. A unit Tesseract read correctly but scored near zero is
    re-attached at that low score, so it too can only refer.
11. **An impossible or contradicted reading is a referral.** The rules treat these as
    misreads:
    - a percentage above 96
    - a percentage ten times the application's (a lost decimal point)
    - a percentage the label's own proof statement contradicts
    - a spirit or wine size no bottle comes in (27 CFR 5.203, 4.72)
12. **The largest text is not always the brand.** A line OCR read below 50% is never the
    brand; a line carrying "Alc./Vol." never is either. When the line taken for the brand
    is the application's class designation, the brand went unread and is referred.

Every row whose doubt comes from the image carries a `read_uncertain` marker. That
marker is the only thing a second reading may act on.

### 8. Two fixture sets, three artwork styles

The rendered set is drawn by `fixtures/generate.py`. The spec *is* the ground truth, so
a failed check is the extractor's miss and never an annotation error. Rendering also
draws the warning prefix in genuine bold or genuine regular weight, which is the only way
to test the typography check. New fixtures are rendered with `--new-only`, so adding them
never changes the pixels of the ones already measured.

The set uses three artwork styles, and each new style found defects on its first run. A
serif, left-aligned style with a wine and two malt beverages found four. The third
reproduces labels a review pass drew to break the tool. They stack a brand in two sizes,
set light type on a dark card and include a scan at three times the usual resolution.
Its first run found a false rejection on an imported tequila.

Every threshold was tuned on that set, which makes it a poor judge of labels the tool was
not tuned on. The brief suggests AI image generation for test labels, and a reviewer is
likely to try exactly that. So `fixtures/ai` holds fifteen labels drawn by Gemini image
models through OpenRouter, for $1.15. Eleven are flat labels, some with arched or
ornamental lettering, and four are phone photographs of bottles and a can. Their truth
was read off each image by eye. The image model got five warnings wrong, so those labels
are defective as printed and expected to fail.

The evaluation reports the two sets separately. Accuracy is gated on the rendered set;
harm is gated on both.

### 9. Batch is client-orchestrated fan-out, bounded at both ends

Each label is an independent request against the single-label endpoint, so there is no
server-side job state to build, store or expire. The browser runs a bounded worker pool
and the server holds a semaphore of the same size, read from one setting. A second open
tab therefore cannot double the load. The semaphore covers OCR only, so a label waiting
on a model holds no OCR slot. Each Tesseract process runs one thread, because the pool
already supplies the parallelism. A refresh loses progress, which is acceptable for a
prototype that stores nothing.

### 10. The model is a second opinion; every verdict still comes from a rule

A model is consulted only after the rules refer a label, only for the fields whose doubt
came from the image. Its reading is adopted only where the rules then pass it, and a
reading that disagrees changes nothing. Two limits came from a review pass that tried to
break it:

- **The warning's wording is never offered.** A vision model knows the statute by heart
  and tends to return it whole. A reading that "clears" a warning looks the same as one
  that corrected an altered statement back to the statute. Adopting it would pass
  exactly the defect Jenny described, so the wording stays with OCR and the agent.
- **One statement, one reading.** The alcohol row and the proof row come from the same
  statement. A reading is adopted for a field only if no row computed from that field
  gets worse, and then it supplies every such row. In a test with a stand-in reader, a
  reading that fixed the percentage and contradicted the proof passed both rows.

That shape meets the "AI-Powered" title where a model helps, on glare and soft focus. It
keeps every rejection traceable to OCR text and a CFR line, which is what an appeal needs.
It also bounds the damage a wrong or manipulated reading can do. The worst case is a
cleared referral, marked on the row for the agent to confirm. The model answers through a
typed tool call with a fixed schema, so free text cannot come back.

The reading goes through OpenRouter, with a hard credit limit on the credential and any
vision model a setting away. Routing excludes providers that store or train on requests.
Only referred labels are sent. Readings are cached by image, and a daily call limit sits
under the credit limit. The single-label page shows the OCR result at once and updates
when the reading lands. The evaluation calls no paid model unless asked, so CI stays free.

Claude Sonnet 5 takes the rendered set from 34 to 35 of 37 and the AI-generated set from
5 to 7 of 15. It adds no harmful outcome and costs
$0.0057 per consulted label. The two rendered labels it leaves referred are photographs
whose warning OCR could not read, which the model may not clear. The default came from a
three-way run on the same labels. Gemini 3.8 Flash scored 35 and 8 at $0.0021, with a
slowest label of 6.9 s against Sonnet's 4.9 s. GPT-6 Luna scored 35 and 7 at $0.0001.

### 11. Triage sees our findings, never the label

A label is artwork the applicant designed. Any label text that reaches a model which
influences a decision is text the applicant wrote into that model's prompt. Jev's own
documentation shows it moving under exactly that kind of text. In a published test,
injected "pre-approved" wording moved a block probability from 0.76 to 0.48.

So the state sent to Jev is the tool's own typed output. It holds the overall verdict
and, for each finding, its field, verdict, layer and markers. It adds whether a second
reading cleared the finding, its similarity, its read confidence and warning word counts.
A test pins that no label text reaches it. Triage only sorts referrals. Without a gateway
credential, or when a call fails, the local heuristic answers and the row names which one
did.

The heuristic is also the baseline. On the live deployment's 18 referrals, Jev ranks a
genuine referral ahead of a read problem in 72% of pairs. The heuristic does so in 46%,
with 41% ties (`eval/out/report-triage-jev-live.md`). The request carries no
zero-data-retention option, which AI Gateway reserves for paid plans; there is no label
content in it to retain.

### 12. Citations by commodity

TTB labels wine under 27 CFR part 4, distilled spirits under part 5 and malt beverages
under part 7, and the section numbers differ. The brief says so, and a TTB reviewer
reads the citation on every row. The application record carries no commodity field, so
`app/rules/citations.py` infers it from the last commodity word in the class/type
designation. "Bourbon Barrel Aged Stout" is a malt beverage; "Kentucky Straight Bourbon
Whiskey" is a spirit. A designation with no such word cites all three parts.

The commodity also changes one rule. Part 7 makes the alcohol statement optional on most
malt beverages. Part 4 lets a wine of 14% or less omit it when the label says "table
wine". Rejecting such a label for a missing statement would be a false rejection, so it
is referred with the exception stated. Sections 5.69, 7.69 and 4.35(e) only cross-refer
country of origin to 19 CFR 134.11, so the rows cite that too.

### 13. Three Tesseract builds, one gate

The same fixtures run on Tesseract 5.4 (Windows), 5.5 (Debian, inside the shipped
container) and 5.3.4 (Ubuntu, in CI). The builds disagree on individual reads, and the
first cross-build run found a false rejection the original build never showed. CI runs
the full evaluation on every push, both fixture sets. It fails on any harmful outcome in
either set, and under 80% accuracy on the rendered set. That floor sits well under the
measured figure, so a different build does not break it. The AI-generated set has no
accuracy floor: artwork OCR cannot read is meant to be referred.

### 14. What recovered the most accuracy

Three preprocessing steps, each found by measuring:

- **Deskew.** A 7° tilt made Tesseract miss the warning statement entirely. The angle
  comes from projecting an edge map and maximising the squared gradient of the
  horizontal profile.
- **Upscale.** Small type sits under Tesseract's reliable floor until enlarged.
  Deskew and upscaling together took exact warning transcription from 17 of 22 to 20
  of 22 on the first template.
- **One working size.** Every image is brought to 2200 pixels on its long edge. A
  12-megapixel photo read "495%" for "45%" and "790" for "750" at full size. A sweep of
  sizes read correctly from 1600 to 2200 and misread at 2600 and above.

### 15. Net contents: the units each part requires, and the sizes bottles come in

Spirits and wine state net contents in liters or milliliters (27 CFR 5.70(a), 4.37(a));
centiliters and U.S. units may appear only beside that statement. Malt beverages state
U.S. units (7.70); metric may appear only beside them. A label whose volume matches but
whose only statement is in the other form is referred with the rule quoted. OCR may have
missed the required statement nearby, so it does not reject. The fixture for "75 cl"
expected a pass until reading 5.70 showed otherwise; it now expects the referral.

Spirits and wine also come only in the sizes 5.203 and 4.72 list. No bottle comes in
790 mL, so a reading of "790 mL" against an application's 750 mL is a misread. It is
referred with the section named.

### 16. Stress-testing what no fixture covers

A review pass wrote the stress test, now `eval/stress.py` (`make stress`). It makes
degraded copies of every compliant rendered label. It uses three blurs, two shrinks, two
JPEG qualities, two rotations, dimming, low contrast, noise and glare in three places.
Its first run rejected 99 of 225 copies. Each fix in this document was measured against
that run and against both fixture sets. With "75 cl" no longer a
compliant label, the run now makes 210 copies. Ten are rejected, all under glare that
erases a line or the warning.

Three more come back as unreadable: two blurred past reading and one tilted photograph at
half brightness. Deskewing fills the uncovered corners white, and beside dim grey paper
Tesseract reads the whole label as dark. Filling with the label's own grey read all 43
words of its warning. The same fill turned a compliant phone photograph
(`ai_photo_compliant`) from a referral into a rejection, so the fill stays white. A
refusal asks for a better copy, and a rejection harms an applicant.

---

## What testing corrected

A selection. The commit history holds the rest.

**Concurrency was a no-op in the first implementation.** Extraction is CPU and
subprocess work that was awaited directly on the event loop, so `async` was decorative.
Eight labels took 12.9 s at concurrency 1, 4 and 8 alike. Moving the blocking body to a
thread pool gave 3.5x.

**The container's batch ran 23 times slower than it had to.** Every throughput figure
came from Windows, and the container's Tesseract behaves differently. Debian's build uses
OpenMP, which starts a thread per core in every process, so four labels at once fought
over six cores. The 52-label sample batch took 346.8 s in the container. With one
thread per process, set by the OCR module, it took 15.1 s with the same verdicts.

**"Zero harmful" was true on one Tesseract build.** Tesseract 5.4 on Windows read the
compressed photo with a stray glyph and two punctuation changes, and the rule rejected a
compliant label. The rule now compares words before punctuation. The real transcription
is pinned in `tests/test_warning_noise.py`, so the next build difference shows up as a
test.

**The evaluation failed itself.** Its accuracy floor was 0.90 and the measured figure was
0.864. So the command the README told reviewers to run exited non-zero on a result the
README called a success. It now gates on harmful outcomes first, with an accuracy floor
of 0.80.

**Harm was defined too broadly, then too narrowly.** The first definition counted a
defective label referred to an agent as harm. A referral hands the label to a person,
which is what the middle verdict is for. The definition also missed a case: a label that
fails for the right reason can still carry a row that fails for the wrong one. That row
tells an applicant something false. Harm now counts a wrong verdict nobody reviews, and
any row failed in error.

**A perfect reading passed tiny type.** The first live run of the second reading cleared
the label whose warning is set in about 6-point type. The model read every word and
judged the prefix bold. That label is referred because the type is tiny, which is a
16.22(b) size question no reading can settle. Type too small to measure is now its own
finding, and a second reading cannot clear it. The evaluation caught this as a harmful
outcome on its first run with a real model.

**"No harmful outcome" held on labels I drew, and nowhere else.** The first run on
fifteen AI-generated labels scored 6 of 15 and rejected 4 of the 7 compliant ones. The
stress test rejected 99 of 225 degraded copies. Ten causes, each fixed and pinned by a
test in `tests/test_hard_artwork.py`, included these:

- A bottler phrase on its own line ("Distilled and Bottled by") was read as the name.
- Border ornaments ("Pax", "ee") in the warning counted as altered wording.
- Heavy JPEG left the bottler's name unread, and the address was compared as the name.

**A missing "not" was referred as a misread.** Deletions of up to five words counted as
OCR dropout. So "women should drink alcoholic beverages during pregnancy" went to an
agent marked as a reading problem, and a second reading could clear it. Losing "not" now
fails, and the second reading may no longer touch the warning's wording at all.

**Matching passed things it should not have.** "Buffalo Grace" passed for "Buffalo
Trace" at 96%, with a reason saying only case differed. Austria passed for Australia,
"XYZ Distilling Company" for "ABC Distilling Company", and "California Rose Wine" for
"California Red Wine". Brand and class now need the same words, the country the same
country, and a bottler name its own distinctive words.

**Three citations named the wrong paragraph.** The capital-letters rule is 16.22(a)(2),
where I had 16.22(b), which sets type size. "Separate and apart" is in 16.21, where I had
16.22(a). And every beer and wine label cited part 5. Reading each section on eCFR found
all three; decision 12 fixes the last.

**The page showed one label's verdict under another's artwork.** While the tool checked a
new label, the old checklist stayed on screen for a second or more. A TIFF, the format
scanners produce, previewed as a broken image in Chrome and Edge. A screen reader never
heard a referral's verdict once a second reading started. Browser tests over every control
found these.

---

## What I would do next

1. **Measure Jev on real referrals.** Eighteen fixture referrals are a small sample.
   `python -m eval.run --triage jev` with an AI Gateway credential reports the same
   ordering locally. The decisions agents record (item 7) are the data to judge it on.
2. **Calibrate the thresholds on real COLA artwork.** Every number here is tuned against
   37 rendered labels and checked against 15 AI-generated ones. The bold bands rest on
   one regular sample each.
3. **Read the warning block a second time at higher resolution.** The soft-focus
   photograph is the case to measure a targeted OCR pass on.
4. **Let a second reading contest an absence.** Glare that erases a line leaves OCR
   nothing, so "no net contents statement" still rejects. A model that finds the
   statement there could turn that rejection into a referral, never a pass.
5. **Check the class and type against the standards of identity** in subpart I, beyond
   comparing it with the application's text.
6. **Take the commodity from the application.** It is inferred from the designation
   today.
7. **Keep what agents decide.** Every referral an agent resolves is a labelled example.
   That is the dataset nobody has today, and the data triage would learn from.
