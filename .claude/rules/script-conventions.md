---
description: Use py not python, single braces in GPT templates, 1-based batch indexing
globs: ["scripts/**", "prompts/**"]
---

# Script Conventions

- **`py` not `python`** — Windows default throughout all scripts and docs.
- **Single braces in GPT templates** — extraction prompt uses `.replace("{items}", payload)`, not f-strings. JSON examples inside template need literal braces.
- **1-based local batch idx** — model returns local idx, code maps `batch[local_idx-1]["idx"]` back to global. Keep this contract.
