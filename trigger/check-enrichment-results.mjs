import { config } from "dotenv";
import { resolve } from "path";

config({ path: resolve("../../.env") });

const url = [process.env.SUPABASE_PROJECT_URL, process.env.SUPABASE_URL]
  .find((u) => u?.startsWith("http"))
  ?.replace(/\/+$/, "") ?? "";
const key = process.env.SUPABASE_ANON_KEY ?? process.env.SUPABASE_KEY ?? "";
const headers = { apikey: key, Authorization: `Bearer ${key}` };

for (const table of ["funding_discoveries", "product_launches"]) {
  const resp = await fetch(
    `${url}/rest/v1/${table}?select=enriched_by,company_name,employee_count,linkedin_followers,company_description&enriched_at=not.is.null&order=enriched_at.desc&limit=200`,
    { headers }
  );
  const rows = await resp.json();
  const byProvider = {};
  let withDesc = 0, withEmp = 0;
  for (const r of rows) {
    byProvider[r.enriched_by] = (byProvider[r.enriched_by] ?? 0) + 1;
    if (r.company_description) withDesc++;
    if (r.employee_count != null) withEmp++;
  }
  console.log(`\n${table}: ${rows.length} rows with enriched_at`);
  console.log("  by provider:", JSON.stringify(byProvider));
  console.log(`  description fill: ${withDesc}/${rows.length}, employee_count fill: ${withEmp}/${rows.length}`);
  for (const r of rows.filter((x) => x.enriched_by && !x.enriched_by.startsWith("miss")).slice(0, 3)) {
    console.log(`  sample: ${r.company_name} | ${r.enriched_by} | emp=${r.employee_count} | followers=${r.linkedin_followers} | desc=${(r.company_description ?? "").slice(0, 60)}`);
  }
}
