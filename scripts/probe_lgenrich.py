"""Probe lg-free-enrichments API with the vault key. Tests /health + /enrich/linkedin
on known domains across size tiers. Never prints the key.

Usage:
    py scripts/probe_lgenrich.py [domain ...]
"""

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
if not KEY:
    print("ERROR: key not fetchable from vault")
    sys.exit(1)

domains = sys.argv[1:] or ["stripe.com", "browser-use.com", "getlago.com"]

health = requests.get(f"{BASE}/health", timeout=15)
print("health:", health.status_code, health.text[:120])

for domain in domains:
    resp = requests.post(
        f"{BASE}/enrich/linkedin",
        headers={"x-api-key": KEY, "Content-Type": "application/json"},
        json={"domain": domain},
        timeout=60,
    )
    print(f"\n=== {domain} -> HTTP {resp.status_code}")
    try:
        d = resp.json()
    except Exception:
        print(resp.text[:200])
        continue
    keep = {
        k: d.get(k)
        for k in (
            "name", "employee_count", "follower_count", "founded_year", "hq_location",
            "industry", "linkedin_url", "domain_verified", "resolution_method", "error",
        )
    }
    desc = d.get("description")
    keep["description_len"] = len(desc) if desc else 0
    print(json.dumps(keep, indent=2)[:900])
