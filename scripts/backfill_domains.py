"""
Domain Backfill — audit + fix company domains in funding_discoveries.

Phase 1 (audit):  Scan all rows, classify domain quality, zero API cost.
Phase 2 (fix):    Run GPT+Serper agent on BAD/SUSPECT rows.
Phase 3 (report): Before/after comparison.

Usage:
    py scripts/backfill_domains.py                  # audit only (default)
    py scripts/backfill_domains.py --fix            # audit + dry-run fix
    py scripts/backfill_domains.py --fix --commit   # audit + fix + write to DB
    py scripts/backfill_domains.py --fix --limit 10 # fix first 10 flagged rows
"""

import json
import os
import re
import sys
import argparse
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, quote

SCRIPT_DIR = Path(__file__).resolve().parent

from dotenv import load_dotenv
load_dotenv(SCRIPT_DIR.parent / ".env")
load_dotenv(SCRIPT_DIR.parent.parent / ".env", override=False)
load_dotenv(Path.home() / ".env", override=False)

import requests

SUPABASE_URL = os.getenv("SUPABASE_PROJECT_URL") or os.getenv("SUPABASE_URL") or ""
SUPABASE_KEY = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY") or ""
SERPER_API_KEY = os.getenv("SERPER_API_KEY") or ""
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or ""

COST_PER_SEARCH = 0.0075
COST_PER_GPT_CALL = 0.002
MAX_SEARCH_ROUNDS = 3

# -------------------------------------------------------------------
# Blocklists
# -------------------------------------------------------------------

NEWS_DOMAINS = {
    "businesswire.com", "prnewswire.com", "finsmes.com", "thesaasnews.com",
    "techcrunch.com", "yahoo.com", "finance.yahoo.com", "reuters.com",
    "bloomberg.com", "eu-startups.com", "tech.eu", "venturebeat.com",
    "finanzwire.com", "therecursive.com", "netinfluencer.com",
    "biospace.com", "kitsapsun.com", "cincinnati.com", "bandt.com.au",
    "bandt.com", "digitaltoday.co.kr", "gobiernu.cw", "finance.biggo.com",
    "thequantuminsider.com", "alleywatch.com", "vcnewsdaily.com",
    "infotechlead.com", "siliconangle.com", "techround.co.uk",
    "pulse2.com", "ventureburn.com", "globenewswire.com",
    "einpresswire.com", "startupnews.fyi", "uktech.news",
    "techfundingnews.com", "fiercebiotech.com", "sdxcentral.com",
    "channele2e.com", "forbes.com", "fortune.com", "cnbc.com", "wsj.com",
    "investing.com", "technews180.com", "securitybrief.co.nz",
}

SOCIAL_DOMAINS = {
    "linkedin.com", "crunchbase.com", "wikipedia.org", "facebook.com",
    "twitter.com", "x.com", "github.com", "youtube.com", "instagram.com",
    "reddit.com", "pitchbook.com", "glassdoor.com", "angel.co",
    "wellfound.com", "g2.com", "capterra.com", "trustpilot.com",
    "medium.com", "substack.com", "tiktok.com",
}

TRACKER_DOMAINS = {
    "googletagmanager.com", "googleapis.com", "cloudfront.net",
    "wistia.com", "cision.com", "adobedtm.com",
}

BLOCKED = NEWS_DOMAINS | SOCIAL_DOMAINS | TRACKER_DOMAINS


def is_blocked(domain):
    if not domain:
        return True
    d = domain.lower().replace("www.", "")
    return any(d == b or d.endswith("." + b) for b in BLOCKED)


def normalize_domain(raw):
    if not raw:
        return ""
    raw = raw.strip().lower()
    if "://" in raw:
        raw = raw.split("://", 1)[1]
    return raw.split("/")[0].replace("www.", "")


def name_matches_domain(company_name, domain):
    if not company_name or not domain:
        return False
    cn = re.sub(r"[^a-z0-9]", "", company_name.lower())
    dn = re.sub(r"[^a-z0-9]", "", domain.split(".")[0])
    if len(cn) < 3 or len(dn) < 2:
        return False
    return cn in dn or dn in cn


def get_source_domain(source_url):
    if not source_url:
        return ""
    try:
        return urlparse(source_url).hostname.replace("www.", "")
    except Exception:
        return ""


# -------------------------------------------------------------------
# Phase 1: Audit
# -------------------------------------------------------------------

