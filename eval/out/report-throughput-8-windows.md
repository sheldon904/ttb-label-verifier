# Evaluation report: `ocr:tesseract`

**37 fixtures · 91.9% verdict accuracy**

OCR engine: Tesseract 5.4.0.20240606.

## Outcome safety

A single accuracy number hides the distinction that matters here: escalating a compliant label costs an agent a minute, whereas rejecting one tells an applicant they broke the law when they did not.

| outcome | count |
|---|---|
| Correct | 34 |
| Referred to a human when not strictly needed | 3 |
| Defective, referred to a human instead of rejected | 0 |
| **Wrong in a way that harms someone** | **0** |

## Latency and throughput

These are two different numbers and conflating them is misleading. Sarah Chen's five second budget is about an agent waiting on **one** label, so it must be measured without contention. Batch is a throughput question: under load, per-label wall clock rises while labels per minute improves.

Measured at concurrency **8** (under load).

| p50 | p95 | p99 | max |
|---|---|---|---|
| 1661 ms | 1943 ms | 1968 ms | 1968 ms |

Throughput: **271 labels/min** (37 in 8.2s). A 300-label batch would take about **1.1 minutes** at this concurrency.

## Verdict confusion matrix

| expected \ actual | pass | flag | fail |
|---|---|---|---|
| **pass** | 16 | 3 | 0 |
| **flag** | 0 | 4 | 0 |
| **fail** | 0 | 0 | 14 |

## Field extraction accuracy

Exact match with the text printed on the artwork, before any second reading. The brand and class are scored as the rules see them: a brand set on two lines is read as two lines and joined against the application.

| field | correct |
|---|---|
| `alcohol_statement` | 92% |
| `brand_name` | 97% |
| `class_type` | 97% |
| `net_contents` | 97% |
| `warning_prefix_is_bold` | 95% |
| `warning_text` | 92% |

## Referral triage (`heuristic`)

Triage orders referrals; it never changes a verdict. A referral of a label that should have passed is a read problem, and should score low. A referral of a label that genuinely needs a person should score high.

| fixture | referral is | chance of a genuine defect |
|---|---|---|
| `brand_near_miss` | genuine | 0.85 |
| `v2_body_caps_not_bold` | genuine | 0.55 |
| `warning_microtype` | genuine | 0.55 |
| `warning_prefix_not_bold` | genuine | 0.55 |
| `photo_compressed` | a read problem | 0.20 |
| `photo_glare` | a read problem | 0.20 |
| `photo_soft_focus` | a read problem | 0.20 |

Genuine referrals ranked above read problems in **100%** of pairs (complete separation).

## Cost

Nothing per label. There is no model, no API and no token. The only cost is local CPU time, which the latency table above already states.

## Rows failed in error

A row that fails when the fixture was not built to fail it tells an applicant something is wrong that is not, even if the label fails for another reason. Counted as harmful above.

None.

## Misses (3)

| fixture | expected | actual | note |
|---|---|---|---|
| `photo_compressed` | pass | flag | flagged government_warning |
| `photo_glare` | pass | flag | flagged brand_name, class_type, alcohol_content, proof_consistency |
| `photo_soft_focus` | pass | flag | flagged government_warning, warning_typography |

## All fixtures

| fixture | expected | actual | ms | description |
|---|---|---|---|---|
| `abv_mismatch` | fail | fail | 1735 | Label states 40%, application says 45% |
| `abv_no_proof` | pass | pass | 1723 | ABV only, no proof statement -- perfectly legal |
| `brand_case_difference` | pass | pass | 1562 | Label is all caps, application is title case. Dave: 'obviously the same thing.' |
| `brand_near_miss` | flag | flag | 1587 | One character apart -- ambiguous, must escalate rather than guess |
| `brand_wrong` | fail | fail | 1721 | Entirely different brand on the artwork |
| `clean_01` | pass | pass | 1700 | Compliant label, Old Tom Distillery |
| `clean_02` | pass | pass | 1505 | Compliant label, Stone'S Throw |
| `clean_03` | pass | pass | 1735 | Compliant label, Copper Ridge Reserve |
| `net_contents_centilitres` | pass | pass | 1768 | '75 cl' on an import against '750 mL' on the application -- equivalent |
| `net_contents_missing` | fail | fail | 1656 | Net contents absent from the artwork |
| `net_contents_wrong` | fail | fail | 1764 | 700 mL on the label, 750 mL on the application |
| `photo_compressed` | pass | flag ⚠ | 1951 | Heavily re-compressed JPEG, as arrives from email chains |
| `photo_glare` | pass | flag ⚠ | 1609 | Compliant label with specular glare across the upper third |
| `photo_skewed` | pass | pass | 1968 | Compliant label shot at an angle |
| `photo_skewed_and_defective` | fail | fail | 1943 | Angled shot AND a title-case warning -- degradation must not mask a real defect |
| `photo_soft_focus` | pass | flag ⚠ | 1664 | Compliant label, slightly out of focus |
| `proof_inconsistent` | fail | fail | 1661 | Label contradicts itself: 45% is 90 proof, not 80 |
| `v2_body_caps` | pass | pass | 1690 | Second template: whole statement in capitals; 16.22 regulates only the prefix |
| `v2_body_caps_not_bold` | flag | flag | 1706 | Second template: whole statement in capitals, prefix in regular weight |
| `v2_import_wrong_country` | fail | fail | 1678 | Second template: Scotch declared Scottish, label says Canada |
| `v2_malt_floz` | pass | pass | 1651 | Second template: '12 FL OZ' on the label, '355 mL' on the application |
| `v2_malt_floz_wrong` | fail | fail | 1600 | Second template: '16 FL OZ' on the label, '355 mL' on the application |
| `v2_photo_skewed` | pass | pass | 1851 | Second template: compliant wine photographed at an angle |
| `v2_title_case` | fail | fail | 1634 | Second template: title-case warning prefix |
| `v2_wine_clean` | pass | pass | 1665 | Second template: compliant wine, serif, web address under the warning |
| `v3_abv_wrong` | fail | fail | 1741 | Third template: stacked brand, label states 40% against 45% on the application |
| `v3_dark_label` | pass | pass | 1623 | Third template: light serif type on a dark label, brand on two lines |
| `v3_dark_title_case` | fail | fail | 1645 | Third template: dark label with a title-case warning prefix |
| `v3_import_agave` | pass | pass | 1542 | Third template: imported tequila; '100% Blue Agave' is the class, not the strength |
| `v3_large_scan` | pass | pass | 1740 | Third template: a 2700 x 3900 pixel scan |
| `v3_one_line_statement` | pass | pass | 1575 | Third template: net contents on the same line as the alcohol statement |
| `v3_stacked_brand` | pass | pass | 1636 | Third template: brand set on two lines in two sizes |
| `warning_microtype` | flag | flag | 1459 | Text buried at ~6pt -- too small to judge weight, must not guess |
| `warning_missing` | fail | fail | 1439 | No health warning statement at all |
| `warning_prefix_not_bold` | flag | flag | 1490 | Correct text, but the prefix is set in regular weight -- advisory only |
| `warning_reworded` | fail | fail | 1488 | Softened wording -- 'may wish to avoid' instead of 'should not drink' |
| `warning_title_case` | fail | fail | 1466 | 'Government Warning:' in title case -- the rejection Jenny caught |
