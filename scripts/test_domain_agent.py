"""
Domain Agent Resolver Test

Tests the GPT-with-Serper-tool approach for domain resolution.
GPT gets search as a tool, reasons about results, can do multi-pass.

Usage:
    py scripts/test_domain_agent.py
    py scripts/test_domain_agent.py --company "Harvey"
    py scripts/test_domain_agent.py --dry-run
"""

import json
import os
import re
import sys
import argparse
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).resolve().parent

from dotenv import load_dotenv
load_dotenv(SCRIPT_DIR.parent / ".env")
load_dotenv(SCRIPT_DIR.parent.parent / ".env", override=False)
load_dotenv(Path.home() / ".env", override=False)

import requests

SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

COST_PER_SEARCH = 0.0075
COST_PER_GPT_CALL = 0.002  # approximate gpt-4o-mini with tool use
MAX_ROUNDS = 3

# ---------------------------------------------------------------
# Ground Truth
# ---------------------------------------------------------------

GROUND_TRUTH = [
    {"company": "Stripe", "domain": "stripe.com", "industry": "fintech", "location": "San Francisco, US", "tier": 1},
    {"company": "Databricks", "domain": "databricks.com", "industry": "AI data analytics", "location": "San Francisco, US", "tier": 1},
    {"company": "Figma", "domain": "figma.com", "industry": "design collaboration", "location": "San Francisco, US", "tier": 1},
    {"company": "Cohere", "domain": "cohere.com", "industry": "AI", "location": "Toronto, Canada", "tier": 2},
    {"company": "Harvey", "domain": "harvey.ai", "industry": "AI legal", "location": "San Francisco, US", "tier": 2},
    {"company": "Mosaic", "domain": "mosaic.pe", "industry": "AI deal-making", "location": "", "tier": 2},
    {"company": "Zenskar", "domain": "zenskar.com", "industry": "billing SaaS", "location": "Bangalore, India", "tier": 2},
    {"company": "Hata", "domain": "hata.io", "industry": "fintech", "location": "", "tier": 2},
    {"company": "ElevenLabs", "domain": "elevenlabs.io", "industry": "AI voice synthesis", "location": "New York, US", "tier": 2},
    {"company": "Lovable", "domain": "lovable.dev", "industry": "AI software development", "location": "Stockholm, Sweden", "tier": 2},
    {"company": "Clay", "domain": "clay.com", "industry": "GTM data enrichment", "location": "New York, US", "tier": 3},
    {"company": "Keep", "domain": "trykeep.com", "industry": "fintech tax credits", "location": "New York, US", "tier": 3},
    {"company": "Vanta", "domain": "vanta.com", "industry": "security compliance", "location": "San Francisco, US", "tier": 3},
    {"company": "Brev", "domain": "brev.dev", "industry": "cloud GPU infrastructure", "location": "San Francisco, US", "tier": 3},
    {"company": "Nava", "domain": "navabenefits.com", "industry": "benefits technology", "location": "", "tier": 3},
    {"company": "Cosaic", "domain": "cosaic.com", "industry": "AI financial analysis", "location": "", "tier": 3},
]

BLOCKED_DOMAINS = {
    "linkedin.com", "crunchbase.com", "wikipedia.org", "twitter.com", "x.com",
    "facebook.com", "bloomberg.com", "pitchbook.com", "glassdoor.com", "indeed.com",
    "github.com", "youtube.com", "instagram.com", "reddit.com", "medium.com",
    "techcrunch.com", "thesaasnews.com", "finsmes.com", "businesswire.com",
    "prnewswire.com", "forbes.com", "yahoo.com", "zoominfo.com",
}

SEARCH_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search Google via Serper. Regular web search (not news). Returns titles, URLs, and snippet descriptions. Use industry + company name + 'website' as primary pattern. Use location to disambiguate common names.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query. Include industry context for disambiguation.",
                },
            },
            "required": ["query"],
        },
    },
}

