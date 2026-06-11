/** PROTOTYPE — throwaway. Does raw DiscoLike API return cost data (headers/body)? */
import { config as dotenv } from "dotenv";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
dotenv({ path: resolve(here, "../../../.env") });
const KEY = process.env.DISCOLIKE_API_KEY ?? "";

const res = await fetch("https://api.discolike.com/v1/bizdata?domain=nylas.com", {
  headers: { "x-discolike-key": KEY },
});
console.log("status:", res.status);
console.log("--- headers ---");
for (const [k, v] of res.headers.entries()) console.log(`${k}: ${v}`);
const body = await res.json();
console.log("--- body keys ---");
console.log(Object.keys(body));
const costish = Object.keys(body).filter((k) => /cost|fee|credit|usage|spend|billing/i.test(k));
console.log("cost-like body fields:", costish.length ? costish : "none");
