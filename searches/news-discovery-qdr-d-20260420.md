# Series A Discovery Test — 2026-04-20

**TBS filter:** `qdr:d`
**Total queries:** 20
**Ground truth:** 8 companies
**Cost:** ~$0.020

## Endpoint Comparison

| Endpoint | Queries | Results | GT Hits | Rate |
|----------|---------|---------|---------|------|
| news | 10 | 67 | 5 | 5/8 (62%) |
| search | 10 | 61 | 7 | 7/8 (88%) |

### news — found: Archangel Lightworks, Creao AI, Ethermed, Hata, Zenskar
**missed:** Spektr, Wamo, Capsule Security

### search — found: Archangel Lightworks, Capsule Security, Creao AI, Ethermed, Hata, Spektr, Zenskar
**missed:** Wamo

## Per-Query GT Hits

| Query | news | search |
|-------|------|------|
| q1_broad_series_a | Ethermed, Zenskar, Hata | Hata, Zenskar |
| q2_announcement_language | Archangel Lightworks, Hata, Ethermed | Hata, Archangel Lightworks |
| q3_thesaasnews | Zenskar, Ethermed, Creao AI | Ethermed, Zenskar, Creao AI, Capsule Security |
| q4_finsmes | Zenskar | Zenskar |
| q5_alleywatch | — | — |
| q6_press_wires | Hata | Hata |
| q7_vc_language | — | Zenskar |
| q8_european | — | — |
| q9_tech_press | — | — |
| q10_infotechlead | — | Zenskar, Spektr, Creao AI |