SYSTEM_PROMPT = """You find the official website domain for a startup that recently raised funding. You have a web search tool.

SEARCH STRATEGY (in order):
1. Primary: "{company_name}" {industry} website
2. If ambiguous: site:crunchbase.com "{company_name}" — Crunchbase snippets often contain the actual domain in text like "Company (domain.com) raised..."
3. If still ambiguous: add location to disambiguate
4. If common-word name (Keep, Clay, Era): search "{company_name}" {industry} startup funding — funding articles link to the actual company

IMPORTANT:
- These are STARTUPS that raised venture funding. Not large enterprises or legacy companies.
- The domain often does NOT match the company name. Examples: Keep -> trykeep.com, Gong -> gong.io, Plaid -> plaid.com. Don't assume {name}.com is correct — verify from search results.
- Crunchbase snippets are your best friend for obscure startups. The snippet text often contains the domain directly.
- Look at SERP snippet descriptions to verify the domain matches the RIGHT company in the RIGHT industry
- NEVER return social media, news/media, investor, or directory domains (linkedin, crunchbase, pitchbook, techcrunch, etc.)
- Return ONLY the bare domain (e.g. "hata.io", "mosaic.pe")
- If confident, return after 1 search. If ambiguous, refine (max 3 searches)

RESPONSE FORMAT (when done searching):
{"domain": "example.com", "confidence": "high|medium|low", "evidence": "brief reason"}"""


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
    except Exception as e:
        print(f"      Serper error: {e}")
    return []


def format_search_results(items):
    if not items:
        return "No results found."
    lines = []
    for i, item in enumerate(items):
        link = item.get("link", "")
        title = item.get("title", "")
        snippet = item.get("snippet", "")
        lines.append(f"[{i+1}] {title}\n    URL: {link}\n    {snippet}")
    return "\n\n".join(lines)


