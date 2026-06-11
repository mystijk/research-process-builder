/** PROTOTYPE — throwaway. Counts maker_website / linkedin_url fill rates in product_launches. */
import { config as dotenv } from "dotenv";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
dotenv({ path: resolve(here, "../../../.env") });

const URL_ = (process.env.SUPABASE_PROJECT_URL || process.env.SUPABASE_URL || "").replace(/\/+$/, "");
const KEY = process.env.SUPABASE_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.SUPABASE_ANON_KEY || "";

async function count(filter: string): Promise<number> {
  const res = await fetch(`${URL_}/rest/v1/product_launches?select=id&${filter}&limit=1`, {
    headers: { apikey: KEY, authorization: `Bearer ${KEY}`, prefer: "count=exact", range: "0-0" },
  });
  return Number(res.headers.get("content-range")?.split("/")[1] ?? -1);
}

const total = await count("id=gt.0");
const site = await count("maker_website=not.is.null");
const li = await count("linkedin_url=not.is.null");
const both = await count("maker_website=not.is.null&linkedin_url=not.is.null");
const last30Total = await count("discovered_date=gte.2026-05-11");
const last30Site = await count("discovered_date=gte.2026-05-11&maker_website=not.is.null");
const last30Li = await count("discovered_date=gte.2026-05-11&linkedin_url=not.is.null");
const enriched = await count("company_description=not.is.null");

console.log({ total, maker_website: site, linkedin_url: li, both, last30Total, last30Site, last30Li, clay_enriched: enriched });
