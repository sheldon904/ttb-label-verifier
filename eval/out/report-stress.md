# Stress test: degraded copies of compliant labels

210 copies: 14 compliant rendered labels under 15 degradations. Every copy is a compliant label, so a rejection is a harmful outcome and a referral is the safe answer.

| degradation | pass | referred | rejected | unreadable |
|---|---|---|---|---|
| blur 1.5 | 1 | 13 | 0 | 0 |
| blur 2.5 | 1 | 13 | 0 | 0 |
| blur 3.5 | 1 | 11 | 0 | 2 |
| shrink to 45% | 4 | 10 | 0 | 0 |
| shrink to 30% | 1 | 13 | 0 | 0 |
| JPEG quality 15 | 1 | 13 | 0 | 0 |
| JPEG quality 8 | 1 | 13 | 0 | 0 |
| rotate 3° | 4 | 10 | 0 | 0 |
| rotate -6° | 2 | 12 | 0 | 0 |
| half brightness | 13 | 0 | 0 | 1 |
| contrast 35% | 12 | 2 | 0 | 0 |
| noise | 10 | 4 | 0 | 0 |
| glare on the warning | 2 | 11 | 1 | 0 |
| glare mid-label | 4 | 1 | 9 | 0 |
| glare at the top | 4 | 10 | 0 | 0 |
| **all** | **61** | **136** | **10** | **3** |

## Rejections

| label | degradation | rows failed |
|---|---|---|
| `abv_no_proof` | glare mid-label | net_contents |
| `brand_case_difference` | glare mid-label | net_contents |
| `clean_01` | glare mid-label | net_contents |
| `clean_02` | glare mid-label | net_contents |
| `clean_03` | glare mid-label | net_contents |
| `v3_dark_label` | glare on the warning | government_warning |
| `v3_dark_label` | glare mid-label | class_type |
| `v3_import_agave` | glare mid-label | net_contents, bottler_name |
| `v3_large_scan` | glare mid-label | proof_consistency, net_contents |
| `v3_stacked_brand` | glare mid-label | net_contents |