def classify_domain(row):
    company = row.get("company_name", "")
    domain = normalize_domain(row.get("company_domain", ""))
    source_url = row.get("source_url", "")
    source_domain = get_source_domain(source_url)

    if not domain or domain in ("not_found", "not_stated", ""):
        return "BAD_MISSING", "no domain"

    if is_blocked(domain):
        return "BAD_BLOCKED", f"blocked domain: {domain}"

    if source_domain and domain == source_domain:
        return "BAD_SOURCE", f"matches source: {domain}"

    if not name_matches_domain(company, domain):
        return "SUSPECT", f"name mismatch: {company} vs {domain}"

    return "OK", ""


def fetch_all_rows():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("  ERROR: SUPABASE_URL and SUPABASE_KEY required")
        sys.exit(1)

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }

    all_rows = []
    offset = 0
    page_size = 1000

    while True:
        url = (
            f"{SUPABASE_URL}/rest/v1/funding_discoveries"
            f"?select=id,company_name,company_domain,round_type,source_url,article_text,discovered_date,score"
            f"&order=id.asc"
            f"&offset={offset}&limit={page_size}"
        )
        resp = requests.get(url, headers=headers, timeout=30)
        if not resp.ok:
            print(f"  ERROR: Supabase {resp.status_code}: {resp.text[:200]}")
            sys.exit(1)

        rows = resp.json()
        all_rows.extend(rows)

        if len(rows) < page_size:
            break
        offset += page_size

    return all_rows


def run_audit(rows):
    categories = {"BAD_MISSING": [], "BAD_BLOCKED": [], "BAD_SOURCE": [], "SUSPECT": [], "OK": []}

    for row in rows:
        cat, reason = classify_domain(row)
        row["_category"] = cat
        row["_reason"] = reason
        categories[cat].append(row)

    print(f"\n  AUDIT RESULTS ({len(rows)} total rows)")
    print(f"  {'='*50}")
    print(f"  OK:          {len(categories['OK']):>5}")
    print(f"  BAD_MISSING: {len(categories['BAD_MISSING']):>5}")
    print(f"  BAD_BLOCKED: {len(categories['BAD_BLOCKED']):>5}")
    print(f"  BAD_SOURCE:  {len(categories['BAD_SOURCE']):>5}")
    print(f"  SUSPECT:     {len(categories['SUSPECT']):>5}")
    print(f"  {'='*50}")

    flagged = categories["BAD_MISSING"] + categories["BAD_BLOCKED"] + categories["BAD_SOURCE"] + categories["SUSPECT"]
    print(f"  Total flagged: {len(flagged)}")

    # Round breakdown
    round_counts = {}
    for row in flagged:
        rt = row.get("round_type", "unknown")
        round_counts[rt] = round_counts.get(rt, 0) + 1
    if round_counts:
        print(f"\n  Flagged by round:")
        for rt, count in sorted(round_counts.items()):
            print(f"    {rt}: {count}")

    # Show flagged rows
    for cat in ["BAD_MISSING", "BAD_BLOCKED", "BAD_SOURCE", "SUSPECT"]:
        if categories[cat]:
            print(f"\n  {cat} ({len(categories[cat])}):")
            for row in categories[cat][:20]:
                domain = row.get("company_domain", "")
                print(f"    {row['company_name'][:30]:<30} domain={domain[:30]:<30} ({row['_reason']})")
            if len(categories[cat]) > 20:
                print(f"    ... and {len(categories[cat]) - 20} more")

    return flagged


# -------------------------------------------------------------------
# Phase 2: Fix — GPT+Serper agent
# -------------------------------------------------------------------

SYSTEM_PROMPT = """You find the official website domain for a startup that recently raised funding. You have a web search tool.

SEARCH STRATEGY (in order):
1. Primary: "{company_name}" {industry} website
2. If ambiguous: site:crunchbase.com "{company_name}" -- Crunchbase snippets often contain the actual domain
3. If still ambiguous: add location to disambiguate
4. If common-word name: search "{company_name}" {industry} startup funding -- funding articles link to the actual company

IMPORTANT:
- These are STARTUPS that raised venture funding. Not large enterprises or legacy companies.
- The domain often does NOT match the company name. Examples: Keep -> trykeep.com, Gong -> gong.io
- Crunchbase snippets are your best friend for obscure startups.
- Look at SERP snippet descriptions to verify the domain matches the RIGHT company in the RIGHT industry
- NEVER return social media, news/media, investor, or directory domains
- Return ONLY the bare domain (e.g. "hata.io", "mosaic.pe")
- If confident, return after 1 search. If ambiguous, refine (max 3 searches)

RESPONSE FORMAT (when done):
{"domain": "example.com", "confidence": "high|medium|low", "evidence": "brief reason"}"""

