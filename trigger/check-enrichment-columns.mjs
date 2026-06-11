import { config } from "dotenv";
import { resolve } from "path";

config({ path: resolve("../../.env") });

const url = [process.env.SUPABASE_PROJECT_URL, process.env.SUPABASE_URL]
  .find((u) => u?.startsWith("http"))
  ?.replace(/\/+$/, "") ?? "";
const key = process.env.SUPABASE_ANON_KEY ?? process.env.SUPABASE_KEY ?? "";
const headers = { apikey: key, Authorization: `Bearer ${key}` };

for (const [table, cols] of [
  ["funding_discoveries", "linkedin_url,employee_count,employee_range,linkedin_followers,company_description,founded_year,company_type,enriched_by,enriched_at"],
  ["product_launches", "enriched_by,enriched_at,employee_count,company_description"],
]) {
  const resp = await fetch(`${url}/rest/v1/${table}?select=${cols}&limit=1`, { headers });
  console.log(`${table}: HTTP ${resp.status}${resp.ok ? " — columns OK" : " — " + (await resp.text()).slice(0, 150)}`);
}
