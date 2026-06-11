import { config } from "dotenv";
import { resolve } from "path";
config({ path: resolve("../../.env") });

const url = process.env.SUPABASE_PROJECT_URL ?? process.env.SUPABASE_URL ?? "";
const key = process.env.SUPABASE_KEY ?? process.env.SUPABASE_SERVICE_ROLE_KEY ?? process.env.SUPABASE_ANON_KEY ?? "";
if (!url || !key) { console.log("SUPABASE not configured"); process.exit(1); }
const h = { apikey: key, Authorization: `Bearer ${key}` };

// Get all companies with full data, Series A/B/Seed priority
const r = await fetch(`${url}/rest/v1/funding_discoveries?select=company_name,company_domain,round_type,amount_raised,industry,location,discovered_date&order=discovered_date.desc&limit=1000`, { headers: h });
const all = await r.json();
if (!Array.isArray(all)) { console.error("Error:", JSON.stringify(all)); process.exit(1); }

// Filter to core rounds
const core = all.filter(r => ["Series A","Series B","Seed","Pre-Seed"].includes(r.round_type));
const seriesA = core.filter(r => r.round_type === "Series A");

console.log(`All: ${all.length}, Core rounds: ${core.length}, Series A: ${seriesA.length}`);

// Domain list for DiscoLike seeding - Series A companies that look like B2B SaaS
// Filter heuristically: exclude obvious non-B2B-SaaS industries
const nonTarget = ["Biotechnology","Healthcare","Medical Technology","Space Technology","Defense & Security",
  "Food & Agriculture","Environmental Technology","Energy","Robotics & Automation"];
const targetable = core.filter(r => {
  if (!r.industry) return false; // need some signal
  return !nonTarget.some(nt => r.industry.includes(nt));
});

console.log(`\nTargetable (have industry, not deep-tech): ${targetable.length}`);
console.log("Industry breakdown:");
const ind = {};
targetable.forEach(r => { ind[r.industry] = (ind[r.industry]||0)+1; });
Object.entries(ind).sort((a,b)=>b[1]-a[1]).forEach(([k,v]) => console.log(`  ${k}: ${v}`));

console.log("\nSample targetable companies:");
targetable.slice(0,20).forEach(r => console.log(`  ${r.company_name} | ${r.round_type} | ${r.industry} | ${r.company_domain}`));

// Also print NO-industry companies (we need to scrape these)
const noIndustry = core.filter(r => !r.industry);
console.log(`\nNo-industry core companies: ${noIndustry.length} (need homepage scraping)`);
console.log("Sample (Series A no industry):");
seriesA.filter(r=>!r.industry).slice(0,15).forEach(r => console.log(`  ${r.company_name} | ${r.company_domain} | ${r.discovered_date}`));

// Export domain list for DiscoLike
const discoSeeds = targetable
  .filter(r => ["AI, Software & SaaS","Software & SaaS","AI","Technology","AI, Marketing & Advertising","Fintech","AI, Data & Analytics"].includes(r.industry))
  .map(r => r.company_domain)
  .filter(Boolean)
  .slice(0,30);
console.log(`\nDiscoLike seed domains (top B2B SaaS signal companies):`);
discoSeeds.forEach(d => console.log(`  ${d}`));
