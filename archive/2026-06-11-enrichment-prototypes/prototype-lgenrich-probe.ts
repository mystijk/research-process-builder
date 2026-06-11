/** PROTOTYPE — throwaway. Probe lg-free-enrichments API: health + find working key from env (prints names only, never values). */
import { config as dotenv } from "dotenv";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
dotenv({ path: resolve(here, "../../../.env") });
dotenv({ path: resolve(here, "../../../gtm-orchestrator/.env") });

const BASE = "https://lg-linkedin-enrich-l6qeugwwca-uc.a.run.app";

const health = await fetch(`${BASE}/health`);
console.log("health:", health.status, await health.text());

// candidate key env names (values never printed)
const candidates = Object.keys(process.env).filter((k) =>
  /ENRICH|LG_LINKEDIN|LINKEDIN_API|FREE_ENRICH|LG_API/i.test(k)
);
console.log("candidate env names:", candidates);

for (const name of candidates) {
  const key = process.env[name]!;
  const res = await fetch(`${BASE}/enrich/linkedin`, {
    method: "POST",
    headers: { "x-api-key": key, authorization: `Bearer ${key}`, "content-type": "application/json" },
    body: JSON.stringify({ domain: "stripe.com" }),
  });
  console.log(`${name}: HTTP ${res.status}`);
  if (res.ok) {
    const d: any = await res.json();
    console.log("  works! linkedin_url:", d.linkedin_url, "| employee_count:", d.firmographics?.employee_count);
    break;
  }
}
