/**
 * PROTOTYPE — THROWAWAY. Delete or absorb once the question is answered.
 *
 * Question: does domain → Blitz (domain-to-linkedin → enrichment/company)
 * produce rich company data for real rows already in Supabase from the
 * Series A pipeline (funding_discoveries) and the PH scraper (product_launches),
 * and what PATCH payload shape lands back in each table?
 *
 * Run (from trigger/):   npx tsx src/prototype-blitz-enrich.ts
 * Flags:
 *   --apply          actually PATCH Supabase (default: dry-run, print only)
 *   --limit N        rows per table (default 5)
 *   --table X        only one table: funding | ph
 *
 * Env: loads ../../.env (workspace root: SUPABASE_*) and
 *      ../../gtm-orchestrator/.env (BLITZ_API_KEY_MITCHELL) internally.
 */

import { config as dotenv } from "dotenv";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
dotenv({ path: resolve(here, "../../../.env") }); // C:\Users\mitch\Everything_CC\.env
dotenv({ path: resolve(here, "../../.env") }); // repo root .env (if present)
dotenv({ path: resolve(here, "../../../gtm-orchestrator/.env") }); // BLITZ key

const BLITZ_BASE = "https://api.blitz-api.ai";
const BLITZ_KEY = process.env.BLITZ_API_KEY_MITCHELL ?? process.env.BLITZ_API_KEY ?? "";
const DISCOLIKE_BASE = "https://api.discolike.com/v1";
const DISCOLIKE_KEY = process.env.DISCOLIKE_API_KEY ?? "";
const SUPABASE_URL = (process.env.SUPABASE_PROJECT_URL || process.env.SUPABASE_URL || "").replace(/\/+$/, "");
const SUPABASE_KEY =
  process.env.SUPABASE_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.SUPABASE_ANON_KEY || "";

const APPLY = process.argv.includes("--apply");
const LIMIT = Number(process.argv[process.argv.indexOf("--limit") + 1]) || 5;
const ONLY = process.argv.includes("--table") ? process.argv[process.argv.indexOf("--table") + 1] : null;
// --before YYYY-MM-DD: sample rows discovered before this date (test index lag on older rows)
const BEFORE = process.argv.includes("--before") ? process.argv[process.argv.indexOf("--before") + 1] : null;

if (!BLITZ_KEY) throw new Error("BLITZ_API_KEY_MITCHELL not found in env");
if (!SUPABASE_URL || !SUPABASE_KEY) throw new Error("Supabase env not found");

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// ---------- Blitz calls (5 req/sec hard limit → 250ms between calls) ----------

