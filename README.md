# TTB Label Verification Prototype

[![CI](https://github.com/sheldon904/ttb-label-verifier/actions/workflows/ci.yml/badge.svg)](https://github.com/sheldon904/ttb-label-verifier/actions/workflows/ci.yml)

Checks alcohol beverage label artwork against the data in its COLA application and
shows a compliance agent exactly what matched, what did not and why.

**Every verdict comes from local OCR and an inspectable rule with a CFR citation.**
Two model features sit downstream of those rules, and neither can reject a label:

- **A second reading.** When OCR cannot read part of a label and the rules refer it,
  Claude Sonnet 5 (through OpenRouter) re-reads just those fields from the image. It can
  clear the referral; it can never produce a rejection.
- **Referral triage.** TypeSafe's Jev (through Vercel AI Gateway) estimates which
  referrals in a batch are real defects, so the queue starts with them.

Each switches on when its credential is present. With none, the whole app runs inside
one container with no outbound call, which is what a locked-down network needs.

> **Live prototype:** _add the deployed URL here at submission_ (see [Deployment](#deployment)).

## Try it in sixty seconds

1. Open the app. Under **Or try a sample label**, click any of the six samples. The
   artwork appears beside the checklist, with a box drawn where each field was read,
   coloured by its result. Click a checklist row to pick out its box. The tilted
   photograph shows the boxes following the tilt. The glare-damaged photograph is one
   OCR cannot fully read: watch the second reading clear it, marked on each row it
   changed.
2. The checklist answers two questions separately: does the label match its
   application, and does the label meet the regulation on its own terms.
3. Click **Many labels**, then **Run the sample batch**. Thirty labels run through the
   same endpoint with a progress bar, a summary and a CSV export. Referrals sort by how
   likely each is to be a real defect, with a "likely cause" column.
4. Upload your own artwork in **One label**. The form takes what is on a COLA
   application; only COLA ID and brand name are required.
5. The API is documented at `/docs`.

## Measured results

30 fixture labels in two artwork styles, full OCR pipeline, one label at a time. The
same fixtures were run on three Tesseract builds, because the first cross-build run
found a failure the original build never showed.

| Tesseract build | Correct | Compliant, referred | Defective, referred | **Harmful** | p95 |
|---|---|---|---|---|---|
| 5.4.0, Windows | 27 | 3 | 0 | **0** | 1.53 s |
| 5.5.0, Debian (the container) | 26 | 3 | 1 | **0** | 1.45 s |
| 5.3.4, Ubuntu 24.04 (CI) | 26 | 3 | 1 | **0** | 1.48 s |

The interactive budget is 5 s. Batch throughput is 219 labels a minute with 8 workers,
so a 300-label peak-season batch takes about a minute and a half. A verdict costs
nothing; a referred label that gets a second reading costs about a cent. Reports: [`eval/out/report.md`](eval/out/report.md) and the per-build copies
beside it.

A single accuracy figure would hide the distinction that matters, so the evaluation
reports four outcomes:

- **Harmful** means a compliant label rejected, a label that needed a person rejected,
  anything that should not pass passing, or any single row failed in error on any
  label. There are none on any build, and `make eval` exits non-zero if one appears.
- **Compliant, referred** is a degraded photograph of a compliant label sent to an
  agent. It costs a minute.
- **Defective, referred** is a defective label sent to an agent with the defect on the
  checklist, where a rejection was expected. On two builds the "16 FL OZ" unit reads
  at near-zero confidence, and a field read that badly is not allowed to reject.

## Scope and time box

The brief set no time budget, so I set one: about sixteen hours for the build, plus two
review passes. Where something was cut it is listed under [Limitations](#limitations)
rather than left half-built.

## Approach

### Where a model fits, and where it does not

The centrepiece of this tool is an exact comparison against a statutory text, and its
output can cause a federal rejection of someone's application. Every rejection here
can be quoted back in an appeal: "the sixth word of your warning statement reads X,
27 CFR 16.21 requires Y". A model's judgement cannot be quoted that way, so no model
decides anything.

It also answers Marcus Williams directly. His firewall blocked the last vendor's ML
endpoints and killed half their features. The default deployment needs nothing from
outside the building.

The brief is titled "AI-Powered", and two thirds of the public submissions to it put a
vision model in charge of reading. This one uses a model in the two places it helps and
cannot hurt:

- **A second reading of referred labels** (on when `OPENROUTER_API_KEY` is set). When
  the rules refer a label because OCR could not read part of it, Claude Sonnet 5 re-reads
  only those fields from the image, through OpenRouter, answering through a typed tool
  call so free text cannot come back. The rules run again on the new reading, and a row is replaced
  only if it now passes. A second reading that disagrees changes nothing, so the worst
  a wrong or manipulated reading can do is clear a referral OCR could not read. The
  row then says where its reading came from and asks the agent to confirm it. A
  confident disagreement, such as a brand one letter off, is never offered. It costs
  about a cent per referred label, only referred labels are ever sent, and three guards
  cap the bill: a cache so a reviewer clicking the same sample twice pays once, a daily
  call limit, and the OpenRouter credit limit. Requests are routed only to
  providers that do not store or train on them. Any model on OpenRouter is one setting
  away.
- **Referral triage** (on by default; `TRIAGE=jev`). After a batch run, [Jev](https://vercel.com/docs/ai-gateway/modalities/evaluation)
  estimates for each referral how likely it is to be a real defect rather than a read
  problem, and the queue sorts by it. Jev receives field names, verdicts, similarity
  scores and word counts. It receives no text from the label, because label text is
  written by the applicant and anything written there would be a prompt. Without a
  gateway credential, or when the call fails, a local heuristic takes over and the row
  says so. That heuristic is also the baseline Jev has to beat: on the fixtures it ranks
  genuine referrals above read problems in 75% of pairs. A referral costs Jev about
  $0.00001.

### The extraction / decision split

`app/extract/` reports what is printed on the label. `app/rules/` decides what that
means. The two never mix: extraction cannot return a verdict, and the rule engine
never touches an image. That keeps the entire decision layer unit-testable with no
image, no OCR and no I/O.

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
| Net contents | Unit-normalise (`750 mL` = `75 cl` = `0.75 L`, `12 FL OZ` = `355 mL`), then compare | 5.70, 7.70 |
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
treated as a separate element. It flags with a 16.22(a) citation, because the statement
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
   read, whatever small print follows is a separate element.
6. **A half-read quantity is a referral.** A number standing alone where the statements
   are is a volume whose unit was lost, and it flags. A unit Tesseract read correctly
   but scored near zero is re-attached, at that low score, so it too can only flag.

Every row whose doubt comes from the image carries a `read_uncertain` marker. That
marker is the only thing a second reading is allowed to act on.

### What a second artwork style found

Every threshold was first tuned on one rendered template. A second template (serif,
left-aligned, a wine and two malt beverages in fluid ounces, small print under the
warning) found four defects the first could not:

- A two-line brand, "COPPER RIDGE" over "RESERVE", was read as "COPPER RIDGE" and
  failed. The label failed for another reason too, so the verdict looked right; the
  evaluation now also fails on any single row failed in error.
- Georgia's "12 FL OZ" came back as "12" plus two words scored at zero, and the label
  failed for a missing net contents statement.
- A bold prefix over a body set in capitals measured as regular. About 0.2 of the
  bold ratio is the capitals, so matching cases now use their own measured band.
- A blank image was rotated twelve degrees, because every angle scored the same and
  the search took the first one.

All four are fixed and pinned by tests.

### What recovered the most accuracy

Two preprocessing steps, both found by measuring:

- **Deskew.** A 7° tilt made Tesseract miss the warning statement entirely. Estimated
  by projecting an edge map and maximising the squared gradient of the horizontal
  profile.
- **Upscale.** Small type sits below Tesseract's reliable floor until enlarged to
  roughly 300 DPI equivalent.

Together these took exact warning transcription from 17/22 to 20/22 on the first
template.

## Assumptions

The brief is written as stakeholder interviews with no formal requirements section, so
these are my readings of it:

1. **Application records arrive as JSON or CSV alongside the images**, joined on
   `cola_id`. The brief never says how application data enters the system; this was
   the largest open question and I resolved it rather than blocking. Column headings
   are matched flexibly, so a spreadsheet export works without reshaping.
2. **Distilled spirits are the primary class in scope**, per the worked example. Wine
   and malt beverage fixtures check that nothing is spirits-only by accident.
3. **No COLA integration**, per Marcus. Standalone proof of concept.
4. **Nothing is persisted.** Images are processed in memory and discarded.
5. **Label versus application has no alcohol tolerance.** 27 CFR 5.65(c) allows 0.3
   points between labeled and actual content, which is a laboratory question. The
   application states what the label says, so the comparison here is exact.

## Limitations

- **The two model features have not been measured live.** No provider credentials were
  available during development. Both are built against the providers' documented contracts and
  tested against mocked responses, including hostile ones. The evaluation reports what
  each did the first time it runs with credentials (`python -m eval.run --second-opinion
  openrouter --triage jev`), including the provider-reported cost per label.
- **Type size cannot be verified from an image.** 27 CFR 16.22(b) specifies minimums
  in millimetres; a photograph carries pixels. The applicable minimum is stated from
  the container volume on every result so the agent knows what to check.
- **The bold/regular bands are calibrated on few samples**, one regular sample for each
  case pairing. Both bands leave an undecided zone that reports "cannot tell".
- **Severe glare defeats field reading.** The tool detects this and refers the label to
  a human. The second opinion is the path to recovering it.
- **Class and type is compared as text.** Whether a designation is permitted for the
  product (subpart I of Part 5) is not checked.
- **Batch progress lives in the browser.** A page refresh loses it. Nothing is stored
  server-side by design.

## Running it

The only system dependency is Tesseract.

```bash
# macOS                 brew install tesseract
# Debian / Ubuntu       sudo apt install tesseract-ocr
# Windows               winget install UB-Mannheim.TesseractOCR
#                       (the default install path is found automatically)

make install
make test                  # 239 tests, no network, no paid calls
make eval                  # full fixture sweep, one label at a time
make eval-throughput       # the same, 8 workers
make dev                   # http://localhost:8000
```

The Makefile works from macOS, Linux, WSL and Git Bash on Windows. `make fixtures`
regenerates every label and needs the fonts; `python fixtures/generate.py --new-only`
renders only fixtures that do not have an image yet, so the committed evaluation set
never changes under you.

### Configuration

| Variable | Default | Effect |
|---|---|---|
| `MAX_BATCH_CONCURRENCY` | 8 (4 in the container) | Labels in the OCR pool at once; the batch page reads it |
| `RATE_LIMIT_PER_MINUTE` | 120 | Review requests per address per minute; over it, a 429 the batch page waits out |
| `TRUST_PROXY_HEADERS` | off | Behind a host's load balancer, take the address from `X-Forwarded-For` |
| `MAX_BATCH_LABELS` | 500 | Largest batch accepted |
| `OPENROUTER_API_KEY` | none | Turns on the second reading. Set a credit limit for it at openrouter.ai |
| `SECOND_OPINION` | auto | `auto` is on when a credential is present; `off` disables it; `anthropic` uses `ANTHROPIC_API_KEY` directly |
| `SECOND_OPINION_MODEL` | `anthropic/claude-sonnet-5` | Any vision model on OpenRouter |
| `SECOND_OPINION_DAILY_LIMIT` | 300 | Paid second readings per day per instance |
| `AI_GATEWAY_API_KEY` | none | Lets triage ask Jev; on Vercel the deployment's OIDC token also works |
| `TRIAGE` | jev | Falls back to the local heuristic without a credential; `off` hides triage |

The page footer states which of the two model features is on. The evaluation never
calls a paid model unless asked (`--second-opinion openrouter`), so `make eval` and CI
stay free.

### Deployment

```bash
docker build -t ttb-label-verifier .
docker run --rm -p 8000:8000 ttb-label-verifier
```

The image installs Tesseract and the English model at build time, runs as an
unprivileged user, exposes `/healthz` and makes no outbound connection at run time
unless a model credential is supplied. CI builds the image and checks it answers on
every push.

**On Vercel**, which runs a `Dockerfile.vercel` as a function: import the repository as
a new project, then set these environment variables and deploy.

| Variable | Value |
|---|---|
| `OPENROUTER_API_KEY` | an OpenRouter credential with a credit limit, for the second reading |
| `AI_GATEWAY_API_KEY` | an AI Gateway credential, for Jev (optional: the deployment's OIDC token is tried) |
| `TRUST_PROXY_HEADERS` | `1` |

`Dockerfile.vercel` is a byte-for-byte copy of `Dockerfile`, checked by a test. An idle
deployment scales to zero after a few minutes, so the first request after a quiet
spell starts the container. Any other container host works the same way.

## Regulatory references

- 27 CFR 16.21: health warning statement text
- 27 CFR 16.22: placement, prefix case and weight, type size by container volume
- 27 CFR Part 5, subpart E: mandatory label information for distilled spirits (5.63 to 5.70)
- 27 CFR Part 4 (wine), Part 7 (malt beverages; 7.70 net contents)
