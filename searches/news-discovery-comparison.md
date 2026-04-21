# Series A Discovery — Endpoint Comparison Report

**date:** 2026-04-20
**ground truth:** 8 companies (7 actual Series A + 1 Seed control)
**cost:** $0.04 total (40 SerperDev queries) + 6 WebSearch queries

## Final Scoreboard

| Method | GT Hit Rate | Cost/Run | Time Filter | Verdict |
|--------|:----------:|:--------:|:-----------:|---------|
| **SerperDev Search + `qdr:d`** | **7/8 (88%)** | $0.01 | ✅ 24h gate | **WINNER — use this** |
| SerperDev News + `qdr:d` | 5/8 (62%) | $0.01 | ✅ 24h gate | Supplementary only |
| SerperDev Search + `qdr:w` | 7/8 (88%) | $0.01 | ✅ 7d gate | Weekly catch-up |
| SerperDev News + `qdr:w` | 6/8 (75%) | $0.01 | ✅ 7d gate | Better than daily news |
| WebSearch (no time filter) | ~4/8 (50%) | free | ❌ none | Too noisy, not viable |

## Why Search Beats News

SerperDev `/search` with `tbs:qdr:d` outperforms `/news` because:

1. **Aggregator pages rank higher in web search.** TheSaaSNews /news/series-a page surfaces as a web result but NOT as a news result — Google News treats it as a listing page, not a news article.
2. **InfotechLead roundups surface in web search.** These 3-company-per-article roundups get indexed as web pages, not news. InfotechLead alone found 3/8 GT companies via search, 0/8 via news.
3. **News endpoint filters too aggressively.** Google News prefers major outlets and editorialized articles. Small aggregators and press wire reposts get demoted.

## Recommended Architecture

**Primary:** SerperDev `/search` endpoint with `tbs: "qdr:d"` — run daily at 7am ET
**Supplementary:** SerperDev `/news` endpoint with `tbs: "qdr:d"` — run in parallel, catches editorial coverage
**Catch-up:** SerperDev `/search` with `tbs: "qdr:w"` — run weekly on Monday, catches anything daily missed

**Combined daily (search + news):** 20 queries = $0.02/day = **$0.60/month**

## Per-Query Performance (Search Endpoint, `qdr:d`)

| Query | GT Hits | Companies Found | Verdict |
|-------|:-------:|-----------------|---------|
| q1 broad sweep | 2 | Hata, Zenskar | KEEP — catches press wire coverage |
| q2 announcement language | 2 | Hata, Archangel Lightworks | KEEP — catches niche sector |
| q3 TheSaaSNews | **4** | Ethermed, Zenskar, Creao AI, Capsule Security | **BEST QUERY** — single source, 4 hits |
| q4 FinSMEs | 1 | Zenskar | KEEP — overlap but catches different articles |
| q5 AlleyWatch | 0 | — | WEAK daily, better weekly |
| q6 press wires | 1 | Hata | KEEP — only source for APAC deals |
| q7 VC language | 1 | Zenskar | MARGINAL — expensive for 1 hit |
| q8 European | 0 | — | FAILED on qdr:d, works on qdr:w (got Wamo) |
| q9 tech press | 0 | — | KILL on qdr:d (0 results returned) |
| q10 InfotechLead | **3** | Zenskar, Spektr, Creao AI | **SECOND BEST** — daily roundup format |

## Optimized Query Set (based on results)

Drop q9 (0 results). Promote q3 and q10. Add VCNewsDaily.

**Recommended 8-query daily set:**
1. q3 TheSaaSNews (4 hits)
2. q10 InfotechLead (3 hits)
3. q1 broad sweep (2 hits)
4. q2 announcement language (2 hits)
5. q6 press wires (1 hit — APAC coverage)
6. q4 FinSMEs (1 hit)
7. q8 European (keep for weekly, optional daily)
8. NEW: `site:vcnewsdaily.com Series A` (untested but appeared in WebSearch results)

**Total: 8 queries × $0.001 = $0.008/day = $0.24/month**

## GT Company Discovery Breakdown

| Company | Amount | Search qdr:d | News qdr:d | Search qdr:w | Discovered By |
|---------|--------|:------------:|:----------:|:------------:|---------------|
| Zenskar | $15M | ✅ (q1,q3,q4,q7,q10) | ✅ (q1,q3,q4) | ✅ | 5 queries found it |
| Spektr | $20M | ✅ (q10) | ❌ | ✅ (q1,q3,q6,q8,q10) | InfotechLead only on daily |
| Ethermed | $8.5M | ✅ (q3) | ✅ (q1,q2,q3) | ✅ | TheSaaSNews primary |
| Hata | $8M | ✅ (q1,q2,q6) | ✅ (q1,q2,q6) | ✅ | Press wires + broad sweep |
| Archangel Lightworks | £10M | ✅ (q2) | ✅ (q2) | ✅ | Announcement language only |
| Wamo | €10M | ❌ | ❌ | ✅ (q8) | **EU gap — only found weekly** |
| Creao AI | $10M | ✅ (q3,q10) | ✅ (q3) | ✅ | TheSaaSNews + InfotechLead |
| Capsule Security | $7M | ✅ (q3) | ❌ | ❌ | TheSaaSNews only (Seed, not Series A) |

## Remaining Gaps

1. **European deals on daily cadence.** Wamo only found with `qdr:w`. EU-Startups and Tech.eu don't surface well with `qdr:d`. Fix: add `site:tech.eu OR site:fintech.global funding` query.
2. **APAC crypto deals.** Hata found but only via press wires (EQS News). Fix: press wire query (q6) covers this.
3. **Niche sector deals.** Archangel Lightworks only found via announcement language (q2). No aggregator covered it. Accept this — niche sectors require broad sweep queries.

## Key Learning

**Aggregator-first, broad-sweep-second.** TheSaaSNews and InfotechLead alone found 6/8 companies. The remaining 2 (Hata, Archangel Lightworks) needed broad sweep queries. The pipeline should:
1. Hit aggregator sources first (q3, q10, q4)
2. Then run broad sweeps (q1, q2)
3. Then press wires for non-US coverage (q6)
4. Weekly catch-up for EU gap (q8 with qdr:w)
