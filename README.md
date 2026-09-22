# TTB Label Verification Prototype

Checks alcohol beverage label artwork against the data in its COLA application and
shows a compliance agent exactly what matched, what did not and why.

**No machine learning model, no API key, no outbound network call.** Every field is
read with local OCR and every determination comes from an inspectable rule with a
CFR citation.

> **Live prototype:** _add the deployed URL here at submission_ (see [Deployment](#deployment)).
> Runs as a single container with no egress.

## Try it in sixty seconds

1. Open the app. Under **Or try a sample label**, click any of the three samples. The
   artwork appears beside the checklist, with a verdict, a reason and a citation on
   every row.
2. Click **Many labels**, then **Run the sample batch**. Twenty-two labels run through
   the same endpoint with a progress bar, a summary and a CSV export.
3. Upload your own artwork in **One label**. The form takes what is on a COLA
   application; only COLA ID and brand name are required.
4. The API is documented at `/docs`.

## Measured results

22 fixture labels, full OCR pipeline, one label at a time. Measured on Windows 11 with
Tesseract 5.4; the numbers regenerate with `make eval` and land in `eval/out/report.md`.

| | |
|---|---|
| Verdict accuracy | **86.4%** (19/22) |
| Referred to a human unnecessarily | 3 |
| **Wrong in a way that harms someone** | **0** |
| Latency p50 / p95, one label | **1.26 s / 1.50 s** (budget: 5 s) |
| Throughput, batch (8 workers) | **209 labels/min**; a 300-label batch in about 1.4 minutes |
| Cost per label | $0.00 |

A single accuracy figure would hide the distinction that matters. Escalating a
compliant label to an agent costs a minute. Rejecting one tells an applicant they
broke the law when they did not. All three misses are the first kind: degraded
photographs of compliant labels referred for human review. There are no false
rejections and no missed violations, and `make eval` exits non-zero if either ever
appears.

The thresholds were first tuned on a macOS Tesseract build. Re-running on a different
build (Windows, 5.4) turned one of the three referrals into a rejection: the compressed
photo came back with a stray glyph and two punctuation marks changed, and the rule read
that as altered wording. That is exactly the harm this tool exists to prevent, so the
rule now compares words first and treats punctuation-only noise as a referral. The
regression is pinned by a test that carries the real transcription.

## Scope and time box

The brief set no time budget, so I set one: about sixteen hours, plus a review pass.
Where something was cut it is listed under [Limitations](#limitations) rather than
left half-built.

## Approach

### Why not a vision model

The centrepiece of this tool is a byte-exact comparison against a statutory text, and
its output can cause a federal rejection of someone's application. That argues for a
pipeline where every step can be quoted back in an appeal: "the sixth word of your
warning statement reads X, 27 CFR 16.21 requires Y". A model's judgement cannot be
quoted that way.

It also answers Marcus Williams directly. His firewall blocked the last vendor's ML
endpoints and killed half their features; nothing here needs to leave the building.
There is no key to rotate, no per-label cost and no vendor to depend on.

### The extraction / decision split

`app/extract/` reports what is printed on the label. `app/rules/` decides what that
means. The two never mix: extraction cannot return a verdict, and the rule engine
never touches an image. That keeps the entire decision layer unit-testable with no
image, no OCR and no I/O. It runs in about a second.

### Matching policy is per field

The brief plants a deliberate contradiction between two stakeholders. Dave Morrison
wants `STONE'S THROW` to pass against `Stone's Throw`: "obviously the same thing."
Jenny Park rejected a label for setting `Government Warning` in title case. Both are
right, because they are describing different fields:

| Field | Policy | Basis |
|---|---|---|
| Brand name | Unicode-normalise, casefold, strip punctuation, fuzzy ratio, banded PASS / FLAG / FAIL | 27 CFR 5.64 |
| Class / type | Same normalisation, stricter bands: regulated vocabulary, not a mark | 5.63(a)(2), subpart I |
| Alcohol content | Parse the percentage, compare to the application, cross-check proof = 2 × ABV, and check the statement uses a permitted form | 5.65(b) |
| Net contents | Unit-normalise (`750 mL` = `75 cl` = `0.75 L`), then compare | 5.70 |
| Bottler name and address | Token-set similarity; a name mismatch can fail, an address mismatch only flags | 5.66 to 5.68 |
| Country of origin | Required on imports only; the country itself is compared, not the boilerplate | 5.69 |
| Government warning | Whitespace-normalise, then exact against the statute, with a word-level diff | 16.21 |
| Warning typography | Prefix weight by ink density, advisory; the 16.22(b) size minimum for this container is stated | 16.22 |

Every citation was checked against the published CFR text on 2026-09-21.

### Three verdicts, not two

`PASS` / `FLAG` / `FAIL`. Dave has watched binary automation fail before; a system that
cannot say "I'm not sure, look at this one" pushes its own uncertainty onto the
applicant.

### What the warning rule forgives, and why

27 CFR 16.21 fixes the wording. 16.22(b) fixes the case and weight of the two words
`GOVERNMENT WARNING` and nothing else about case. So the rule is exact on wording and
on the prefix. It deliberately tolerates three things. The regulation does not mention
them, or the camera can cause them:

- **Body case.** A label that sets the whole statement in capitals is compliant and
  passes. A title-case prefix is a real defect and fails, citing 16.22(b).
- **Wrapping and hyphenation.** The statute contains no hyphens, so `preg-` at a line
  end followed by `nancy` is a wrap.
- **Punctuation and stray glyphs.** When every word is present and in order, a period
  read as a colon is the camera's doing. It is referred to an agent, never rejected.

Text that follows an exact statement on the same block, such as a web address, is
not treated as wrong wording. It flags with a 16.22(a) citation, because the statement
must appear separate and apart from other information, and an agent confirms.

### Making OCR safe enough to reject on

Tesseract's characteristic failure is losing text, not inventing it. These rules keep
that failure mode from ever being reported as a violation:

1. **Unreadable is not absent.** Small print detected but not resolved reports
   `illegible`, which flags. Only genuine absence fails.
2. **Dropped words are not altered words.** A near-perfect match that differs only by
   deletion is treated as an imperfect read and flagged. Substitutions stay hard
   failures.
3. **Low confidence cannot reject.** A field read below 70% confidence downgrades any
   failure to a flag.
4. **A degraded image cannot reject anything.** Every label sets its brand as the most
   prominent element. If nothing on the page is substantially larger than the body
   copy, the brand did not survive the photograph and no field from that image is
   trusted.
5. **The warning block ends where the statute ends.** Once the closing words have been
   read, whatever small print follows is a separate element. Without this, a website
   line under the warning became part of the transcription and failed the label.

### What recovered the most accuracy

Two preprocessing steps, both found by measuring rather than assuming:

- **Deskew.** A 7° tilt made Tesseract miss the warning statement entirely. Estimated
  by projecting an edge map and maximising the squared gradient of the horizontal
  profile. Projecting raw ink instead lets dark background at the corners dominate and
  the estimate collapses to zero; that regression is pinned by a test.
- **Upscale.** Small type sits below Tesseract's reliable floor until enlarged to
  roughly 300 DPI equivalent.

Together these took exact warning transcription from 17/22 to 20/22.

## Assumptions

The brief is written as stakeholder interviews with no formal requirements section, so
these are my readings of it:

1. **Application records arrive as JSON or CSV alongside the images**, joined on
   `cola_id`. The brief never says how application data enters the system; this was
   the largest open question and I resolved it rather than blocking. Column headings
   are matched flexibly, so a spreadsheet export works without reshaping.
2. **Distilled spirits are the primary class in scope**, per the worked example.
3. **No COLA integration**, per Marcus. Standalone proof of concept.
4. **Nothing is persisted.** Images are processed in memory and discarded.
5. **Label versus application has no alcohol tolerance.** 27 CFR 5.65(c) allows 0.3
   points between labeled and actual content, which is a laboratory question. The
   application states what the label says, so the comparison here is exact.

## Limitations

- **Type size cannot be verified from an image.** 27 CFR 16.22(b) specifies minimums
  in millimetres; a photograph carries pixels. The applicable minimum is stated from
  the container volume on every result so the agent knows what to check.
- **The bold/regular boundary is weakly calibrated.** Measured separation is 1.21 for
  regular against 1.33 to 1.48 for bold, from a single negative sample. The band leaves
  an explicit undecided zone that reports "cannot tell" rather than guessing.
- **Severe glare defeats field reading.** The tool detects this and refers the label to
  a human; it does not recover the text.
- **Class and type is compared as text.** Whether a designation is permitted for the
  product (subpart I of Part 5) is not checked.
- **Batch progress lives in the browser.** A page refresh loses it. Nothing is stored
  server-side by design.

## Build plan

- [x] Domain models and the extract / decide seam
- [x] Rule engine: brand, class/type, alcohol + proof consistency + statement form, net contents, bottler, country, warning, typography
- [x] OCR extraction: deskew, upscale, Otsu binarisation, layout-based field assignment
- [x] Safety rules that keep a read failure from becoming a rejection
- [x] 22-fixture evaluation harness gated on harmful outcomes
- [x] Single-label review UI with the artwork beside the checklist
- [x] Batch review with bounded concurrency, sample batch and CSV export
- [x] Container image
- [ ] Deployed URL (add above)

## Running it

The only system dependency is Tesseract.

```bash
# macOS                 brew install tesseract
# Debian / Ubuntu       sudo apt install tesseract-ocr
# Windows               winget install UB-Mannheim.TesseractOCR
#                       (the default install path is found automatically)

make install
make test                  # 164 tests, no network, no OCR needed
make eval                  # full fixture sweep, one label at a time
make eval-throughput       # the same, 8 workers
make dev                   # http://localhost:8000
```

The Makefile works from macOS, Linux, WSL and Git Bash on Windows. `make fixtures`
regenerates the label set; it needs Arial, so the rendered PNGs are committed to keep
the eval set reproducible without it.

### Deployment

```bash
docker build -t ttb-label-verifier .
docker run --rm -p 8000:8000 ttb-label-verifier
```

The image installs Tesseract and the English model at build time, runs as an
unprivileged user, exposes `/healthz` and makes no outbound connection at run time.
`PORT` and `MAX_BATCH_CONCURRENCY` are the only knobs a host needs. Any container
host works; the app needs about 512 MB of memory and one CPU per concurrent label.

## Regulatory references

- 27 CFR 16.21: health warning statement text
- 27 CFR 16.22: placement, prefix case and weight, type size by container volume
- 27 CFR Part 5, subpart E: mandatory label information for distilled spirits (5.63 to 5.70)
- 27 CFR Part 4 (wine), Part 7 (malt beverages)