def resolve_domain_agent(company):
    name = company["company"]
    industry = company.get("industry", "")
    location = company.get("location", "")

    context_parts = [f"Company: {name}"]
    if industry:
        context_parts.append(f"Industry: {industry}")
    if location:
        context_parts.append(f"Location: {location}")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(context_parts)},
    ]

    search_count = 0
    gpt_calls = 0
    queries_used = []

    for round_num in range(MAX_ROUNDS + 1):
        try:
            gpt_calls += 1
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "temperature": 0,
                    "max_tokens": 300,
                    "messages": messages,
                    "tools": [SEARCH_TOOL_DEF],
                    "tool_choice": "auto" if round_num < MAX_ROUNDS else "none",
                },
                timeout=30,
            )

            if not resp.ok:
                return {"domain": "not_found", "error": f"openai {resp.status_code}", "searches": search_count, "gpt_calls": gpt_calls, "queries": queries_used}

            data = resp.json()
            choice = data["choices"][0]
            msg = choice["message"]

            # Tool calls -> execute search
            if msg.get("tool_calls"):
                messages.append(msg)
                for tc in msg["tool_calls"]:
                    args = json.loads(tc["function"]["arguments"])
                    query = args.get("query", "")
                    queries_used.append(query)
                    search_count += 1
                    print(f"      Search {search_count}: {query}")
                    items = serper_search(query, 5)
                    result_text = format_search_results(items)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result_text,
                    })
                continue

            # Final response
            content = (msg.get("content") or "").strip()
            parsed = {}
            try:
                json_match = re.search(r"\{[\s\S]*\}", content)
                if json_match:
                    parsed = json.loads(json_match.group(0))
            except Exception:
                pass

            domain = (parsed.get("domain") or "").replace("www.", "").replace("https://", "").replace("http://", "").split("/")[0].lower()
            confidence = parsed.get("confidence", "medium")
            evidence = parsed.get("evidence", "")

            return {
                "domain": domain or "not_found",
                "confidence": confidence,
                "evidence": evidence,
                "searches": search_count,
                "gpt_calls": gpt_calls,
                "queries": queries_used,
            }

        except Exception as e:
            return {"domain": "not_found", "error": str(e), "searches": search_count, "gpt_calls": gpt_calls, "queries": queries_used}

    return {"domain": "not_found", "searches": search_count, "gpt_calls": gpt_calls, "queries": queries_used}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--company", type=str, help="Test single company")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    companies = GROUND_TRUTH
    if args.company:
        companies = [c for c in GROUND_TRUTH if c["company"].lower() == args.company.lower()]
        if not companies:
            print(f"Company '{args.company}' not in ground truth")
            return

    print(f"\n{'='*80}")
    print(f"  DOMAIN AGENT RESOLVER TEST")
    print(f"  Companies: {len(companies)} | Serper: {'YES' if SERPER_API_KEY else 'NO'} | OpenAI: {'YES' if OPENAI_API_KEY else 'NO'}")
    print(f"{'='*80}\n")

    if not SERPER_API_KEY or not OPENAI_API_KEY:
        print("  ERROR: Need both SERPER_API_KEY and OPENAI_API_KEY")
        return

    results = []
    total_searches = 0
    total_gpt_calls = 0

    for company in companies:
        name = company["company"]
        expected = company["domain"]
        tier = company["tier"]

        print(f"\n  [{name}] (T{tier}) expected={expected}")

        if args.dry_run:
            print(f"    SKIP (dry run)")
            continue

        result = resolve_domain_agent(company)
        resolved = result["domain"]
        searches = result["searches"]
        gpt_calls = result["gpt_calls"]
        total_searches += searches
        total_gpt_calls += gpt_calls

        correct = resolved.replace("www.", "") == expected.replace("www.", "")
        status = "OK" if correct else "XX"

        print(f"    {status} got={resolved} | {searches} searches, {gpt_calls} GPT calls")
        if result.get("evidence"):
            print(f"    evidence: {result['evidence']}")
        if not correct and result.get("queries"):
            for q in result["queries"]:
                print(f"      query: {q}")

        results.append({
            "company": name,
            "tier": tier,
            "expected": expected,
            "resolved": resolved,
            "correct": correct,
            "searches": searches,
            "gpt_calls": gpt_calls,
            "queries": result.get("queries", []),
            "confidence": result.get("confidence", ""),
            "evidence": result.get("evidence", ""),
        })

    if args.dry_run:
        return

    # Summary
    print(f"\n{'='*80}")
    print(f"  SUMMARY")
    print(f"{'='*80}\n")

    correct_count = sum(1 for r in results if r["correct"])
    total = len(results)
    accuracy = (correct_count / total * 100) if total else 0

    print(f"  Accuracy: {correct_count}/{total} = {accuracy:.0f}%")
    print(f"  Total searches: {total_searches} (${total_searches * COST_PER_SEARCH:.4f})")
    print(f"  Total GPT calls: {total_gpt_calls} (~${total_gpt_calls * COST_PER_GPT_CALL:.4f})")
    print(f"  Avg searches/company: {total_searches / total:.1f}")

    # Per-tier breakdown
    for tier in [1, 2, 3]:
        tier_results = [r for r in results if r["tier"] == tier]
        tier_correct = sum(1 for r in tier_results if r["correct"])
        tier_total = len(tier_results)
        if tier_total:
            print(f"  T{tier}: {tier_correct}/{tier_total} = {tier_correct/tier_total*100:.0f}%")

    # Failures
    failures = [r for r in results if not r["correct"]]
    if failures:
        print(f"\n  FAILURES:")
        for f in failures:
            print(f"    {f['company']} (T{f['tier']}): expected={f['expected']} got={f['resolved']}")
            for q in f.get("queries", []):
                print(f"      query: {q}")

    # Save
    out_path = SCRIPT_DIR.parent / "output" / f"domain-agent-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps({
        "date": datetime.now().isoformat(),
        "accuracy_pct": accuracy,
        "correct": correct_count,
        "total": total,
        "total_searches": total_searches,
        "total_gpt_calls": total_gpt_calls,
        "results": results,
    }, indent=2), encoding="utf-8")
    print(f"\n  Saved: {out_path}")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    main()
