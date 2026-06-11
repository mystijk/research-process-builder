import { config } from "dotenv";
import { resolve } from "path";

config({ path: resolve("../../.env") });

const key = process.env.TRIGGER_SECRET_KEY;
const task = process.argv[2] ?? "product-launches-ph-daily";

const resp = await fetch(
  `https://api.trigger.dev/api/v1/runs?filter[taskIdentifier]=${task}&page[size]=10`,
  { headers: { Authorization: `Bearer ${key}` } }
);

console.log("Status:", resp.status);
const data = await resp.json();
for (const r of data.data ?? []) {
  console.log(`${r.id}  ${r.status}  created=${r.createdAt}  dur=${r.durationMs}ms  v=${r.version}`);
}
