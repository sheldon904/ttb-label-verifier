# Evaluation report: `ocr:tesseract`

**22 fixtures · 86.4% verdict accuracy**

## Outcome safety

A single accuracy number hides the distinction that matters here: escalating a compliant label costs an agent a minute, whereas rejecting one tells an applicant they broke the law when they did not.

| outcome | count |
|---|---|
| Correct | 19 |
| Referred to a human when not strictly needed | 3 |
| **Wrong in a way that harms someone** | **0** |

## Latency and throughput

These are two different numbers and conflating them is misleading. Sarah Chen's five second budget is about an agent waiting on **one** label, so it must be measured without contention. Batch is a throughput question: under load, per-label wall clock rises while labels per minute improves.

Measured at concurrency **1** (interactive).

| p50 | p95 | p99 | max |
|---|---|---|---|
| 1260 ms | 1501 ms | 1584 ms | 1584 ms |

Interactive target is < 5 000 ms. **p95 MET.**

Throughput: **46 labels/min** (22 in 28.4s). A 300-label batch would take about **6.5 minutes** at this concurrency.

## Verdict confusion matrix

| expected \ actual | pass | flag | fail |
|---|---|---|---|
| **pass** | 7 | 3 | 0 |
| **flag** | 0 | 3 | 0 |
| **fail** | 0 | 0 | 9 |

## Field extraction accuracy

| field | correct |
|---|---|
| `alcohol_statement` | 91% |
| `brand_name` | 95% |
| `class_type` | 95% |
| `net_contents` | 100% |
| `warning_prefix_is_bold` | 86% |
| `warning_text` | 86% |

## Cost

Nothing per label. There is no model, no API and no token. The only cost is local CPU time, which the latency table above already states.

## Misses (3)

| fixture | expected | actual | note |
|---|---|---|---|
| `photo_compressed` | pass | flag | flagged government_warning |
| `photo_glare` | pass | flag | flagged brand_name, class_type, alcohol_content, proof_consistency |
| `photo_soft_focus` | pass | flag | flagged government_warning, warning_typography |

## All fixtures

| fixture | expected | actual | ms | description |
|---|---|---|---|---|
| `abv_mismatch` | fail | fail | 1146 | Label states 40%, application says 45% |
| `abv_no_proof` | pass | pass | 1090 | ABV only, no proof statement -- perfectly legal |
| `brand_case_difference` | pass | pass | 1112 | Label is all caps, application is title case. Dave: 'obviously the same thing.' |
| `brand_near_miss` | flag | flag | 1196 | One character apart -- ambiguous, must escalate rather than guess |
| `brand_wrong` | fail | fail | 1418 | Entirely different brand on the artwork |
| `clean_01` | pass | pass | 1435 | Compliant label, Old Tom Distillery |
| `clean_02` | pass | pass | 1385 | Compliant label, Stone'S Throw |
| `clean_03` | pass | pass | 1148 | Compliant label, Copper Ridge Reserve |
| `net_contents_centilitres` | pass | pass | 1276 | '75 cl' on an import against '750 mL' on the application -- equivalent |
| `net_contents_missing` | fail | fail | 1233 | Net contents absent from the artwork |
| `net_contents_wrong` | fail | fail | 1465 | 700 mL on the label, 750 mL on the application |
| `photo_compressed` | pass | flag ⚠ | 1584 | Heavily re-compressed JPEG, as arrives from email chains |
| `photo_glare` | pass | flag ⚠ | 1242 | Compliant label with specular glare across the upper third |
| `photo_skewed` | pass | pass | 1473 | Compliant label shot at an angle |
| `photo_skewed_and_defective` | fail | fail | 1501 | Angled shot AND a title-case warning -- degradation must not mask a real defect |
| `photo_soft_focus` | pass | flag ⚠ | 1249 | Compliant label, slightly out of focus |
| `proof_inconsistent` | fail | fail | 1230 | Label contradicts itself: 45% is 90 proof, not 80 |
| `warning_microtype` | flag | flag | 1260 | Text buried at ~6pt -- too small to judge weight, must not guess |
| `warning_missing` | fail | fail | 1096 | No health warning statement at all |
| `warning_prefix_not_bold` | flag | flag | 1291 | Correct text, but the prefix is set in regular weight -- advisory only |
| `warning_reworded` | fail | fail | 1267 | Softened wording -- 'may wish to avoid' instead of 'should not drink' |
| `warning_title_case` | fail | fail | 1260 | 'Government Warning:' in title case -- the rejection Jenny caught |
