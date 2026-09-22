# Evaluation report: `ocr:tesseract`

**30 fixtures · 86.7% verdict accuracy**

OCR engine: Tesseract 5.5.0.

## Outcome safety

A single accuracy number hides the distinction that matters here: escalating a compliant label costs an agent a minute, whereas rejecting one tells an applicant they broke the law when they did not.

| outcome | count |
|---|---|
| Correct | 26 |
| Referred to a human when not strictly needed | 3 |
| Defective, referred to a human instead of rejected | 1 |
| **Wrong in a way that harms someone** | **0** |

## Latency and throughput

These are two different numbers and conflating them is misleading. Sarah Chen's five second budget is about an agent waiting on **one** label, so it must be measured without contention. Batch is a throughput question: under load, per-label wall clock rises while labels per minute improves.

Measured at concurrency **1** (interactive).

| p50 | p95 | p99 | max |
|---|---|---|---|
| 1137 ms | 1447 ms | 1468 ms | 1468 ms |

Interactive target is < 5 000 ms. **p95 MET.**

Throughput: **50 labels/min** (30 in 35.7s). A 300-label batch would take about **5.9 minutes** at this concurrency.

## Verdict confusion matrix

| expected \ actual | pass | flag | fail |
|---|---|---|---|
| **pass** | 11 | 3 | 0 |
| **flag** | 0 | 4 | 0 |
| **fail** | 0 | 1 | 11 |

## Field extraction accuracy

| field | correct |
|---|---|
| `alcohol_statement` | 93% |
| `brand_name` | 97% |
| `class_type` | 97% |
| `net_contents` | 97% |
| `warning_prefix_is_bold` | 93% |
| `warning_text` | 90% |

## Referral triage (`heuristic`)

Triage orders referrals; it never changes a verdict. A referral of a label that should have passed is a read problem, and should score low. A referral of a label that genuinely needs a person should score high.

| fixture | referral is | chance of a genuine defect |
|---|---|---|
| `brand_near_miss` | genuine | 0.85 |
| `photo_soft_focus` | a read problem | 0.85 |
| `v2_body_caps_not_bold` | genuine | 0.55 |
| `warning_prefix_not_bold` | genuine | 0.55 |
| `photo_compressed` | a read problem | 0.20 |
| `photo_glare` | a read problem | 0.20 |
| `v2_malt_floz_wrong` | genuine | 0.20 |
| `warning_microtype` | genuine | 0.20 |

Genuine referrals ranked above read problems in **40%** of pairs.

## Cost

Nothing per label. There is no model, no API and no token. The only cost is local CPU time, which the latency table above already states.

## Rows failed in error

A row that fails when the fixture was not built to fail it tells an applicant something is wrong that is not, even if the label fails for another reason. Counted as harmful above.

None.

## Misses (4)

| fixture | expected | actual | note |
|---|---|---|---|
| `photo_compressed` | pass | flag | flagged government_warning |
| `photo_glare` | pass | flag | flagged brand_name, class_type, alcohol_content, proof_consistency |
| `photo_soft_focus` | pass | flag | flagged bottler_address, country_of_origin, government_warning, warning_typography |
| `v2_malt_floz_wrong` | fail | flag | flagged net_contents |

## All fixtures

| fixture | expected | actual | ms | description |
|---|---|---|---|---|
| `abv_mismatch` | fail | fail | 1443 | Label states 40%, application says 45% |
| `abv_no_proof` | pass | pass | 1431 | ABV only, no proof statement -- perfectly legal |
| `brand_case_difference` | pass | pass | 1192 | Label is all caps, application is title case. Dave: 'obviously the same thing.' |
| `brand_near_miss` | flag | flag | 1236 | One character apart -- ambiguous, must escalate rather than guess |
| `brand_wrong` | fail | fail | 1137 | Entirely different brand on the artwork |
| `clean_01` | pass | pass | 1150 | Compliant label, Old Tom Distillery |
| `clean_02` | pass | pass | 1119 | Compliant label, Stone'S Throw |
| `clean_03` | pass | pass | 1148 | Compliant label, Copper Ridge Reserve |
| `net_contents_centilitres` | pass | pass | 1100 | '75 cl' on an import against '750 mL' on the application -- equivalent |
| `net_contents_missing` | fail | fail | 1095 | Net contents absent from the artwork |
| `net_contents_wrong` | fail | fail | 1112 | 700 mL on the label, 750 mL on the application |
| `photo_compressed` | pass | flag ⚠ | 1468 | Heavily re-compressed JPEG, as arrives from email chains |
| `photo_glare` | pass | flag ⚠ | 1119 | Compliant label with specular glare across the upper third |
| `photo_skewed` | pass | pass | 1447 | Compliant label shot at an angle |
| `photo_skewed_and_defective` | fail | fail | 1342 | Angled shot AND a title-case warning -- degradation must not mask a real defect |
| `photo_soft_focus` | pass | flag ⚠ | 1145 | Compliant label, slightly out of focus |
| `proof_inconsistent` | fail | fail | 1116 | Label contradicts itself: 45% is 90 proof, not 80 |
| `v2_body_caps` | pass | pass | 1115 | Second template: whole statement in capitals; 16.22 regulates only the prefix |
| `v2_body_caps_not_bold` | flag | flag | 1112 | Second template: whole statement in capitals, prefix in regular weight |
| `v2_import_wrong_country` | fail | fail | 1063 | Second template: Scotch declared Scottish, label says Canada |
| `v2_malt_floz` | pass | pass | 1063 | Second template: '12 FL OZ' on the label, '355 mL' on the application |
| `v2_malt_floz_wrong` | fail | flag ⚠ | 1088 | Second template: '16 FL OZ' on the label, '355 mL' on the application |
| `v2_photo_skewed` | pass | pass | 1304 | Second template: compliant wine photographed at an angle |
| `v2_title_case` | fail | fail | 1112 | Second template: title-case warning prefix |
| `v2_wine_clean` | pass | pass | 1225 | Second template: compliant wine, serif, web address under the warning |
| `warning_microtype` | flag | flag | 1102 | Text buried at ~6pt -- too small to judge weight, must not guess |
| `warning_missing` | fail | fail | 1094 | No health warning statement at all |
| `warning_prefix_not_bold` | flag | flag | 1178 | Correct text, but the prefix is set in regular weight -- advisory only |
| `warning_reworded` | fail | fail | 1154 | Softened wording -- 'may wish to avoid' instead of 'should not drink' |
| `warning_title_case` | fail | fail | 1164 | 'Government Warning:' in title case -- the rejection Jenny caught |
