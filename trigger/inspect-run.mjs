import { config } from "dotenv";
import { resolve } from "path";

config({ path: resolve("../../.env") });

const key = process.env.TRIGGER_SECRET_KEY;
const runId = process.argv[2];

const resp = await fetch(`https://api.trigger.dev/api/v3/runs/${runId}`, {
  headers: { Authorization: `Bearer ${key}` },
});
console.log("Status:", resp.status);
const data = await resp.json();
console.log(JSON.stringify(data, null, 2).slice(0, 6000));
