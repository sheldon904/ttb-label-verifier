# Evaluation report: `ocr:tesseract`

**37 fixtures · 100.0% verdict accuracy**

OCR engine: Tesseract 5.4.0.20240606.

## Outcome safety

A single accuracy number hides the distinction that matters here: escalating a compliant label costs an agent a minute, whereas rejecting one tells an applicant they broke the law when they did not.

| outcome | count |
|---|---|
| Correct | 37 |
| Referred to a human when not strictly needed | 0 |
| Defective, referred to a human instead of rejected | 0 |
| **Wrong in a way that harms someone** | **0** |

## Latency and throughput

These are two different numbers and conflating them is misleading. Sarah Chen's five second budget is about an agent waiting on **one** label, so it must be measured without contention. Batch is a throughput question: under load, per-label wall clock rises while labels per minute improves.

Measured at concurrency **1** (interactive).

| p50 | p95 | p99 | max |
|---|---|---|---|
| 1153 ms | 5956 ms | 7037 ms | 7037 ms |

Interactive target is < 5 000 ms. **p95 MISSED.**

Throughput: **35 labels/min** (37 in 63.5s). A 300-label batch would take about **8.6 minutes** at this concurrency.

## Verdict confusion matrix

| expected \ actual | pass | flag | fail |
|---|---|---|---|
| **pass** | 19 | 0 | 0 |
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

## Second opinion (`google/gemini-3.8-flash`)

Consulted on 4 referred label(s); cleared rows on 4. A cleared row is a PASS the agent confirms on the artwork; a second reading can never produce a FAIL.

Cost: $0.0087 in total, $0.0022 per consulted label, as reported by the provider.

Slowest consulted label: 7037 ms (`warning_microtype`), OCR and the second reading together. On the page the OCR result is shown first and the second reading replaces it when it arrives.

| fixture | expected | rows cleared |
|---|---|---|
| `photo_compressed` | pass | government_warning |
| `photo_glare` | pass | brand_name, class_type, alcohol_content, proof_consistency |
| `photo_soft_focus` | pass | government_warning, warning_typography |
| `warning_microtype` | flag | government_warning |

## Referral triage (`heuristic`)

Triage orders referrals; it never changes a verdict. A referral of a label that should have passed is a read problem, and should score low. A referral of a label that genuinely needs a person should score high.

| fixture | referral is | chance of a genuine defect |
|---|---|---|
| `brand_near_miss` | genuine | 0.85 |
| `v2_body_caps_not_bold` | genuine | 0.55 |
| `warning_microtype` | genuine | 0.55 |
| `warning_prefix_not_bold` | genuine | 0.55 |

## Cost

OCR and the rules cost nothing per label: no model, no API and no token, only the local CPU time in the latency table above. The second reading is the one paid step. Only referred labels go to it, and its cost is stated above.

## Rows failed in error

A row that fails when the fixture was not built to fail it tells an applicant something is wrong that is not, even if the label fails for another reason. Counted as harmful above.

None.

## Misses (0)

None.

## All fixtures

| fixture | expected | actual | ms | description |
|---|---|---|---|---|
| `abv_mismatch` | fail | fail | 1102 | Label states 40%, application says 45% |
| `abv_no_proof` | pass | pass | 1108 | ABV only, no proof statement -- perfectly legal |
| `brand_case_difference` | pass | pass | 1099 | Label is all caps, application is title case. Dave: 'obviously the same thing.' |
| `brand_near_miss` | flag | flag | 1092 | One character apart -- ambiguous, must escalate rather than guess |
| `brand_wrong` | fail | fail | 1069 | Entirely different brand on the artwork |
| `clean_01` | pass | pass | 1102 | Compliant label, Old Tom Distillery |
| `clean_02` | pass | pass | 1116 | Compliant label, Stone'S Throw |
| `clean_03` | pass | pass | 1248 | Compliant label, Copper Ridge Reserve |
| `net_contents_centilitres` | pass | pass | 1267 | '75 cl' on an import against '750 mL' on the application -- equivalent |
| `net_contents_missing` | fail | fail | 1152 | Net contents absent from the artwork |
| `net_contents_wrong` | fail | fail | 1184 | 700 mL on the label, 750 mL on the application |
| `photo_compressed` | pass | pass | 5956 | Heavily re-compressed JPEG, as arrives from email chains |
| `photo_glare` | pass | pass | 5167 | Compliant label with specular glare across the upper third |
| `photo_skewed` | pass | pass | 1462 | Compliant label shot at an angle |
| `photo_skewed_and_defective` | fail | fail | 1315 | Angled shot AND a title-case warning -- degradation must not mask a real defect |
| `photo_soft_focus` | pass | pass | 6251 | Compliant label, slightly out of focus |
| `proof_inconsistent` | fail | fail | 1179 | Label contradicts itself: 45% is 90 proof, not 80 |
| `v2_body_caps` | pass | pass | 1172 | Second template: whole statement in capitals; 16.22 regulates only the prefix |
| `v2_body_caps_not_bold` | flag | flag | 1090 | Second template: whole statement in capitals, prefix in regular weight |
| `v2_import_wrong_country` | fail | fail | 1134 | Second template: Scotch declared Scottish, label says Canada |
| `v2_malt_floz` | pass | pass | 1076 | Second template: '12 FL OZ' on the label, '355 mL' on the application |
| `v2_malt_floz_wrong` | fail | fail | 1092 | Second template: '16 FL OZ' on the label, '355 mL' on the application |
| `v2_photo_skewed` | pass | pass | 1365 | Second template: compliant wine photographed at an angle |
| `v2_title_case` | fail | fail | 1215 | Second template: title-case warning prefix |
| `v2_wine_clean` | pass | pass | 1153 | Second template: compliant wine, serif, web address under the warning |
| `v3_abv_wrong` | fail | fail | 1098 | Third template: stacked brand, label states 40% against 45% on the application |
| `v3_dark_label` | pass | pass | 1077 | Third template: light serif type on a dark label, brand on two lines |
| `v3_dark_title_case` | fail | fail | 1066 | Third template: dark label with a title-case warning prefix |
| `v3_import_agave` | pass | pass | 1039 | Third template: imported tequila; '100% Blue Agave' is the class, not the strength |
| `v3_large_scan` | pass | pass | 1161 | Third template: a 2700 x 3900 pixel scan |
| `v3_one_line_statement` | pass | pass | 1060 | Third template: net contents on the same line as the alcohol statement |
| `v3_stacked_brand` | pass | pass | 1067 | Third template: brand set on two lines in two sizes |
| `warning_microtype` | flag | flag | 7037 | Text buried at ~6pt -- too small to judge weight, must not guess |
| `warning_missing` | fail | fail | 1346 | No health warning statement at all |
| `warning_prefix_not_bold` | flag | flag | 1551 | Correct text, but the prefix is set in regular weight -- advisory only |
| `warning_reworded` | fail | fail | 1330 | Softened wording -- 'may wish to avoid' instead of 'should not drink' |
| `warning_title_case` | fail | fail | 1433 | 'Government Warning:' in title case -- the rejection Jenny caught |
