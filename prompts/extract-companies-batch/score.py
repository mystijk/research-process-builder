"""Scorer for extract-companies-batch prompt anneal loop.

Usage:
    python score.py                       # score baseline
    python score.py --prompt path.json    # score a candidate prompt JSON {system, user_template}
    python score.py --candidate-id v002   # score from candidates/v002.json
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = SCRIPT_DIR.parent.parent.parent  # research-process-builder/.. = Everything_CC

load_dotenv(WORKSPACE_ROOT / ".env")

MODEL = "gpt-4o-mini"
BATCH_SIZE = 25
PRICE_IN = 0.15 / 1_000_000
PRICE_OUT = 0.60 / 1_000_000

TEST_CASES_PATH = SCRIPT_DIR / "test_cases.json"

BASELINE_SYSTEM = "You extract structured data. Output strict JSON."

BASELINE_USER_TEMPLATE = """For each numbered news item, identify the COMPANY THAT RAISED FUNDING.
The company is usually the subject of a verb like raises/secures/closes/announces/eyes/snags/lands.
Read both TITLE and SNIPPET — the snippet often names the company when the title is generic
(e.g. title "TechCrunch Mobility: Elon's admission" but snippet starts "A&K Robotics raised $8M").
NEVER return the investor / VC firm. NEVER return a publication name (TechCrunch, AI Market Watch, FemWealth).
If the item is a roundup / column / multi-company piece with no single subject, return null.
If it isn't a funding announcement at all, set is_funding=false and company=null.

Return STRICT JSON: {{"results":[{{"idx":1,"company":"Auth0","is_funding":true}},...]}}

Items:
{items}"""


def normalize_company(s):
    if s is None:
        return None
    if isinstance(s, str):
        s = s.strip()
        if s == "" or s.lower() in ("null", "none"):
            return None
        return re.sub(r"\s+", " ", s).lower()
    return None


def format_items(cases):
    lines = []
    for i, c in enumerate(cases, 1):
        title = (c.get("title") or "").replace("\n", " ").strip()
        snippet = (c.get("snippet") or "").replace("\n", " ").strip()
        lines.append(f"[{i}] TITLE: {title} | SNIPPET: {snippet}")
    return "\n".join(lines)


def call_model(client, system, user, model=MODEL):
    resp = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        max_tokens=2000,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    content = resp.choices[0].message.content
    usage = resp.usage
    return content, usage.prompt_tokens, usage.completion_tokens


def score_prompt(system, user_template, cases, client, verbose=False):
    """Score a prompt against all cases. Returns (total_score, per_case, cost, tokens_in, tokens_out)."""
    results_by_idx = {}
    total_in = 0
    total_out = 0

    for batch_start in range(0, len(cases), BATCH_SIZE):
        batch = cases[batch_start:batch_start + BATCH_SIZE]
        items_str = format_items(batch)
        user = user_template.replace("{items}", items_str)

        for attempt in range(3):
            try:
                content, t_in, t_out = call_model(client, system, user)
                total_in += t_in
                total_out += t_out
                parsed = json.loads(content)
                results = parsed.get("results", [])
                # Map 1-based local idx in batch -> case
                for r in results:
                    local_idx = r.get("idx")
                    if local_idx is None or not (1 <= local_idx <= len(batch)):
                        continue
                    case = batch[local_idx - 1]
                    results_by_idx[case["idx"]] = {
                        "company": r.get("company"),
                        "is_funding": r.get("is_funding"),
                    }
                break
            except Exception as e:
                if attempt == 2:
                    print(f"  ERROR batch starting {batch_start}: {e}", file=sys.stderr)
                else:
                    time.sleep(1.5)

    per_case = []
    total_score = 0.0
    for c in cases:
        idx = c["idx"]
        exp = c["expected"]
        got = results_by_idx.get(idx, {"company": None, "is_funding": None})

        exp_co_n = normalize_company(exp.get("company"))
        got_co_n = normalize_company(got.get("company"))
        co_match = (exp_co_n == got_co_n)

        is_match = bool(exp.get("is_funding")) == bool(got.get("is_funding"))

        score = (0.7 if co_match else 0.0) + (0.3 if is_match else 0.0)
        total_score += score

        per_case.append({
            "idx": idx,
            "title": c["title"][:60],
            "expected_company": exp.get("company"),
            "got_company": got.get("company"),
            "expected_is_funding": exp.get("is_funding"),
            "got_is_funding": got.get("is_funding"),
            "co_match": co_match,
            "is_match": is_match,
            "score": score,
        })

    avg = total_score / len(cases)
    cost = total_in * PRICE_IN + total_out * PRICE_OUT

    if verbose:
        print(f"\n{'idx':<4}{'co?':<5}{'is?':<5}{'score':<7}expected -> got")
        for p in per_case:
            mark_c = "OK" if p["co_match"] else "FAIL"
            mark_i = "OK" if p["is_match"] else "FAIL"
            print(f"{p['idx']:<4}{mark_c:<5}{mark_i:<5}{p['score']:<7.2f}{p['expected_company']!r} -> {p['got_company']!r}")

    return avg, per_case, cost, total_in, total_out


def load_candidate(path):
    with open(path) as f:
        d = json.load(f)
    return d["system"], d["user_template"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", help="Path to candidate prompt JSON")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    cases = json.loads(TEST_CASES_PATH.read_text(encoding="utf-8"))["cases"]

    if args.prompt:
        system, user_template = load_candidate(args.prompt)
        label = Path(args.prompt).stem
    else:
        system, user_template = BASELINE_SYSTEM, BASELINE_USER_TEMPLATE
        label = "baseline"

    client = OpenAI()
    print(f"Scoring {label} on {len(cases)} cases...")
    score, per_case, cost, t_in, t_out = score_prompt(system, user_template, cases, client, verbose=args.verbose)
    print(f"\nScore: {score:.4f}  Cost: ${cost:.5f}  Tokens: in={t_in} out={t_out}")
    return score, per_case, cost


if __name__ == "__main__":
    main()
