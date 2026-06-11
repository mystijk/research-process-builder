import { config } from "dotenv";
import { resolve } from "path";

config({ path: resolve("../../.env") });

const key = process.env.TRIGGER_SECRET_KEY;
const taskId = "enrichment-retry-weekly";

if (!key) { console.error("TRIGGER_SECRET_KEY not set"); process.exit(1); }

const resp = await fetch(`https://api.trigger.dev/api/v1/tasks/${taskId}/trigger`, {
  method: "POST",
  headers: {
    Authorization: `Bearer ${key}`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ payload: { type: "MANUAL", timestamp: new Date().toISOString(), upcoming: [] } }),
});

const data = await resp.json();
if (!resp.ok) {
  console.error("Error:", resp.status, JSON.stringify(data, null, 2));
  process.exit(1);
}

console.log("Run triggered:", data.id);
