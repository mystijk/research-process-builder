import { config } from "dotenv";
import { resolve } from "path";

config({ path: resolve("../../.env") });

const key = process.env.TRIGGER_SECRET_KEY;
const auth = { Authorization: `Bearer ${key}` };

const s = await (await fetch("https://api.trigger.dev/api/v1/schedules?perPage=50", { headers: auth })).json();
for (const sc of s.data ?? []) {
  console.log(
    `${sc.task} | ${sc.generator?.expression ?? "?"} ${sc.timezone ?? ""} | active=${sc.active} | next=${sc.nextRun ?? "?"}`
  );
}