async function blitzPost(path: string, body: unknown): Promise<any | null> {
  await sleep(250);
  const res = await fetch(`${BLITZ_BASE}${path}`, {
    method: "POST",
    headers: { "x-api-key": BLITZ_KEY, "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (res.status === 429) {
    console.log("    429 — waiting 60s once");
    await sleep(60_000);
    return blitzPost(path, body);
  }
  if (!res.ok) {
    console.log(`    Blitz ${path} → HTTP ${res.status}: ${(await res.text()).slice(0, 200)}`);
    return null;
  }
  return res.json();
}

interface BlitzCompany {
  linkedin_url?: string | null;
  name?: string | null;
  about?: string | null;
  specialties?: string[] | null;
  industry?: string | null;
  type?: string | null;
  size?: string | null; // e.g. "51-200"
  employees_on_linkedin?: number | null;
  followers?: number | null;
  founded_year?: number | null;
  hq?: { city?: string | null; state?: string | null; country_name?: string | null } | null;
  domain?: string | null;
  website?: string | null;
}

async function enrichDomain(
  domain: string,
  knownLinkedin?: string | null
): Promise<{ linkedin_url: string; company: BlitzCompany } | null> {
  let linkedinUrl = knownLinkedin ?? null;
  if (linkedinUrl) {
    console.log(`    using existing linkedin_url: ${linkedinUrl}`);
  } else {
    const d2l = await blitzPost("/v2/enrichment/domain-to-linkedin", { domain });
    if (!d2l?.found || !d2l.company_linkedin_url) {
      console.log("    domain-to-linkedin: no match");
      return null;
    }
    linkedinUrl = d2l.company_linkedin_url;
  }
  const ce = await blitzPost("/v2/enrichment/company", { company_linkedin_url: linkedinUrl });
  if (!ce?.found || !ce.company) {
    console.log("    enrichment/company: no match");
    return null;
  }
  return { linkedin_url: linkedinUrl!, company: ce.company as BlitzCompany };
}

// ---------- DiscoLike ($0.18 per /bizdata query — SSL-cert/web-crawl index) ----------

interface DiscoProfile {
  name: string | null;
  description: string | null;
  industry: string | null;
  location: string | null;
  linkedin_url: string | null;
  footprint_score: number | null;
}

async function discolikeProfile(domain: string): Promise<DiscoProfile | null> {
  const res = await fetch(`${DISCOLIKE_BASE}/bizdata?domain=${encodeURIComponent(domain)}`, {
    headers: { "x-discolike-key": DISCOLIKE_KEY },
  });
  if (!res.ok) {
    console.log(`    DiscoLike /bizdata → HTTP ${res.status}: ${(await res.text()).slice(0, 150)}`);
    return null;
  }
  const text = await res.text();
  let d: any;
  try {
    d = JSON.parse(text);
  } catch {
    return null; // empty/non-JSON body = not found
  }
  if (!d || (!d.name && !d.description && !d.industry_groups)) return null;

  // industry_groups: {label: confidence} — take top key
  let industry: string | null = null;
  if (d.industry_groups && typeof d.industry_groups === "object" && !Array.isArray(d.industry_groups)) {
    industry = Object.entries(d.industry_groups as Record<string, number>).sort((a, b) => b[1] - a[1])[0]?.[0] ?? null;
  }
  const addr = d.address ?? {};
  const location = [addr.city, addr.state, addr.country].filter(Boolean).join(", ") || null;
  const socials: string[] = Array.isArray(d.social_urls) ? d.social_urls : Object.values(d.social_urls ?? {});
  const linkedin = socials.find((u: string) => typeof u === "string" && u.includes("linkedin.com")) ?? null;

  return {
    name: d.name ?? null,
    description: d.description ?? null,
    industry,
    location,
    linkedin_url: linkedin,
    footprint_score: d.score ?? null,
  };
}

// ---------- Supabase ----------

async function sbGet(path: string): Promise<any[]> {
  const res = await fetch(`${SUPABASE_URL}/rest/v1/${path}`, {
    headers: { apikey: SUPABASE_KEY, authorization: `Bearer ${SUPABASE_KEY}` },
  });
  if (!res.ok) throw new Error(`Supabase GET ${path} → ${res.status}`);
  return res.json();
}

async function sbPatch(table: string, sourceUrl: string, payload: Record<string, unknown>): Promise<boolean> {
  const res = await fetch(`${SUPABASE_URL}/rest/v1/${table}?source_url=eq.${encodeURIComponent(sourceUrl)}`, {
    method: "PATCH",
    headers: { apikey: SUPABASE_KEY, authorization: `Bearer ${SUPABASE_KEY}`, "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) console.log(`    PATCH ${table} → ${res.status}: ${(await res.text()).slice(0, 200)}`);
  return res.ok;
}

// ---------- Field mapping (the actual thing being prototyped) ----------

/**
 * Wrong-match guard. Blitz's domain field echoes the input (its DB owns the
 * mapping), so domain comparison can't catch bad mappings like
 * mesoware.com -> "Meso America Inc". Compare names instead: any shared token
 * (len >= 3) or prefix containment counts as a match.
 */
function nameMatches(ours: string, theirs: string | null | undefined): boolean {
  if (!theirs) return false;
  const norm = (s: string) =>
    s.toLowerCase().replace(/[^a-z0-9 ]/g, " ").split(/\s+/).filter((t) => t.length >= 3);
  const a = norm(ours);
  const b = norm(theirs);
  const aJoined = a.join("");
  const bJoined = b.join("");
  if (aJoined && bJoined && (aJoined.includes(bJoined) || bJoined.includes(aJoined))) return true;
  return a.some((t) => b.some((u) => u.includes(t) || t.includes(u)));
}

function hqString(c: BlitzCompany): string | null {
  const parts = [c.hq?.city, c.hq?.state, c.hq?.country_name].filter(Boolean);
  return parts.length ? parts.join(", ") : null;
}

/** product_launches — columns already exist (Clay fills these today). Blitz drop-in. */
function toPhPayload(linkedinUrl: string, c: BlitzCompany) {
  return {
    employee_count: c.employees_on_linkedin ?? null,
    industry: c.industry ?? null,
    company_location: hqString(c),
    company_description: c.about ?? null,
    linkedin_followers: c.followers ?? null,
    linkedin_url: linkedinUrl,
  };
}

/** funding_discoveries — only industry/location exist today; rest = PROPOSED NEW COLUMNS. */
function toFundingPayload(linkedinUrl: string, c: BlitzCompany) {
  return {
    existing: {
      industry: c.industry ?? null,
      location: hqString(c),
    },
    proposed_new_columns: {
      linkedin_url: linkedinUrl,
      employee_count: c.employees_on_linkedin ?? null,
      employee_range: c.size ?? null,
      linkedin_followers: c.followers ?? null,
      company_description: c.about ?? null,
      founded_year: c.founded_year ?? null,
      company_type: c.type ?? null,
    },
  };
}

// ---------- Run ----------

interface Stat {
  table: string;
  name: string;
  domain: string;
  found: boolean;
  fieldsFilled: number;
  fieldsTotal: number;
}
const stats: Stat[] = [];
const discoStats: Stat[] = [];

async function runTable(label: "funding" | "ph") {
  const isFunding = label === "funding";
  const table = isFunding ? "funding_discoveries" : "product_launches";
  const domainCol = isFunding ? "company_domain" : "maker_website";
  console.log(`\n=== ${table} (last ${LIMIT} rows with ${domainCol}) ===`);

  const linkedinSelect = isFunding ? "" : ",linkedin_url";
  const beforeFilter = BEFORE ? `&discovered_date=lt.${BEFORE}` : "";
  const rows = await sbGet(
    `${table}?select=company_name,source_url,${domainCol}${linkedinSelect}&${domainCol}=not.is.null${beforeFilter}&order=created_at.desc&limit=${LIMIT}`
  );

  for (const row of rows) {
    const rawDomain: string = row[domainCol];
    const domain = rawDomain
      .replace(/^https?:\/\//, "")
      .replace(/^www\./, "")
      .split(/[/?#]/)[0];
    console.log(`\n• ${row.company_name}  (${domain})`);

    // DiscoLike head-to-head (runs on every row regardless of Blitz outcome)
    if (DISCOLIKE_KEY) {
      const dp = await discolikeProfile(domain);
      if (dp) {
        const dFilled = Object.values(dp).filter((v) => v !== null && v !== "").length;
        discoStats.push({ table, name: row.company_name, domain, found: true, fieldsFilled: dFilled, fieldsTotal: 6 });
        console.log(`    [discolike] name="${dp.name}" industry="${dp.industry}" loc="${dp.location}" linkedin=${dp.linkedin_url ?? "-"} score=${dp.footprint_score} desc_len=${dp.description?.length ?? 0}`);
      } else {
        discoStats.push({ table, name: row.company_name, domain, found: false, fieldsFilled: 0, fieldsTotal: 0 });
        console.log("    [discolike] NOT FOUND");
      }
    }

    const hit = await enrichDomain(domain, isFunding ? null : row.linkedin_url);
    if (!hit) {
      console.log("    [blitz] NOT FOUND");
      stats.push({ table, name: row.company_name, domain, found: false, fieldsFilled: 0, fieldsTotal: 0 });
      continue;
    }

    const trusted = nameMatches(row.company_name, hit.company.name);
    if (!trusted) {
      console.log(`    LOW CONFIDENCE — Blitz name "${hit.company.name}" vs ours "${row.company_name}" (excluded from --apply)`);
    }

    const payload = isFunding ? toFundingPayload(hit.linkedin_url, hit.company) : toPhPayload(hit.linkedin_url, hit.company);
    const flat = isFunding
      ? { ...(payload as any).existing, ...(payload as any).proposed_new_columns }
      : (payload as Record<string, unknown>);
    const filled = Object.values(flat).filter((v) => v !== null && v !== "").length;
    stats.push({ table, name: row.company_name, domain, found: true, fieldsFilled: filled, fieldsTotal: Object.keys(flat).length });

    console.log(JSON.stringify(payload, null, 2).replace(/^/gm, "    "));

    if (APPLY && trusted) {
      const patchBody = isFunding ? (payload as any).existing : flat; // funding: only existing cols are PATCH-able
      const ok = await sbPatch(table, row.source_url, patchBody);
      console.log(`    PATCH ${ok ? "OK" : "FAILED"}${isFunding ? " (existing cols only — new cols need migration)" : ""}`);
    }
  }
}

if (!ONLY || ONLY === "funding") await runTable("funding");
if (!ONLY || ONLY === "ph") await runTable("ph");

// ---------- Summary ----------

console.log("\n=== SUMMARY ===");
function summarize(label: string, all: Stat[]) {
  const byTable = new Map<string, Stat[]>();
  for (const s of all) byTable.set(s.table, [...(byTable.get(s.table) ?? []), s]);
  for (const [table, list] of byTable) {
    const found = list.filter((s) => s.found);
    const avgFill = found.length
      ? Math.round((found.reduce((a, s) => a + s.fieldsFilled / s.fieldsTotal, 0) / found.length) * 100)
      : 0;
    console.log(`[${label}] ${table}: ${found.length}/${list.length} found, avg field coverage ${avgFill}%`);
  }
}
summarize("blitz", stats);
if (discoStats.length) summarize("discolike", discoStats);
console.log(APPLY ? "\nMode: APPLIED to Supabase" : "\nMode: DRY-RUN (no writes). Re-run with --apply to PATCH.");
