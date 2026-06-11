# Trigger.dev → Firecrawl Migration

**Date:** 2026-05-13  
**Status:** Ready to execute  
**Repo:** `research-process-builder/trigger/`  
**Prereq:** `FIRECRAWL_API_KEY` added to Trigger.dev environments (prod/staging/dev)

---

## What Calls Spider Today

Two files contain direct Spider API calls:

| File | Spider usage | Lines |
|------|-------------|-------|
| `src/pipeline/spider.ts` | Spider HTTP client module — imported by 3 other files | whole file |
| `src/signal-bank-daily.ts` | Inline `scrapeHomepage()` fn — not using spider.ts, calls api.spider.cloud directly | ~74–91, ~38 |

Importers of `pipeline/spider.ts`:
- `src/backfill-article-text.ts` → `import { fetchUrl } from "./pipeline/spider.js"`
- `src/pipeline/pipeline.ts` → `import { fetchUrl } from "./spider.js"` (used at lines ~202, 206 to fetch article text)
- `src/pipeline/product-launches-ph.ts` → `import { fetchUrl } from "./spider.js"`

---

## What to Build

### Step 1 — Replace `pipeline/spider.ts` with Firecrawl

Rewrite `src/pipeline/spider.ts` in-place. Same export signature (`fetchUrl`) so all importers need zero changes.

```typescript
// src/pipeline/spider.ts — AFTER (rename mentally to firecrawl.ts if desired, but keep filename for zero-import-churn)

const FIRECRAWL_API_KEY = process.env.FIRECRAWL_API_KEY ?? "";
const FC_BASE = "https://api.firecrawl.dev/v1";

interface FetchOptions {
  renderJs?: boolean;   // kept for call-site compat — FC handles JS natively, ignored
  waitForSecs?: number; // kept for compat — ignored
}

async function firecrawlFetch(url: string, timeoutMs: number): Promise<string | null> {
  const resp = await fetch(`${FC_BASE}/scrape`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${FIRECRAWL_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      url,
      formats: ["markdown"],
      onlyMainContent: true,
    }),
    signal: AbortSignal.timeout(timeoutMs),
  });

  if (!resp.ok) return null;

  const data = await resp.json() as { success: boolean; data?: { markdown?: string } };
  if (!data.success) return null;

  const content = data.data?.markdown ?? "";
  return content.length > 200 ? content.slice(0, 15_000) : null;
}

export async function fetchUrl(url: string, options?: FetchOptions): Promise<string | null> {
  if (FIRECRAWL_API_KEY) {
    try {
      const result = await firecrawlFetch(url, 30_000);
      if (result) return result;
    } catch { /* first attempt failed */ }

    try {
      const result = await firecrawlFetch(url, 60_000);
      if (result) return result;
    } catch { /* retry failed */ }
  }

  // Direct fetch fallback (no key or FC failed)
  try {
    const resp = await fetch(url, {
      headers: { "User-Agent": "Mozilla/5.0 (compatible; LeadGrow/1.0)" },
      signal: AbortSignal.timeout(15_000),
    });
    if (resp.ok) {
      const text = await resp.text();
      if (text.length > 200) return text.slice(0, 15_000);
    }
  } catch { /* all methods failed */ }

  return null;
}
```

**Key differences from Spider:**
- Endpoint: `api.firecrawl.dev/v1/scrape` (not `api.spider.cloud/crawl`)
- Auth: same `Bearer` pattern
- Request body: `{ url, formats: ["markdown"], onlyMainContent: true }` (not `{ url, limit, return_format }`)
- Response: `{ success: true, data: { markdown: "..." } }` (not array `[{ content }]`)
- `renderJs`/`waitForSecs` options dropped — FC handles JS natively, params silently ignored

---

### Step 2 — Fix `signal-bank-daily.ts` inline Spider call

Replace `scrapeHomepage()` fn (~lines 73–91) and remove `SPIDER_API_KEY` reference (~line 38).

```typescript
// REMOVE:
const SPIDER_API_KEY = process.env.SPIDER_API_KEY ?? "";

// REPLACE scrapeHomepage() with:
const FIRECRAWL_API_KEY = process.env.FIRECRAWL_API_KEY ?? "";

async function scrapeHomepage(domain: string): Promise<string | null> {
  if (!FIRECRAWL_API_KEY) return null;
  try {
    const resp = await fetch("https://api.firecrawl.dev/v1/scrape", {
      method: "POST",
      headers: { Authorization: `Bearer ${FIRECRAWL_API_KEY}`, "Content-Type": "application/json" },
      body: JSON.stringify({ url: `https://${domain}`, formats: ["markdown"], onlyMainContent: true }),
      signal: AbortSignal.timeout(25_000),
    });
    if (!resp.ok) return null;
    const data = await resp.json() as { success: boolean; data?: { markdown?: string } };
    const content = data.data?.markdown ?? "";
    return content.length > 150 ? content.slice(0, 8_000) : null;
  } catch {
    return null;
  }
}
```

Also update the guard at ~line 261: `if (!row.industry && SPIDER_API_KEY)` → `if (!row.industry && FIRECRAWL_API_KEY)`

---

### Step 3 — Add `FIRECRAWL_API_KEY` to Trigger.dev environments

```bash
cd C:\Users\mitch\Everything_CC\cli\leadgrow-trigger.dev-cli
bun run src/index.ts envvars import --from C:\Users\mitch\Everything_CC\.env --env prod --override
bun run src/index.ts envvars import --from C:\Users\mitch\Everything_CC\.env --env staging --override
bun run src/index.ts envvars import --from C:\Users\mitch\Everything_CC\.env --env dev --override
```

Or add manually in Trigger.dev dashboard under Project → Environment Variables.

---

### Step 4 — Deploy

```bash
cd C:\Users\mitch\Everything_CC\research-process-builder\trigger
npx trigger.dev@latest deploy
```

---

## Files Changed

| File | Change |
|------|--------|
| `src/pipeline/spider.ts` | Full rewrite — same `fetchUrl` export, FC internals |
| `src/signal-bank-daily.ts` | Replace `scrapeHomepage()` + `SPIDER_API_KEY` refs |

No other files need changes — importers use `fetchUrl` which keeps same signature.

---

## Done State

- `SPIDER_API_KEY` referenced in 0 trigger src files
- `fetchUrl` routes through FC (with direct HTTP fallback)
- `scrapeHomepage` in signal-bank-daily uses FC
- `FIRECRAWL_API_KEY` confirmed live in prod/staging/dev
- `npx trigger.dev deploy` succeeds
