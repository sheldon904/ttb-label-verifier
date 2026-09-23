# Referral triage on the live deployment: `typesafe-ai/jev`

Measured on 2026-09-23 on https://ttb-label-verifier-opal.vercel.app, with Tesseract 5.5 and the second reading off. Every fixture of both sets went through `/api/review/example/{id}`. Each label the rules referred came back with Jev's estimate; no call fell back. The local heuristic's score is computed from the same responses.

A referral of a label that should have passed is a read problem and should score low. A referral of a label that needs a person is genuine and should score high.

| fixture | referral is | Jev | heuristic |
|---|---|---|---|
| `net_contents_centilitres` | genuine | 0.90 | 0.85 |
| `photo_soft_focus` | read problem | 0.89 | 0.85 |
| `brand_near_miss` | genuine | 0.88 | 0.85 |
| `ai_tequila_import` | read problem | 0.81 | 0.55 |
| `warning_microtype` | genuine | 0.77 | 0.55 |
| `warning_prefix_not_bold` | genuine | 0.41 | 0.55 |
| `v2_body_caps_not_bold` | genuine | 0.39 | 0.55 |
| `ai_beer` | genuine | 0.27 | 0.20 |
| `photo_compressed` | read problem | 0.25 | 0.20 |
| `ai_scotch_import` | read problem | 0.17 | 0.20 |
| `ai_beer_can_photo` | genuine | 0.16 | 0.20 |
| `ai_vodka_import` | read problem | 0.15 | 0.20 |
| `ai_photo_bar` | genuine | 0.14 | 0.20 |
| `ai_rum_photo_glare` | genuine | 0.14 | 0.20 |
| `ai_gin_arched` | read problem | 0.13 | 0.20 |
| `photo_glare` | read problem | 0.12 | 0.20 |
| `ai_photo_compliant` | read problem | 0.12 | 0.20 |
| `ai_malt_pint` | read problem | 0.11 | 0.20 |

9 genuine referrals and 9 read problems. Jev ranks a genuine referral ahead of a read problem in **72%** of pairs, with 0% ties. The heuristic does so in **46%**, with 41% ties.