SEARCH_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search Google. Returns titles, URLs, and snippet descriptions.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
    },
}

INDUSTRY_PATTERNS = [
    (re.compile(r"\b(AI|artificial intelligence|machine learning|ML)\b", re.I), "AI"),
    (re.compile(r"\b(fintech|financial technology|payments|banking|insurtech)\b", re.I), "fintech"),
    (re.compile(r"\b(healthtech|healthcare|medical|biotech|pharma)\b", re.I), "healthtech"),
    (re.compile(r"\b(SaaS|software|platform|cloud)\b", re.I), "SaaS"),
    (re.compile(r"\b(cybersecurity|security|infosec)\b", re.I), "cybersecurity"),
    (re.compile(r"\b(e-commerce|ecommerce|retail|marketplace)\b", re.I), "ecommerce"),
    (re.compile(r"\b(robotics|autonomous|automation)\b", re.I), "robotics"),
    (re.compile(r"\b(climate|cleantech|energy|sustainability)\b", re.I), "cleantech"),
    (re.compile(r"\b(edtech|education|learning)\b", re.I), "edtech"),
    (re.compile(r"\b(proptech|real estate|construction)\b", re.I), "proptech"),
    (re.compile(r"\b(logistics|supply chain|shipping)\b", re.I), "logistics"),
    (re.compile(r"\b(devtools|developer|infrastructure)\b", re.I), "devtools"),
]


def extract_industry(article_text):
    if not article_text:
        return ""
    text = article_text[:3000]
    for pattern, label in INDUSTRY_PATTERNS:
        if pattern.search(text):
            return label
    return ""


def serper_search(query, num=5):
    if not SERPER_API_KEY:
        return []
    try:
        resp = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json={"q": query, "num": num},
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json().get("organic", [])
    except Exception:
        pass
    return []


def format_results(items):
    if not items:
        return "No results found."
    lines = []
    for i, item in enumerate(items):
        lines.append(f"[{i+1}] {item.get('title', '')}\n    URL: {item.get('link', '')}\n    {item.get('snippet', '')}")
    return "\n\n".join(lines)


def resolve_domain_agent(company_name, industry, source_domain=""):
    context_parts = [f"Company: {company_name}"]
    if industry:
        context_parts.append(f"Industry: {industry}")
    if source_domain:
        context_parts.append(f"Source article domain (DO NOT return this): {source_domain}")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(context_parts)},
    ]

    search_count = 0
    gpt_calls = 0

    for round_num in range(MAX_SEARCH_ROUNDS + 1):
        try:
            gpt_calls += 1
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "gpt-4o-mini",
                    "temperature": 0,
                    "max_tokens": 300,
                    "messages": messages,
                    "tools": [SEARCH_TOOL_DEF],
                    "tool_choice": "auto" if round_num < MAX_SEARCH_ROUNDS else "none",
                },
                timeout=30,
            )
            if not resp.ok:
                return {"domain": "not_found", "confidence": "low", "searches": search_count, "gpt_calls": gpt_calls}

            data = resp.json()
            msg = data["choices"][0]["message"]

            if msg.get("tool_calls"):
                messages.append(msg)
                for tc in msg["tool_calls"]:
                    args = json.loads(tc["function"]["arguments"])
                    query = args.get("query", "")
                    search_count += 1
                    items = serper_search(query, 5)
                    messages.append({"role": "tool", "tool_call_id": tc["id"], "content": format_results(items)})
                continue

            content = (msg.get("content") or "").strip()
            parsed = {}
            try:
                m = re.search(r"\{[\s\S]*\}", content)
                if m:
                    parsed = json.loads(m.group(0))
            except Exception:
                pass

            domain = (parsed.get("domain") or "").replace("www.", "").replace("https://", "").replace("http://", "").split("/")[0].lower()
            confidence = parsed.get("confidence", "low")
            evidence = parsed.get("evidence", "")

            if not domain or domain == "not_found" or is_blocked(domain):
                domain = "not_found"
                confidence = "low"

            return {"domain": domain, "confidence": confidence, "evidence": evidence, "searches": search_count, "gpt_calls": gpt_calls}
        except Exception:
            break

    return {"domain": "not_found", "confidence": "low", "searches": search_count, "gpt_calls": gpt_calls}


def patch_domain(row_id, new_domain):
    url = f"{SUPABASE_URL}/rest/v1/funding_discoveries?id=eq.{row_id}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    resp = requests.patch(url, headers=headers, json={"company_domain": new_domain}, timeout=15)
    return resp.ok


