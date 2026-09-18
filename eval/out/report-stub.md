# Evaluation report — `stub`

**22 fixtures · 100.0% verdict accuracy**

## Outcome safety

A single accuracy number hides the distinction that matters here: escalating a compliant label costs an agent a minute, whereas rejecting one tells an applicant they broke the law when they did not.

| outcome | count |
|---|---|
| Correct | 22 |
| Referred to a human when not strictly needed | 0 |
| **Wrong in a way that harms someone** | **0** |

## Latency

Wall clock for the full operation: preprocessing, extraction and rule evaluation.

| p50 | p95 | p99 | max |
|---|---|---|---|
| 1262 ms | 2105 ms | 2523 ms | 2523 ms |

Target is < 5 000 ms (Sarah Chen). **p95 MET.**

## Verdict confusion matrix

| expected \ actual | pass | flag | fail |
|---|---|---|---|
| **pass** | 10 | 0 | 0 |
| **flag** | 0 | 3 | 0 |
| **fail** | 0 | 0 | 9 |

## Field extraction accuracy

| field | correct |
|---|---|
| `alcohol_statement` | 100% |
| `brand_name` | 100% |
| `class_type` | 100% |
| `net_contents` | 100% |
| `warning_prefix_is_bold` | 100% |
| `warning_text` | 100% |

## Cost

Mean 0 input / 0 output tokens per label.

## Misses (0)

None.

## All fixtures

| fixture | expected | actual | ms | description |
|---|---|---|---|---|
| `abv_mismatch` | fail | fail | 1154 | Label states 40%, application says 45% |
| `abv_no_proof` | pass | pass | 1301 | ABV only, no proof statement -- perfectly legal |
| `brand_case_difference` | pass | pass | 1634 | Label is all caps, application is title case. Dave: 'obviously the same thing.' |
| `brand_near_miss` | flag | flag | 1233 | One character apart -- ambiguous, must escalate rather than guess |
| `brand_wrong` | fail | fail | 2105 | Entirely different brand on the artwork |
| `clean_01` | pass | pass | 979 | Compliant label, Old Tom Distillery |
| `clean_02` | pass | pass | 837 | Compliant label, Stone'S Throw |
| `clean_03` | pass | pass | 1113 | Compliant label, Copper Ridge Reserve |
| `net_contents_centilitres` | pass | pass | 1345 | '75 cl' on an import against '750 mL' on the application -- equivalent |
| `net_contents_missing` | fail | fail | 1255 | Net contents absent from the artwork |
| `net_contents_wrong` | fail | fail | 1320 | 700 mL on the label, 750 mL on the application |
| `photo_compressed` | pass | pass | 2523 | Heavily re-compressed JPEG, as arrives from email chains |
| `photo_glare` | pass | pass | 2020 | Compliant label with specular glare across the upper third |
| `photo_skewed` | pass | pass | 1704 | Compliant label shot at an angle |
| `photo_skewed_and_defective` | fail | fail | 1804 | Angled shot AND a title-case warning -- degradation must not mask a real defect |
| `photo_soft_focus` | pass | pass | 1262 | Compliant label, slightly out of focus |
| `proof_inconsistent` | fail | fail | 1013 | Label contradicts itself: 45% is 90 proof, not 80 |
| `warning_microtype` | flag | flag | 1700 | Text buried at ~6pt -- too small to judge weight, must not guess |
| `warning_missing` | fail | fail | 1396 | No health warning statement at all |
| `warning_prefix_not_bold` | flag | flag | 874 | Correct text, but the prefix is set in regular weight -- advisory only |
| `warning_reworded` | fail | fail | 1006 | Softened wording -- 'may wish to avoid' instead of 'should not drink' |
| `warning_title_case` | fail | fail | 1127 | 'Government Warning:' in title case -- the rejection Jenny caught |
