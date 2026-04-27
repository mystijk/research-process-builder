"""Anneal loop driver. Runs candidates and tracks scores."""
import json
import sys
import time
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
from openai import OpenAI

SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = SCRIPT_DIR.parent.parent.parent
load_dotenv(WORKSPACE_ROOT / ".env")

sys.path.insert(0, str(SCRIPT_DIR))
from score import score_prompt, BASELINE_SYSTEM, BASELINE_USER_TEMPLATE

CANDIDATES_DIR = SCRIPT_DIR / "candidates"
CANDIDATES_DIR.mkdir(exist_ok=True)
LOG_PATH = SCRIPT_DIR / "anneal_log.json"
TEST_CASES_PATH = SCRIPT_DIR / "test_cases.json"


def load_log():
    if LOG_PATH.exists():
        return json.loads(LOG_PATH.read_text(encoding="utf-8"))
    return {"runs": []}


def save_log(log):
    LOG_PATH.write_text(json.dumps(log, indent=2), encoding="utf-8")


def run_candidate(version, system, user_template, notes=""):
    cases = json.loads(TEST_CASES_PATH.read_text(encoding="utf-8"))["cases"]
    client = OpenAI()
    score, per_case, cost, t_in, t_out = score_prompt(system, user_template, cases, client, verbose=True)

    cand_path = CANDIDATES_DIR / f"{version}.json"
    cand_path.write_text(json.dumps({
        "version": version,
        "system": system,
        "user_template": user_template,
        "notes": notes,
    }, indent=2), encoding="utf-8")

    log = load_log()
    failures = [p["idx"] for p in per_case if p["score"] < 1.0]
    log["runs"].append({
        "version": version,
        "score": score,
        "cost": cost,
        "tokens_in": t_in,
        "tokens_out": t_out,
        "failing_idxs": failures,
        "notes": notes,
        "timestamp": datetime.utcnow().isoformat(),
    })
    save_log(log)
    print(f"\n=== {version}: {score:.4f} ({len(failures)} failures: {failures}) cost=${cost:.5f} ===")
    return score, per_case, cost


if __name__ == "__main__":
    # baseline
    if len(sys.argv) > 1 and sys.argv[1] == "baseline":
        run_candidate("v001-baseline", BASELINE_SYSTEM, BASELINE_USER_TEMPLATE, "baseline from pipeline_base.py")
