import { config } from "dotenv";
import { resolve } from "path";

config({ path: resolve("../../.env") });

const url = [process.env.SUPABASE_PROJECT_URL, process.env.SUPABASE_URL]
  .find((u) => u?.startsWith("http"))
  ?.replace(/\/+$/, "") ?? "";
const key = process.env.SUPABASE_ANON_KEY ?? process.env.SUPABASE_KEY ?? "";
const headers = { apikey: key, Authorization: `Bearer ${key}` };

for (const [table, domainCol] of [
  ["funding_discoveries", "company_domain"],
  ["product_launches", "maker_website"],
]) {
  const resp = await fetch(
    `${url}/rest/v1/${table}?select=company_name,${domainCol},linkedin_url&enriched_by=eq.miss:discolike&limit=30`,
    { headers }
  );
  const rows = await resp.json();
  console.log(`\n${table} misses (${rows.length}):`);
  for (const r of rows) console.log(`  ${r.company_name} | ${r[domainCol]} | linkedin=${r.linkedin_url ?? "-"}`);
}
