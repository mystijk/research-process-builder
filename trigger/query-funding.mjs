import { config } from "dotenv";
import { resolve } from "path";

config({ path: resolve("../../.env") });

const url = process.env.SUPABASE_PROJECT_URL ?? process.env.SUPABASE_URL ?? "";
const key = process.env.SUPABASE_KEY ?? process.env.SUPABASE_SERVICE_ROLE_KEY ?? process.env.SUPABASE_ANON_KEY ?? "";

if (!url || !key) { console.log("SUPABASE not configured"); process.exit(1); }

const h = { apikey: key, Authorization: `Bearer ${key}` };

// Funding count
const r1 = await fetch(`${url}/rest/v1/funding_discoveries?select=id`, { headers: { ...h, Prefer: "count=exact" } });
console.log("funding_discoveries total:", r1.headers.get("content-range"));

// Round type breakdown
const r2 = await fetch(`${url}/rest/v1/funding_discoveries?select=round_type&limit=2000`, { headers: h });
const rows = await r2.json();
const types = {};
rows.forEach(r => { types[r.round_type] = (types[r.round_type]||0)+1; });
console.log("Round types:", JSON.stringify(types, null, 2));

// Sample recent
const r3 = await fetch(`${url}/rest/v1/funding_discoveries?select=company_name,round_type,amount_raised,industry,location,discovered_date&order=discovered_date.desc&limit=8`, { headers: h });
const sample = await r3.json();
console.log("\nRecent sample:\n", JSON.stringify(sample, null, 2));

// Product launches count
const r4 = await fetch(`${url}/rest/v1/product_launches?select=id`, { headers: { ...h, Prefer: "count=exact" } });
console.log("\nproduct_launches total:", r4.headers.get("content-range"));