def run_fix(flagged, limit=None, commit=False):
    if not SERPER_API_KEY or not OPENAI_API_KEY:
        print("  ERROR: Need SERPER_API_KEY and OPENAI_API_KEY for fix phase")
        return

    if limit:
        flagged = flagged[:limit]

    print(f"\n  FIXING {len(flagged)} rows {'(DRY RUN)' if not commit else '(COMMITTING)'}")
    print(f"  {'='*60}")

    total_searches = 0
    total_gpt_calls = 0
    changes = []
    unchanged = 0
    failures = 0

    for i, row in enumerate(flagged):
        company = row["company_name"]
        old_domain = normalize_domain(row.get("company_domain", ""))
        source_domain = get_source_domain(row.get("source_url", ""))
        industry = extract_industry(row.get("article_text", ""))
        row_id = row["id"]

        result = resolve_domain_agent(company, industry, source_domain)
        new_domain = result["domain"]
        confidence = result["confidence"]
        total_searches += result["searches"]
        total_gpt_calls += result["gpt_calls"]

        if new_domain == "not_found" or confidence == "low":
            failures += 1
            print(f"  [{i+1}/{len(flagged)}] {company[:30]:<30} SKIP (low confidence / not found)")
            continue

        if new_domain == old_domain:
            unchanged += 1
            print(f"  [{i+1}/{len(flagged)}] {company[:30]:<30} SAME ({new_domain})")
            continue

        changes.append({
            "id": row_id,
            "company": company,
            "old_domain": old_domain,
            "new_domain": new_domain,
            "confidence": confidence,
            "evidence": result.get("evidence", ""),
            "round_type": row.get("round_type", ""),
        })

        if commit:
            ok = patch_domain(row_id, new_domain)
            status = "UPDATED" if ok else "PATCH FAILED"
        else:
            status = "WOULD UPDATE"

        print(f"  [{i+1}/{len(flagged)}] {company[:30]:<30} {old_domain[:20]:<20} -> {new_domain[:20]:<20} [{confidence}] {status}")

    # Summary
    cost = total_searches * COST_PER_SEARCH + total_gpt_calls * COST_PER_GPT_CALL
    print(f"\n  FIX SUMMARY")
    print(f"  {'='*50}")
    print(f"  Changed:   {len(changes)}")
    print(f"  Unchanged: {unchanged}")
    print(f"  Failed:    {failures}")
    print(f"  Searches:  {total_searches} (${total_searches * COST_PER_SEARCH:.4f})")
    print(f"  GPT calls: {total_gpt_calls} (~${total_gpt_calls * COST_PER_GPT_CALL:.4f})")
    print(f"  Total cost: ~${cost:.4f}")

    if not commit and changes:
        print(f"\n  Run with --commit to write {len(changes)} changes to DB")

    # Save change log
    out_path = SCRIPT_DIR.parent / "output" / f"backfill-{'committed' if commit else 'dryrun'}-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps({
        "date": datetime.now().isoformat(),
        "committed": commit,
        "changes": changes,
        "stats": {
            "changed": len(changes),
            "unchanged": unchanged,
            "failed": failures,
            "total_searches": total_searches,
            "total_gpt_calls": total_gpt_calls,
            "cost": cost,
        },
    }, indent=2), encoding="utf-8")
    print(f"  Log saved: {out_path}")

    return changes


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Backfill company domains in funding_discoveries")
    parser.add_argument("--fix", action="store_true", help="Run fix phase (agent resolver)")
    parser.add_argument("--commit", action="store_true", help="Write changes to DB (requires --fix)")
    parser.add_argument("--limit", type=int, help="Limit fix to N rows")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  DOMAIN BACKFILL")
    print(f"  Supabase: {'YES' if SUPABASE_URL else 'NO'} | Serper: {'YES' if SERPER_API_KEY else 'NO'} | OpenAI: {'YES' if OPENAI_API_KEY else 'NO'}")
    print(f"{'='*60}")

    # Phase 1: Pull + Audit
    print(f"\n  Fetching all rows from funding_discoveries...")
    rows = fetch_all_rows()
    print(f"  Fetched {len(rows)} rows")

    flagged = run_audit(rows)

    if not flagged:
        print("\n  No flagged rows. DB is clean.")
        return

    # Phase 2: Fix
    if args.fix:
        run_fix(flagged, limit=args.limit, commit=args.commit)
    else:
        est_cost = len(flagged) * 0.02
        print(f"\n  Estimated fix cost: ~${est_cost:.2f} for {len(flagged)} rows")
        print(f"  Run with --fix to start resolving")
        print(f"  Run with --fix --commit to write to DB")


if __name__ == "__main__":
    main()
