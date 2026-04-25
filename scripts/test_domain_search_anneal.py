"""
Domain Search Pattern Annealer

Tests domain resolution search strategies against ground truth companies.
Strategy: {industry} {company_name} website → score from SERP snippets.
Location as fallback. Regular Serper search endpoint (NOT Google News).

Usage:
    python scripts/test_domain_search_anneal.py
    python scripts/test_domain_search_anneal.py --pattern 1
    python scripts/test_domain_search_anneal.py --dry-run
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
COST_PER_SEARCH = 0.0075  # Serper cost per search

# ------------------------------------------------------------
# Ground Truth — companies with KNOWN correct domains
# Mix of tiers: T1 (well-known), T2 (mid), T3 (obscure)
# ------------------------------------------------------------

GROUND_TRUTH = [
    # T1 — well-known, easy
    {"company": "Stripe", "domain": "stripe.com", "industry": "fintech", "location": "San Francisco, US", "tier": 1},
    {"company": "Databricks", "domain": "databricks.com", "industry": "AI data analytics", "location": "San Francisco, US", "tier": 1},
    {"company": "Figma", "domain": "figma.com", "industry": "design collaboration", "location": "San Francisco, US", "tier": 1},

    # T2 — funded startups, some press
    {"company": "Cohere", "domain": "cohere.com", "industry": "AI", "location": "Toronto, Canada", "tier": 2},
    {"company": "Harvey", "domain": "harvey.ai", "industry": "AI legal", "location": "San Francisco, US", "tier": 2},
    {"company": "Mosaic", "domain": "mosaic.pe", "industry": "AI deal-making", "location": "", "tier": 2},
    {"company": "Zenskar", "domain": "zenskar.com", "industry": "billing SaaS", "location": "Bangalore, India", "tier": 2},
    {"company": "Hata", "domain": "hata.io", "industry": "fintech", "location": "", "tier": 2},
    {"company": "ElevenLabs", "domain": "elevenlabs.io", "industry": "AI voice synthesis", "location": "New York, US", "tier": 2},
    {"company": "Lovable", "domain": "lovable.dev", "industry": "AI software development", "location": "Stockholm, Sweden", "tier": 2},

    # T3 — obscure, ambiguous names, hard cases
    {"company": "Clay", "domain": "clay.com", "industry": "GTM data enrichment", "location": "New York, US", "tier": 3},
    {"company": "Keep", "domain": "trykeep.com", "industry": "fintech tax credits", "location": "New York, US", "tier": 3},
    {"company": "Era", "domain": "era.co", "industry": "construction technology", "location": "", "tier": 3},
    {"company": "Humble", "domain": "humbleburger.com", "industry": "restaurant", "location": "", "tier": 3},
    {"company": "Brev", "domain": "brev.dev", "industry": "cloud GPU infrastructure", "location": "San Francisco, US", "tier": 3},
    {"company": "Signit", "domain": "signit.com", "industry": "digital signatures", "location": "", "tier": 3},
    {"company": "Verda", "domain": "verda.co", "industry": "sustainability", "location": "", "tier": 3},
    {"company": "Foamlab", "domain": "foamlab.co", "industry": "materials science", "location": "", "tier": 3},
    {"company": "Nava", "domain": "nava.io", "industry": "benefits technology", "location": "", "tier": 3},
    {"company": "Cosaic", "domain": "cosaic.io", "industry": "AI financial analysis", "location": "", "tier": 3},
]

# ------------------------------------------------------------
# Blocklists
# ------------------------------------------------------------

BLOCKED_DOMAINS = {
    "linkedin.com", "crunchbase.com", "wikipedia.org", "twitter.com", "x.com",
    "facebook.com", "bloomberg.com", "pitchbook.com", "glassdoor.com", "indeed.com",
    "ycombinator.com", "github.com", "youtube.com", "instagram.com", "tiktok.com",
    "reddit.com", "medium.com", "substack.com", "angel.co", "wellfound.com",
    "g2.com", "capterra.com", "trustpilot.com", "apple.com", "play.google.com",
    "techcrunch.com", "thesaasnews.com", "finsmes.com", "businesswire.com",
    "prnewswire.com", "einpresswire.com", "globenewswire.com", "yahoo.com",
    "finance.yahoo.com", "reuters.com", "venturebeat.com", "siliconangle.com",
    "alleywatch.com", "vcnewsdaily.com", "infotechlead.com", "eu-startups.com",
    "tech.eu", "forbes.com", "fortune.com", "cnbc.com", "wsj.com",
    "zoominfo.com", "tracxn.com", "dealroom.co", "cbinsights.com",
}


def is_blocked(domain: str) -> bool:
    d = domain.lower().replace("www.", "")
    return any(d == b or d.endswith("." + b) for b in BLOCKED_DOMAINS)


def normalize_domain(raw: str) -> str:
    raw = raw.strip().lower()
    if "://" in raw:
        raw = raw.split("://", 1)[1]
    raw = raw.split("/")[0].replace("www.", "")
    return raw


def domain_contains_name(domain: str, company: str) -> bool:
    d = re.sub(r"[^a-z0-9]", "", domain.split(".")[0])
    c = re.sub(r"[^a-z0-9]", "", company.lower())
    if len(c) < 3 or len(d) < 2:
        return False
    return c in d or d in c


# ------------------------------------------------------------
# Serper search (regular endpoint, NOT news)
# ------------------------------------------------------------

def serper_search(query: str, num: int = 5) -> list[dict]:
    if not SERPER_API_KEY:
        return []
    try:
        resp = requests.post(
            "https://google.serper.dev/search",  # regular search, NOT /news
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json={"q": query, "num": num},
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json().get("organic", [])
    except Exception as e:
        print(f"      Serper error: {e}")
    return []


# ------------------------------------------------------------
# Search Pattern Definitions
# Each pattern is a function: (company, industry, location) → query string
# ------------------------------------------------------------

SEARCH_PATTERNS = {
    # Primary: industry + name + website
    "P1_industry_name_website": lambda c, ind, loc: f"{ind} {c} website" if ind else None,

    # Primary: quoted name + website
    "P2_quoted_name_website": lambda c, ind, loc: f'"{c}" website',

    # Primary: industry + name + official site
    "P3_industry_name_official": lambda c, ind, loc: f"{ind} {c} official site" if ind else None,

    # Fallback: name + location + website (location as disambiguator)
    "F1_name_location_website": lambda c, ind, loc: f"{c} {loc} website" if loc else None,

    # Fallback: industry + name + location
    "F2_industry_name_location": lambda c, ind, loc: f"{ind} {c} {loc}" if ind and loc else None,

    # Legacy: quoted name + startup website (current production pattern)
    "L1_quoted_startup": lambda c, ind, loc: f'"{c}" startup website',

    # Legacy: name + company (exclude social)
    "L2_direct_company": lambda c, ind, loc: f'"{c}" company -site:linkedin.com -site:crunchbase.com',

    # Crunchbase snippet mining
    "CB_crunchbase": lambda c, ind, loc: f'site:crunchbase.com "{c}"',
}


def extract_domains_from_snippet(text: str) -> list[str]:
    pattern = re.compile(
        r"\b([a-z0-9][-a-z0-9]*\.(?:com|io|ai|co|org|net|dev|app|tech|health|bio|xyz|gg|so|cc|me|pe))\b",
        re.IGNORECASE,
    )
    return list(dict.fromkeys(m.lower() for m in pattern.findall(text)))


# ------------------------------------------------------------
# Scoring: rank candidates from SERP results
# ------------------------------------------------------------

def score_serp_results(
    results: list[dict],
    company_name: str,
    industry: str,
    pattern_label: str,
    source_domain: str = "",
) -> dict[str, dict]:
    """Score domains from SERP results. Returns {domain: {score, appearances, evidence}}"""
    candidates: dict[str, dict] = {}

    def add(domain: str, evidence: str, bonus: int = 0):
        d = normalize_domain(domain)
        if is_blocked(d) or d == source_domain or len(d) < 4:
            return
        entry = candidates.setdefault(d, {"score": 0, "appearances": 0, "evidence": []})
        entry["appearances"] += 1
        entry["evidence"].append(evidence)

        # Name match in domain (+5)
        if domain_contains_name(d, company_name):
            entry["score"] += 5

        # Good TLD (+1)
        if re.search(r"\.(com|io|ai|co|dev|pe)$", d):
            entry["score"] += 1

        entry["score"] += bonus

    for item in results:
        link = item.get("link", "")
        title = item.get("title", "")
        snippet = item.get("snippet", "")

        # Score the link domain
        if "://" in link:
            try:
                from urllib.parse import urlparse
                hostname = urlparse(link).hostname or ""
                d = hostname.replace("www.", "")

                bonus = 0
                # Title mentions company name (+2)
                if company_name.lower() in title.lower():
                    bonus += 2
                # Snippet mentions company name (+1)
                if company_name.lower() in snippet.lower():
                    bonus += 1
                # Snippet describes industry match (+2)
                if industry and industry.lower() in snippet.lower():
                    bonus += 2

                add(d, f"{pattern_label}:link", bonus)
            except Exception:
                pass

        # Mine domains from snippet (Crunchbase snippets often contain company domain)
        for sd in extract_domains_from_snippet(snippet):
            snippet_bonus = 3 if "crunchbase" in pattern_label.lower() else 0
            add(sd, f"{pattern_label}:snippet", snippet_bonus)

    return candidates


# ------------------------------------------------------------
# Run one pattern against one company
# ------------------------------------------------------------

def test_pattern(
    pattern_name: str,
    pattern_fn,
    company: dict,
    dry_run: bool = False,
) -> dict:
    """Test a single search pattern against a single company."""
    name = company["company"]
    industry = company.get("industry", "")
    location = company.get("location", "")
    expected = company["domain"]

    query = pattern_fn(name, industry, location)
    if query is None:
        return {"pattern": pattern_name, "company": name, "query": None, "skip": True, "reason": "missing input"}

    if dry_run:
        return {"pattern": pattern_name, "company": name, "query": query, "skip": True, "reason": "dry_run"}

    results = serper_search(query, 5)
    candidates = score_serp_results(results, name, industry, pattern_name)

    if not candidates:
        return {
            "pattern": pattern_name, "company": name, "query": query,
            "resolved": "not_found", "expected": expected, "correct": False,
            "candidates": 0, "top_score": 0,
        }

    sorted_cands = sorted(candidates.items(), key=lambda x: x[1]["score"], reverse=True)
    best_domain, best_meta = sorted_cands[0]

    correct = normalize_domain(best_domain) == normalize_domain(expected)

    return {
        "pattern": pattern_name, "company": name, "query": query,
        "resolved": best_domain, "expected": expected, "correct": correct,
        "candidates": len(candidates),
        "top_score": best_meta["score"],
        "top_3": [(d, m["score"]) for d, m in sorted_cands[:3]],
    }


# ------------------------------------------------------------
# Full anneal run
# ------------------------------------------------------------

def run_anneal(pattern_filter: str | None = None, dry_run: bool = False):
    patterns_to_test = SEARCH_PATTERNS
    if pattern_filter:
        patterns_to_test = {k: v for k, v in SEARCH_PATTERNS.items() if pattern_filter.lower() in k.lower()}

    total_searches = 0
    all_results = []

    print(f"\n{'='*80}")
    print(f"  DOMAIN SEARCH PATTERN ANNEAL")
    print(f"  Patterns: {len(patterns_to_test)} | Companies: {len(GROUND_TRUTH)} | Serper: {'YES' if SERPER_API_KEY else 'NO'}")
    print(f"  Date: {datetime.now().isoformat()[:10]}")
    print(f"{'='*80}\n")

    for pat_name, pat_fn in patterns_to_test.items():
        print(f"\n-- Pattern: {pat_name} --")
        pat_results = []

        for company in GROUND_TRUTH:
            result = test_pattern(pat_name, pat_fn, company, dry_run)
            pat_results.append(result)
            all_results.append(result)

            if result.get("skip"):
                print(f"  {company['company']:<25} SKIP ({result.get('reason', '')})")
                continue

            total_searches += 1
            status = "OK" if result["correct"] else "XX"
            resolved = result["resolved"]
            expected = result["expected"]
            print(f"  {status} {company['company']:<25} got={resolved:<25} expected={expected:<25} score={result['top_score']}")

            if not result["correct"] and result.get("top_3"):
                for d, s in result["top_3"][:3]:
                    flag = " << EXPECTED" if normalize_domain(d) == normalize_domain(expected) else ""
                    print(f"      candidate: {d:<30} score={s}{flag}")

        # Pattern summary
        tested = [r for r in pat_results if not r.get("skip")]
        correct = sum(1 for r in tested if r.get("correct"))
        total = len(tested)
        accuracy = (correct / total * 100) if total else 0
        print(f"\n  >> {pat_name}: {correct}/{total} = {accuracy:.0f}%")

    # -- GRAND SUMMARY --
    print(f"\n{'='*80}")
    print(f"  ANNEAL SUMMARY")
    print(f"{'='*80}\n")

    # Per-pattern accuracy
    print(f"  {'Pattern':<35} {'Correct':>8} {'Tested':>8} {'Accuracy':>10}")
    print(f"  {'-'*35} {'-'*8} {'-'*8} {'-'*10}")

    pattern_scores = {}
    for pat_name in patterns_to_test:
        pat_results = [r for r in all_results if r["pattern"] == pat_name and not r.get("skip")]
        correct = sum(1 for r in pat_results if r.get("correct"))
        total = len(pat_results)
        accuracy = (correct / total * 100) if total else 0
        pattern_scores[pat_name] = {"correct": correct, "total": total, "accuracy": accuracy}
        print(f"  {pat_name:<35} {correct:>8} {total:>8} {accuracy:>9.0f}%")

    # Per-company accuracy (across all patterns)
    print(f"\n  {'Company':<25} {'Tier':>5} {'Hits':>6} {'Total':>6}")
    print(f"  {'-'*25} {'-'*5} {'-'*6} {'-'*6}")
    for company in GROUND_TRUTH:
        comp_results = [r for r in all_results if r["company"] == company["company"] and not r.get("skip")]
        hits = sum(1 for r in comp_results if r.get("correct"))
        total = len(comp_results)
        print(f"  {company['company']:<25} T{company['tier']:>4} {hits:>6} {total:>6}")

    # Cost
    cost = total_searches * COST_PER_SEARCH
    print(f"\n  Total searches: {total_searches} | Cost: ${cost:.4f}")

    # Best pattern
    if pattern_scores:
        best = max(pattern_scores.items(), key=lambda x: x[1]["accuracy"])
        print(f"  Best pattern: {best[0]} ({best[1]['accuracy']:.0f}%)")

    # Hard failures — companies NO pattern found correctly
    hard_fails = []
    for company in GROUND_TRUTH:
        comp_results = [r for r in all_results if r["company"] == company["company"] and not r.get("skip")]
        if comp_results and not any(r.get("correct") for r in comp_results):
            hard_fails.append(company["company"])
    if hard_fails:
        print(f"\n  HARD FAILURES (no pattern found correct domain):")
        for f in hard_fails:
            print(f"    - {f}")

    print(f"\n{'='*80}\n")

    # Save results
    out_path = SCRIPT_DIR.parent / "output" / f"domain-anneal-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps({
        "date": datetime.now().isoformat(),
        "pattern_scores": pattern_scores,
        "results": [r for r in all_results if not r.get("skip")],
        "total_searches": total_searches,
        "cost": cost,
        "hard_failures": hard_fails,
    }, indent=2, default=str), encoding="utf-8")
    print(f"  Results saved: {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Domain search pattern annealer")
    parser.add_argument("--pattern", type=str, help="Filter to specific pattern name (substring match)")
    parser.add_argument("--dry-run", action="store_true", help="Show queries without executing")
    args = parser.parse_args()

    run_anneal(pattern_filter=args.pattern, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
