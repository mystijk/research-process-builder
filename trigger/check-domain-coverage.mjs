import { config } from "dotenv";
import { resolve } from "path";

config({ path: resolve("../../.env") });

const url = [process.env.SUPABASE_PROJECT_URL, process.env.SUPABASE_URL]
  .find((u) => u?.startsWith("http"))
  ?.replace(/\/+$/, "") ?? "";
const key = process.env.SUPABASE_ANON_KEY ?? process.env.SUPABASE_KEY ?? "";
const headers = { apikey: key, Authorization: `Bearer ${key}` };

const resp = await fetch(
  `${url}/rest/v1/funding_discoveries?select=company_domain,discovered_by_pipeline,discovered_date&order=discovered_date.desc&limit=1000`,
  { headers }
);
const rows = await resp.json();

const bad = (d) => !d || d === "not_enriched" || d === "not_found" || d === "not_stated" || !d.includes(".");
let badCount = 0;
const byPipeline = {};
const byMonth = {};
for (const r of rows) {
  const isBad = bad(r.company_domain);
  if (isBad) badCount++;
  const p = r.discovered_by_pipeline ?? "?";
  byPipeline[p] = byPipeline[p] ?? { total: 0, bad: 0 };
  byPipeline[p].total++;
  if (isBad) byPipeline[p].bad++;
  const m = (r.discovered_date ?? "?").slice(0, 7);
  byMonth[m] = byMonth[m] ?? { total: 0, bad: 0 };
  byMonth[m].total++;
  if (isBad) byMonth[m].bad++;
}
console.log(`last ${rows.length} funding rows: ${badCount} missing/placeholder domain (${Math.round((badCount / rows.length) * 100)}%)`);
console.log("\nby pipeline:");
for (const [p, s] of Object.entries(byPipeline)) console.log(`  ${p}: ${s.bad}/${s.total} bad`);
console.log("\nby month:");
for (const [m, s] of Object.entries(byMonth).sort()) console.log(`  ${m}: ${s.bad}/${s.total} bad`);
