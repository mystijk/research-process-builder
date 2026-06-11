# Prototype verdict — Blitz enrichment for funding_discoveries + product_launches

**Question:** Does domain → Blitz (`/v2/enrichment/domain-to-linkedin` → `/v2/enrichment/company`)
produce rich company data for rows the Series A pipeline and PH scraper push to Supabase,
and what payload shape lands back in each table?

**Run:** `npx tsx src/prototype-blitz-enrich.ts` (from `trigger/`), `--apply` to PATCH, `--limit N`, `--table funding|ph`.
Env loaded internally from workspace root `.env` (Supabase) + `gtm-orchestrator/.env` (`BLITZ_API_KEY_MITCHELL`).

## Findings (2026-06-10, 10 rows per table)

| Table | Hit rate | Field coverage when found |
|---|---|---|
| funding_discoveries | 5/10 | 93% |
| product_launches | 2/10 | 83% |

1. **Data is rich when found** — description, industry, HQ, employee count, followers, founded year, LinkedIn URL. Full profile, free on Leads+ plan (no per-credit cost on these endpoints).
2. **Hit rate limited by freshness, not the API.** Misses are brand-new startups (opereit.ai, soffi.ai, seaticket.ai, monako.ai) not yet in Blitz's cached LinkedIn DB. These tables are *fresh-company feeds by design* → expect ~30–50% same-day hit rate. Mitigation: **delayed retry pass** (re-enrich NOT_FOUND rows after 7–14 days) and/or keep Clay as the same-day path with Blitz as free first attempt.
3. **Wrong-match risk is real.** Blitz's `domain` field echoes its own mapping, so domain comparison can't validate. Name check catches gross mismatches (Gemini/blog.google → "Google Bus Bangladesh" rejected) but loose token overlap lets "Mesoware" → "Meso America Inc" through. Production needs stricter similarity (min token length 5+, or GPT-4o-mini yes/no validation like the existing `validateDomainSemantic`).
4. **PH scraper's existing `linkedin_url` column** can skip `domain-to-linkedin` entirely when present (none in sample had it, but path is wired).

## Head-to-head: Blitz vs DiscoLike (same 20 rows, 2026-06-10)

| Table | Blitz | DiscoLike (`/bizdata`, $0.18/lookup) | Union |
|---|---|---|---|
| funding_discoveries | 5/10 (93% fields) | **7/10 (95% fields)** | 8/10 |
| product_launches | 2/10 (83%) | **0/10** | 2/10 |

- **DiscoLike wins on funded companies.** Found 3 fresh startups Blitz missed (Golden Analytics, Soffi, Titan) — SSL-cert/web-crawl index picks up new companies faster than Blitz's LinkedIn cache. Also returns clean legal names ("Pogo Technologies, Inc.") and a LinkedIn URL.
- **DiscoLike useless for PH launches.** 0/10 — PH products are micro/brand-new projects with no SSL/web footprint yet. Blitz (2/10) + Clay stays the path there.
- **Field gaps:** DiscoLike profile has no `employee_count` / `linkedin_followers`. But it returns `linkedin_url` → chain into Blitz `enrichment/company` (free) to fill those. Waterfall: **Blitz direct (free) → DiscoLike $0.18 → feed DiscoLike's linkedin_url back into Blitz company enrichment.**
- DiscoLike `/bizdata` returns HTTP 200 with empty body on miss — must guard JSON parse.

**Recommended design:** funding_discoveries = Blitz → DiscoLike → Blitz-via-linkedin waterfall (~$0.13 avg/row at 30% DiscoLike usage). product_launches = Blitz free pre-step, Clay unchanged as fallback; skip DiscoLike.

## Integration shape (if promoted)

- **product_launches:** drop-in — columns already exist (`employee_count`, `industry`, `company_location`, `company_description`, `linkedin_followers`, `linkedin_url`). Insert Blitz before/instead of Clay in `stage4ClayEnrich()` (`trigger/src/pipeline/product-launches-ph.ts:623`). Use `employees_on_linkedin` for `employee_count`.
- **funding_discoveries:** needs migration adding: `linkedin_url`, `employee_count`, `employee_range`, `linkedin_followers`, `company_description`, `founded_year`, `company_type`. `industry` + `location` already exist (migration 002). Hook after `enrichOneCompany()` in `trigger/src/pipeline/pipeline.ts`.
- Shared `blitz.ts` module in `trigger/src/pipeline/` with 250ms rate-limit spacing (5 req/s hard limit), 60s wait on 429.
- Add `BLITZ_API_KEY_MITCHELL` to Trigger.dev project env vars (`proj_vvsvdbeeoiaausrkdiqp`).
- Add a `blitz-retry` pass (weekly cron or tail of daily task) re-trying rows where enrichment fields are NULL and row age 7–14 days.

Delete this prototype (`prototype-blitz-enrich.ts` + this file) once the real integration lands.
