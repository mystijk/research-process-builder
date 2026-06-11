import { logger } from "@trigger.dev/sdk";

const DISCOLIKE_BASE = "https://api.discolike.com/v1";
const DISCOLIKE_KEY = process.env.DISCOLIKE_API_KEY ?? "";

export interface DiscoProfile {
  name: string | null;
  description: string | null;
  industry: string | null;
  location: string | null;
  linkedin_url: string | null;
  employees: number | null;
  footprint_score: number | null;
}

export function discolikeConfigured(): boolean {
  return Boolean(DISCOLIKE_KEY);
}

/**
 * Spend guard. `_meta.cost` on responses is a local CLI estimate, not billing —
 * GET /usage `month_to_date_spend` is authoritative. Call once per run before
 * fanning out; skip the run when within $5 of max_spend.
 */
export async function discolikeUsageOk(): Promise<boolean> {
  if (!DISCOLIKE_KEY) return false;
  try {
    const res = await fetch(`${DISCOLIKE_BASE}/usage`, {
      headers: { "x-discolike-key": DISCOLIKE_KEY },
      signal: AbortSignal.timeout(15_000),
    });
    if (!res.ok) {
      logger.warn(`DiscoLike /usage → HTTP ${res.status} — treating as not-ok`);
      return false;
    }
    const u = (await res.json()) as { month_to_date_spend?: number; max_spend?: number };
    const spend = u.month_to_date_spend ?? 0;
    const max = u.max_spend ?? 99;
    logger.info("DiscoLike usage", { month_to_date_spend: spend, max_spend: max });
    return spend < max - 5;
  } catch (e) {
    logger.warn(`DiscoLike /usage error: ${e instanceof Error ? e.message : String(e)}`);
    return false;
  }
}

/**
 * /bizdata lookup (~$0.18/query). Returns null on miss — API responds
 * HTTP 200 with an empty body when the domain isn't in the index.
 */
export async function discolikeProfile(domain: string): Promise<DiscoProfile | null> {
  if (!DISCOLIKE_KEY) return null;
  const res = await fetch(`${DISCOLIKE_BASE}/bizdata?domain=${encodeURIComponent(domain)}`, {
    headers: { "x-discolike-key": DISCOLIKE_KEY },
    signal: AbortSignal.timeout(30_000),
  });
  if (!res.ok) {
    logger.warn(`DiscoLike /bizdata → HTTP ${res.status}`, { domain });
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
    employees: typeof d.employees === "number" ? d.employees : null,
    footprint_score: d.score ?? null,
  };
}
