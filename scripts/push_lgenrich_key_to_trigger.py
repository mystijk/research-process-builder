"""Push LG_FREE_ENRICHMENTS_API_KEY from the LG Secrets Vault to Trigger.dev prod env.
Never prints the value.

Usage:
    py scripts/push_lgenrich_key_to_trigger.py
"""

import importlib.util
import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1].parent / ".env")

LG_PY = Path.home() / ".local" / "bin" / "lg.py"
spec = importlib.util.spec_from_file_location("lg", LG_PY)
lg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lg)

PROJECT_REF = "proj_vvsvdbeeoiaausrkdiqp"

trigger_key = os.environ.get("TRIGGER_SECRET_KEY", "")
if not trigger_key:
    print("ERROR: TRIGGER_SECRET_KEY not in workspace .env")
    sys.exit(1)

projects = json.loads((Path.home() / ".cache" / "lg-cli" / "projects.json").read_text())
value = lg.fetch_secret(projects["scraping"], "prod", "LG_FREE_ENRICHMENTS_API_KEY")
if not value:
    print("ERROR: key not fetchable from vault")
    sys.exit(1)

resp = requests.post(
    f"https://api.trigger.dev/api/v1/projects/{PROJECT_REF}/envvars/prod",
    headers={"Authorization": f"Bearer {trigger_key}", "Content-Type": "application/json"},
    json={"name": "LG_FREE_ENRICHMENTS_API_KEY", "value": value},
    timeout=30,
)
print(f"LG_FREE_ENRICHMENTS_API_KEY: HTTP {resp.status_code} {resp.text[:120]}")
