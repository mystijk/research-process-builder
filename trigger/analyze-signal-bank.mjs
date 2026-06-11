import { config } from "dotenv";
import { resolve } from "path";
config({ path: resolve("../../.env") });

const url = process.env.SUPABASE_PROJECT_URL ?? process.env.SUPABASE_URL ?? "";
const key = process.env.SUPABASE_KEY ?? process.env.SUPABASE_SERVICE_ROLE_KEY ?? process.env.SUPABASE_ANON_KEY ?? "";
if (!url || !key) { console.log("SUPABASE not configured. URL:", !!url, "Key:", !!key); process.exit(1); }
const h = { apikey: key, Authorization: `Bearer ${key}` };

async function q(path) {
  const r = await fetch(`${url}/rest/v1/${path}`, { headers: h });
  const data = await r.json();
  if (!Array.isArray(data)) { console.error("ERROR:", JSON.stringify(data)); return []; }
  return data;
}

// Full dataset
const all = await q("funding_discoveries?select=company_name,company_domain,round_type,industry,location,discovered_date&limit=1000");
console.log(`Total fetched: ${all.length}`);

// Industry breakdown
const industries = {};
all.forEach(r => { const i = r.industry || "(none)"; industries[i] = (industries[i]||0)+1; });
const sorted = Object.entries(industries).sort((a,b) => b[1]-a[1]);
console.log("\n=== INDUSTRIES ===");
sorted.slice(0,30).forEach(([k,v]) => console.log(`  ${k}: ${v}`));
console.log(`  Total with industry: ${all.filter(r=>r.industry).length}`);

// Location breakdown
const locs = {};
all.forEach(r => { const l = (r.location||"(none)").split(",")[0].trim(); locs[l] = (locs[l]||0)+1; });
const sortedLocs = Object.entries(locs).sort((a,b) => b[1]-a[1]);
console.log("\n=== TOP LOCATIONS ===");
sortedLocs.slice(0,20).forEach(([k,v]) => console.log(`  ${k}: ${v}`));

// Sample companies WITH domain
const withDomain = all.filter(r => r.company_domain);
console.log(`\n=== DOMAINS: ${withDomain.length}/${all.length} have domain ===`);
console.log("Sample:", withDomain.slice(0,15).map(r=>`${r.company_name}|${r.company_domain}|${r.round_type}`).join("\n  "));

// Round type filtered: just A, Seed, B for core targets
const target = all.filter(r => ["Series A","Series B","Seed","Pre-Seed"].includes(r.round_type));
console.log(`\nCore signal rounds (A/B/Seed/Pre-Seed): ${target.length}`);
