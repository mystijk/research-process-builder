"""Dump raw lg-free-enrichments /enrich/linkedin response for one domain. Never prints key."""

import importlib.util
import json
import sys
from pathlib import Path

import requests

LG_PY = Path.home() / ".local" / "bin" / "lg.py"
spec = importlib.util.spec_from_file_location("lg", LG_PY)
lg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lg)

BASE = "https://lg-linkedin-enrich-l6qeugwwca-uc.a.run.app"
projects = json.loads((Path.home() / ".cache" / "lg-cli" / "projects.json").read_text())
KEY = lg.fetch_secret(projects["scraping"], "prod", "LG_FREE_ENRICHMENTS_API_KEY")

domain = sys.argv[1] if len(sys.argv) > 1 else "stripe.com"
resp = requests.post(
    f"{BASE}/enrich/linkedin",
    headers={"x-api-key": KEY, "Content-Type": "application/json"},
    json={"domain": domain},
    timeout=60,
)
print(resp.status_code)
print(json.dumps(resp.json(), indent=2)[:3000])
