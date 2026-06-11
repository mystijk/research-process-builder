# HANDOFF — Company Enrichment for Series A + PH Pipelines (2026-06-10)

## Goal

Append rich company data (description, industry, employee count, location, LinkedIn, followers, founded year) to every row hitting Supabase from two Trigger.dev pipelines:

- **Series A finder** → `funding_discoveries` (tasks `series-a-daily` / `series-a-weekly`, `trigger/src/pipeline/pipeline.ts`)
- **PH scraper** → `product_launches` (task `product-launches-ph-daily`, `trigger/src/pipeline/product-launches-ph.ts`)

## What was done (prototype phase — complete)

Prototype harness built + run against live Supabase rows, three providers evaluated. Full empirical results in:

- `trigger/src/prototype-blitz-enrich.NOTES.md` — verdict doc (read this first)
- `trigger/src/prototype-blitz-enrich.ts` — head-to-head harness (Blitz + DiscoLike, dry-run default, `--apply`, `--limit N`, `--table funding|ph`, `--before YYYY-MM-DD`)
- `trigger/src/prototype-ph-fill-check.ts` — PH column fill-rate counter
- `trigger/src/prototype-discolike-cost-check.ts`, `trigger/src/prototype-lgenrich-probe.ts` — API probes

All prototypes throwaway — delete after real integration lands.

### Key findings

| Provider | funding_discoveries (fresh) | product_launches (fresh) | product_launches (30+ days old) |
|---|---|---|---|
| Blitz (free) | 5/10, 93% fields | 2/10 | 4/10 |
| DiscoLike (~$0.18/q, inside $99/mo allowance) | 7/10, 95% | **0/10** | **6/10, 92%** |

1. **Index lag is the story.** Both providers miss brand-new companies; DiscoLike catches even tiny startups once ~30 days old. Enrichment must be day-0 attempt + **delayed retry pass (~30 days)**.
2. **Clay enrichment on PH is dead** — `company_description` NULL on all 308 rows ever. Stage 4 webhook/callback loop (`stage4ClayEnrich`) has never landed data. Enrichment columns exist but empty. Root cause not yet diagnosed.
3. **PH fill rates:** `maker_website` 289/308 (94%), `linkedin_url` 31/308 (10%, dropping to 5% recently).
4. **Wrong-match risk:** Blitz `domain-to-linkedin` returns garbage on ambiguous domains (mesoware.com → "Meso America Inc", blog.google → "Google Bus Bangladesh"); its `domain` field echoes its own mapping so domain-compare can't validate. Name-token guard in prototype catches gross cases; production wants GPT yes/no validation (pattern exists: `validateDomainSemantic` in `trigger/src/pipeline/openai.ts`).
5. **DiscoLike `/bizdata` returns more than CLI docs claim** — `employees`, `revenue_range`, `business_model` in body. Returns HTTP 200 + empty body on miss (guard JSON parse). No per-call cost data; authoritative spend = `GET /usage` (`month_to_date_spend`). Auth: `x-discolike-key`, env `DISCOLIKE_API_KEY` (workspace root `.env`).
6. **Blitz:** base `https://api.blitz-api.ai`, header `x-api-key`, env `BLITZ_API_KEY_MITCHELL` (in `gtm-orchestrator/.env`), 5 req/s hard limit (250ms spacing, 60s wait on 429). Endpoints free on current plan. Reference: `C:\Users\mitch\Everything_CC\clients\gtm-client-heydigital\data\docs\blitz-api-reference.md`, SDK types in that repo's `node_modules/blitz-api-js`.

### Deferred: internal lg-free-enrichments API (BLOCKED on key, revisit later)

`https://lg-linkedin-enrich-l6qeugwwca-uc.a.run.app` — internal Cloud Run service (Charles's; spec gist: https://gist.github.com/charlesdr13/1f5f7c70c9d757685957a880941e77a2). `POST /enrich/linkedin {domain}` does homepage-scrape → LinkedIn extract → full firmographics incl. `employee_count`/`follower_count`, with `domain_verified` trust signal. `/enrich/batch` takes 100 domains. Would be PRIMARY provider (free, internal) once key found. Key NOT in workspace `.env`, gtm-orchestrator `.env`, or Infisical registry (`~/.lg-cli/registry.json`); no gcloud SDK/auth on machine. **User decision: skip for now, add later via GCP or Charles.**

## Agreed design (build this next)

**funding_discoveries:** day-0 in-pipeline Blitz attempt (free) → weekly/delayed DiscoLike pass over rows with NULL enrichment, age 7–30 days → chain DiscoLike `linkedin_url` into Blitz `enrichment/company` for followers. Needs migration adding: `linkedin_url`, `employee_count`, `employee_range`, `linkedin_followers`, `company_description`, `founded_year`, `company_type` (`industry`/`location` exist via migration 002).

**product_launches:** day-0 Blitz on `maker_website` (columns already exist: `employee_count`, `industry`, `company_location`, `company_description`, `linkedin_followers`) → delayed ~30-day DiscoLike pass. Junk-domain kill list needed (apps.apple.com, pages.dev etc. — reuse `isDomainBlocked` in `trigger/src/pipeline/domain-lookup.ts`). Clay path: diagnose or remove.

**Shared:** `trigger/src/pipeline/blitz.ts` + `discolike.ts` modules; DiscoLike `/usage` preflight each run (skip near `max_spend`); name-match or GPT validation gate before writes; provider designed as waterfall so lg-free-enrichments slots in as primary later. Add `BLITZ_API_KEY_MITCHELL` + `DISCOLIKE_API_KEY` to Trigger.dev project env (`proj_vvsvdbeeoiaausrkdiqp`) — see `lg-trigger` CLI / `reference_clay_trigger_integration` memory for env var workflow.

## Next session task list

1. Migration `trigger/supabase/migrations/00X_funding_enrichment_columns.sql`
2. `blitz.ts` + `discolike.ts` pipeline modules (lift logic from prototype)
3. Day-0 hooks in both pipelines
4. Delayed-pass task (new scheduled task, e.g. `enrichment-retry-weekly`) — consider `graduate-to-trigger` skill conventions
5. Trigger.dev env vars + deploy (`npx trigger.dev@4.4.6 deploy` from `trigger/`)
6. Validate on live rows, then delete `prototype-*` files
7. (Optional) diagnose dead Clay stage 4; (later) add lg-free-enrichments as primary

## Suggested skills

- `trigger-tasks` / `trigger-config` — new scheduled task + deploy
- `graduate-to-trigger` — conventions for promoting to scheduled monitor
- Spawn `smart-searcher`/Explore (Haiku) agents for file discovery before editing — worked well this session.

## Gotchas

- Hook blocks any shell command referencing `.env` — load env inside scripts via dotenv (see prototype header for the three .env paths).
- `py` not `python`; pnpm over npm; never delete — archive.
- Supabase prod = workspace 3; both tables upsert on `source_url`.
- DiscoLike CLI `_meta.cost` is a local estimate, not API billing.
