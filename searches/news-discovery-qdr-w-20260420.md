# Series A Discovery Test — 2026-04-20

**TBS filter:** `qdr:w`
**Total queries:** 20
**Ground truth:** 8 companies
**Cost:** ~$0.020

## Endpoint Comparison

| Endpoint | Queries | Results | GT Hits | Rate |
|----------|---------|---------|---------|------|
| news | 10 | 96 | 6 | 6/8 (75%) |
| search | 10 | 92 | 7 | 7/8 (88%) |

### news — found: Archangel Lightworks, Ethermed, Hata, Spektr, Wamo, Zenskar
**missed:** Creao AI, Capsule Security

### search — found: Archangel Lightworks, Creao AI, Ethermed, Hata, Spektr, Wamo, Zenskar
**missed:** Capsule Security

## Per-Query GT Hits

| Query | news | search |
|-------|------|------|
| q1_broad_series_a | Spektr | Archangel Lightworks, Spektr, Zenskar, Ethermed |
| q2_announcement_language | Archangel Lightworks, Hata | Hata, Archangel Lightworks |
| q3_thesaasnews | Zenskar, Ethermed | Ethermed, Zenskar, Spektr, Creao AI |
| q4_finsmes | — | Ethermed |
| q5_alleywatch | — | Zenskar |
| q6_press_wires | Zenskar, Spektr | Zenskar, Spektr |
| q7_vc_language | — | — |
| q8_european | Wamo | Spektr, Wamo |
| q9_tech_press | — | Zenskar |
| q10_infotechlead | Spektr | Spektr, Zenskar, Creao AI |