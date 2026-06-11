// Push BLITZ_API_KEY_MITCHELL + DISCOLIKE_API_KEY to Trigger.dev prod env.
// Loads keys from local .env files internally (never echoes values).
import { config } from "dotenv";
import { resolve } from "path";

config({ path: resolve("../../.env") }); // workspace root: DISCOLIKE_API_KEY, TRIGGER_SECRET_KEY
config({ path: resolve("../../gtm-orchestrator/.env") }); // BLITZ_API_KEY_MITCHELL

const triggerKey = process.env.TRIGGER_SECRET_KEY;
const projectRef = "proj_vvsvdbeeoiaausrkdiqp";

const vars = {
  BLITZ_API_KEY_MITCHELL: process.env.BLITZ_API_KEY_MITCHELL,
  DISCOLIKE_API_KEY: process.env.DISCOLIKE_API_KEY,
};

for (const [name, value] of Object.entries(vars)) {
  if (!value) {
    console.log(`SKIP ${name} — not found in local env`);
    continue;
  }
  const resp = await fetch(
    `https://api.trigger.dev/api/v1/projects/${projectRef}/envvars/prod`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${triggerKey}`, "Content-Type": "application/json" },
      body: JSON.stringify({ name, value }),
    }
  );
  const body = await resp.text();
  console.log(`${name}: HTTP ${resp.status} ${body.slice(0, 120)}`);
}
