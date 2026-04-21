"""
Series A Daily Discovery Pipeline

Four-stage pipeline:
  1. Parallel discovery via SerperDev (10 queries, search endpoint, tbs:qdr:d)
  2. Score, filter to Series A, dedup by company
  3. Enrich: scrape best source, extract structured fields, domain lookup
  4. Output CSV + JSON

Usage:
    py scripts/series_a_pipeline.py                     # full run, daily
    py scripts/series_a_pipeline.py --tbs qdr:w         # weekly catch-up
    py scripts/series_a_pipeline.py --stage 1            # discovery only
    py scripts/series_a_pipeline.py --stage 2            # score/filter only (reads stage 1 output)
    py scripts/series_a_pipeline.py --skip-enrich        # stages 1-2 + CSV (no scraping)
    py scripts/series_a_pipeline.py --dry-run            # preview queries
"""

import json
import sys
import os
import re
import csv
import time
import argparse
import concurrent.futures
from pathlib import Path
from datetime import datetime
from typing import Optional

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT / "leadgrow-hq" / "tools" / "shared-scripts"))

from dotenv import load_dotenv
load_dotenv(WORKSPACE_ROOT / ".env")
# Also try user-level .env
load_dotenv(Path.home() / ".env", override=False)

import serper_search
import requests

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR.parent / "output"
STAGE_DIR = SCRIPT_DIR.parent / "output" / "stages"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SPIDER_API_KEY = os.getenv("SPIDER_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL") or os.getenv("SUPABASE_PROJECT_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")

# ---------------------------------------------------------------------------
# Query Definitions (validated 2026-04-20, 88% GT hit rate)
# ---------------------------------------------------------------------------

AGENT_A_QUERIES = [
    {"id": "q3", "query": "site:thesaasnews.com Series A", "num": 30, "desc": "TheSaaSNews"},
    {"id": "q4", "query": "site:finsmes.com Series A", "num": 30, "desc": "FinSMEs"},
    {"id": "q5", "query": "site:alleywatch.com funding report", "num": 10, "desc": "AlleyWatch"},
    {"id": "q9", "query": "site:vcnewsdaily.com Series A", "num": 10, "desc": "VCNewsDaily"},
    {"id": "q10", "query": "site:infotechlead.com venture capital funding", "num": 10, "desc": "InfotechLead"},
]

AGENT_B_QUERIES = [
    {"id": "q1", "query": '"Series A" raises OR raised OR funding OR round million', "num": 30, "desc": "broad sweep"},
    {"id": "q2", "query": '"Series A" announces OR secures OR closes OR completes funding', "num": 20, "desc": "announcement language"},
    {"id": "q6", "query": '"Series A" site:businesswire.com OR site:prnewswire.com OR site:einpresswire.com', "num": 10, "desc": "press wires"},
    {"id": "q7", "query": '"led the round" OR "led the Series A" OR "led a" Series A investment startup', "num": 20, "desc": "VC language"},
    {"id": "q8", "query": '"Series A" startup funding site:eu-startups.com OR site:tech.eu OR site:techround.co.uk', "num": 10, "desc": "European"},
]


def normalize_company_name(name: str) -> str:
    """Strip Inc/Ltd/Corp/etc and lowercase for dedup."""
    name = name.strip()
    # Strip legal suffixes
    name = re.sub(r'\s*[,.]?\s*\b(Inc|Ltd|Corp|LLC|GmbH|Co|PLC|SA|AG|BV|Pty|SAS|SRL)\b\.?\s*$', '', name, flags=re.IGNORECASE)
    # Strip "Tag" suffix (tech.eu puts this on tag pages)
    name = re.sub(r'\s+Tag$', '', name, flags=re.IGNORECASE)
    # Strip trailing punctuation
    name = re.sub(r'[\s,.\-:;]+$', '', name)
    return name.lower().strip()


# ---------------------------------------------------------------------------
# STAGE 1: Discovery
# ---------------------------------------------------------------------------

def run_single_query(qdef: dict, tbs: str) -> dict:
    """Run one SerperDev query and return structured results."""
    original_num = serper_search.DEFAULT_NUM_RESULTS
    serper_search.DEFAULT_NUM_RESULTS = qdef["num"]

    try:
        raw = serper_search.search(query=qdef["query"], news=False, tbs=tbs)
    except Exception as e:
        serper_search.DEFAULT_NUM_RESULTS = original_num
        return {"query_id": qdef["id"], "desc": qdef["desc"], "error": str(e), "results": []}
    finally:
        serper_search.DEFAULT_NUM_RESULTS = original_num

    items = raw.get("organic", [])
    results = []
    for item in items:
        results.append({
            "company_name_raw": "",
            "amount_raw": "",
            "round_type_raw": "",
            "source_url": item.get("link", ""),
            "source_domain": item.get("link", "").split("/")[2] if "://" in item.get("link", "") else "",
            "snippet": item.get("snippet", "")[:300],
            "title": item.get("title", ""),
            "query_source": qdef["id"],
        })

    return {
        "query_id": qdef["id"],
        "desc": qdef["desc"],
        "result_count": len(results),
        "results": results,
    }


def run_discovery(tbs: str, dry_run: bool = False) -> list[dict]:
    """Stage 1: Run all queries in parallel (Agent A + Agent B)."""
    all_queries = AGENT_A_QUERIES + AGENT_B_QUERIES

    if dry_run:
        for q in all_queries:
            print(f"  [DRY] {q['id']}: {q['desc']} (num={q['num']})")
        return []

    all_results = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(run_single_query, q, tbs): q for q in all_queries}
        for future in concurrent.futures.as_completed(futures):
            qdef = futures[future]
            result = future.result()
            count = result.get("result_count", 0)
            err = result.get("error", "")
            status = f"ERROR: {err}" if err else f"{count} results"
            print(f"  [{result['query_id']}] {result['desc']}: {status}")
            all_results.extend(result.get("results", []))

    print(f"\n  Stage 1 total: {len(all_results)} raw results from {len(all_queries)} queries")
    return all_results


# ---------------------------------------------------------------------------
# STAGE 2: Score, Filter, Dedup
# ---------------------------------------------------------------------------

VC_PATTERNS = re.compile(
    r'\b(Capital|Ventures|Partners|Fund|Investment|Advisors|Management|'
    r'Sequoia|Andreessen|Bessemer|Greylock|Accel|Lightspeed|GV|YC|'
    r'a16z|Khosla|NEA|Insight|Tiger Global|Coatue|General Catalyst)\b',
    re.IGNORECASE
)

NON_SERIES_A = re.compile(
    r'\b(Series\s+[B-Z]|Pre-Seed|pre-seed|Pre-IPO|IPO|Debt|Grant|'
    r'acquisition|acquires|acquired|merger|SPAC|refinanc)',
    re.IGNORECASE
)

SOFT_NON_A = re.compile(r'\b(Seed|Growth)\b', re.IGNORECASE)

SERIES_A_PATTERN = re.compile(r'\bSeries\s+A\b', re.IGNORECASE)
AMOUNT_PATTERN = re.compile(r'[\$\u20ac\u00a3\u00a5]\s*[\d,.]+\s*[MBmb](?:illion)?|\d+\s*(?:million|billion)', re.IGNORECASE)

NOISE_PATTERNS = re.compile(
    r'(?:Series A activity|weekly recap|funding recap|venture market|job search|'
    r'quarterly.*dividend|financial results|earnings|stock|preferred stock|'
    r'broadband|announces common|\bTag\b\s*[-|]|\bTag\s*$)',
    re.IGNORECASE
)

TIER_S_DOMAINS = {
    "thesaasnews.com", "finsmes.com", "alleywatch.com", "infotechlead.com", "vcnewsdaily.com"
}
TIER_A_DOMAINS = {
    "businesswire.com", "prnewswire.com", "einpresswire.com", "ventureburn.com",
    "tech.eu", "eu-startups.com", "pulse2.com", "siliconangle.com"
}


def extract_company_name_from_title(title: str) -> str:
    """Best-effort company name extraction from article title."""
    # Pattern: "CompanyName Raises $XM..." or "CompanyName Secures..."
    m = re.match(r'^([A-Z][\w\s.&\'-]{1,40}?)\s+(?:raises?|secures?|closes?|announces?|gets?|lands?|nabs?|bags?|receives?|completes?)\b', title, re.IGNORECASE)
    if m:
        name = m.group(1).strip()
        if not VC_PATTERNS.search(name):
            return name

    # Pattern: "... in CompanyName" or "... into CompanyName"
    m = re.search(r'(?:in|into|backs?|for)\s+([A-Z][\w\s.&\'-]{1,30}?)(?:\s*[,.]|\s+to\b|\s+for\b|$)', title)
    if m:
        name = m.group(1).strip()
        if not VC_PATTERNS.search(name):
            return name

    return ""


def score_and_filter(raw_results: list[dict]) -> dict:
    """Stage 2: Filter to Series A, dedup, score."""
    candidates = {}
    filtered_out = []

    for r in raw_results:
        title = r.get("title", "")
        snippet = r.get("snippet", "")
        combined = f"{title} {snippet}"
        url = r.get("source_url", "")
        domain = r.get("source_domain", "")

        # Noise filter — market reports, listicles, financial filings
        if NOISE_PATTERNS.search(title):
            filtered_out.append({"title": title[:80], "reason": "noise (report/listicle/filing)", "url": url})
            continue

        # Title is authoritative — snippet may contain text from adjacent articles
        title_has_series_a = bool(SERIES_A_PATTERN.search(title))
        title_has_hard_non_a = bool(NON_SERIES_A.search(title))
        title_has_soft_non_a = bool(SOFT_NON_A.search(title))

        has_series_a = bool(SERIES_A_PATTERN.search(combined))
        has_hard_non_a = bool(NON_SERIES_A.search(combined))

        # Title-level hard non-A always kills (most reliable signal)
        if title_has_hard_non_a:
            filtered_out.append({"title": title[:80], "reason": "non-Series A in title", "url": url})
            continue

        # Title says Seed/Growth with no Series A in title — kill even if snippet has "Series A"
        if title_has_soft_non_a and not title_has_series_a:
            filtered_out.append({"title": title[:80], "reason": "Seed/Growth in title, no Series A", "url": url})
            continue

        # Combined-level hard non-A (snippet only) still kills if no Series A anywhere
        if has_hard_non_a and not has_series_a:
            filtered_out.append({"title": title[:80], "reason": "non-Series A round detected", "url": url})
            continue

        # Must have Series A OR strong funding language
        if not has_series_a:
            if not re.search(r'(?:raises?|raised|secures?|closes?)\s+[\$\u20ac\u00a3]', combined, re.IGNORECASE):
                filtered_out.append({"title": title[:80], "reason": "no Series A and no funding amount", "url": url})
                continue

        # Extract company name
        company = extract_company_name_from_title(title)
        if not company:
            # Fallback: take title before separator
            fallback = title.split(" - ")[0].split(" | ")[0]
            # Strip "Raises/Secures" suffix
            fallback = re.split(r'\s+(?:Raises?|Secures?|Closes?|Announces?)\b', fallback)[0]
            company = fallback.strip()[:50]

        # Clean up display name
        company = re.sub(r'\s+Tag$', '', company, flags=re.IGNORECASE).strip()
        company = re.sub(r'^\[PDF\]\s*', '', company).strip()
        pass

        if not company or len(company) < 3:
            continue

        # Skip generic/garbage names
        if company.lower() in {"u.s", "u.s.", "us", "series a", "series a funding", "funding", "startup", "the"}:
            continue

        # Skip very long "company names" — likely article titles not parsed well
        if len(company) > 45:
            filtered_out.append({"title": title[:80], "reason": "company name too long (likely bad parse)", "url": url})
            continue

        # Check if it's a VC name not a company
        needs_disambiguation = bool(VC_PATTERNS.search(company))

        # Extract amount
        amount_match = AMOUNT_PATTERN.search(combined)
        amount = amount_match.group(0) if amount_match else ""

        # Score source quality
        if domain in TIER_S_DOMAINS:
            source_quality = 4
        elif domain in TIER_A_DOMAINS:
            source_quality = 5
        elif "crunchbase" in domain or "techcrunch" in domain:
            source_quality = 3
        else:
            source_quality = 2

        # Score data completeness
        data_completeness = 1
        if company:
            data_completeness += 1
        if amount:
            data_completeness += 1
        if has_series_a:
            data_completeness += 1
        if re.search(r'(?:led by|investors?|participated)', combined, re.IGNORECASE):
            data_completeness += 1

        score = source_quality * data_completeness

        # Dedup by normalized company name
        norm = normalize_company_name(company)

        if norm not in candidates:
            candidates[norm] = {
                "company_name": company.strip(),
                "company_name_normalized": norm,
                "amount": amount,
                "round_type": "Series A" if has_series_a else "Unknown",
                "needs_disambiguation": needs_disambiguation,
                "sources": [],
                "best_score": 0,
                "best_source_url": "",
            }

        candidates[norm]["sources"].append({
            "url": url,
            "domain": domain,
            "score": score,
            "query_source": r.get("query_source", ""),
            "title": title[:100],
        })

        if score > candidates[norm]["best_score"]:
            candidates[norm]["best_score"] = score
            candidates[norm]["best_source_url"] = url
            if amount and not candidates[norm]["amount"]:
                candidates[norm]["amount"] = amount

    # Sort by score descending
    companies = sorted(candidates.values(), key=lambda x: x["best_score"], reverse=True)

    print(f"\n  Stage 2: {len(raw_results)} raw -> {len(companies)} companies (filtered {len(filtered_out)})")
    for c in companies:
        flag = " [VC?]" if c["needs_disambiguation"] else ""
        amt = (c['amount'] or '?').encode('ascii', 'replace').decode()
        name = c['company_name'].encode('ascii', 'replace').decode()
        print(f"    {name}{flag} - {amt} - score {c['best_score']} - {len(c['sources'])} sources")

    return {
        "companies": companies,
        "filtered_out": filtered_out,
        "stats": {
            "raw_count": len(raw_results),
            "company_count": len(companies),
            "filtered_count": len(filtered_out),
        }
    }


# ---------------------------------------------------------------------------
# STAGE 3: Enrich & Extract
# ---------------------------------------------------------------------------

def fetch_url(url: str) -> Optional[str]:
    """Fetch URL content. Spider Cloud primary, requests fallback."""
    # Spider Cloud primary — handles 403s, returns clean markdown
    if SPIDER_API_KEY:
        try:
            resp = requests.post(
                "https://api.spider.cloud/crawl",
                headers={
                    "Authorization": f"Bearer {SPIDER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={"url": url, "limit": 1, "return_format": "markdown"},
                timeout=20,
            )
            if resp.status_code == 200:
                data = resp.json()
                content = ""
                if isinstance(data, list) and data:
                    content = data[0].get("content", "")
                elif isinstance(data, dict):
                    content = data.get("content", "")
                if content and len(content) > 200:
                    return content[:15000]
        except Exception:
            pass

    # Fallback: direct requests
    try:
        resp = requests.get(url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (compatible; LeadGrow/1.0)"
        })
        if resp.status_code == 200 and len(resp.text) > 200:
            return resp.text[:15000]
    except Exception:
        pass

    return None


def extract_with_openai(article_text: str, company_hint: str, amount_hint: str) -> Optional[dict]:
    """Use GPT-4o-mini to extract structured funding data from article text."""
    if not OPENAI_API_KEY:
        return None

    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o-mini",
                "temperature": 0,
                "max_tokens": 500,
                "messages": [
                    {"role": "system", "content": "You extract structured funding data from articles. Return valid JSON only, no markdown fences, no explanation."},
                    {"role": "user", "content": f"""Extract Series A funding data from this article.

Company hint: {company_hint}
Amount hint: {amount_hint}

Article:
{article_text[:8000]}

Return exactly this JSON:
{{"company_name": "...", "company_domain": "...", "amount_raised": "...", "lead_investors": "...", "round_reasoning": "..."}}

Rules:
- company_name = the company that RAISED money (NOT the investor/VC)
- company_domain = their website domain (e.g. zenskar.com). "not_stated" if not in article
- amount_raised = exact amount with currency symbol (e.g. "$15M", "EUR10M", "KRW 90B")
- lead_investors = who led the round, comma-separated. "not_stated" if unknown
- round_reasoning = why they raised / what funds are for, 1-2 sentences. "not_stated" if unknown
- If this is NOT actually a Series A funding announcement, set company_name to "NOT_SERIES_A" """},
                ],
            },
            timeout=30,
        )
        if resp.status_code == 200:
            content = resp.json()["choices"][0]["message"]["content"]
            content = content.strip()
            if content.startswith("```"):
                content = re.sub(r'^```(?:json)?\s*', '', content)
                content = re.sub(r'\s*```$', '', content)
            return json.loads(content)
    except Exception as e:
        print(f"    OpenAI extraction error: {e}")

    return None


def lookup_domain(company_name: str) -> str:
    """Search for company's official website domain."""
    original_num = serper_search.DEFAULT_NUM_RESULTS
    serper_search.DEFAULT_NUM_RESULTS = 5
    try:
        results = serper_search.search(f"{company_name} official website")
        items = results.get("organic", [])
        for item in items:
            link = item.get("link", "")
            domain = link.split("/")[2] if "://" in link else ""
            # Skip known non-company domains
            if any(skip in domain for skip in [
                "linkedin.com", "crunchbase.com", "wikipedia.org", "twitter.com",
                "facebook.com", "bloomberg.com", "pitchbook.com", "glassdoor.com",
                "indeed.com", "ycombinator.com", "github.com"
            ]):
                continue
            return domain
    except Exception:
        pass
    finally:
        serper_search.DEFAULT_NUM_RESULTS = original_num
    return "not_found"


def enrich_companies(scored: dict) -> list[dict]:
    """Stage 3: Scrape, extract, and enrich each company."""
    companies = scored["companies"]
    enriched = []

    for i, company in enumerate(companies):
        name = company["company_name"]
        print(f"\n  [{i+1}/{len(companies)}] Enriching: {name}")

        # Scrape best source
        article_text = None
        source_url = company["best_source_url"]
        if source_url:
            print(f"    Scraping {source_url[:80]}...")
            article_text = fetch_url(source_url)
            if article_text:
                print(f"    Got {len(article_text)} chars")
            else:
                print(f"    Scrape failed, trying next source...")
                for src in company["sources"]:
                    if src["url"] != source_url:
                        article_text = fetch_url(src["url"])
                        if article_text:
                            source_url = src["url"]
                            print(f"    Fallback worked: {src['url'][:80]}")
                            break

        # Extract with GPT-4o-mini
        extracted = None
        if article_text and OPENAI_API_KEY:
            print(f"    Extracting with GPT-4o-mini...")
            extracted = extract_with_openai(article_text, name, company.get("amount", ""))
            if extracted and extracted.get("company_name") == "NOT_SERIES_A":
                print(f"    FILTERED: GPT says not Series A")
                continue

        # Domain lookup if needed
        domain = "not_found"
        if extracted and extracted.get("company_domain") and extracted["company_domain"] != "not_stated":
            domain = extracted["company_domain"]
        else:
            print(f"    Looking up domain...")
            domain = lookup_domain(name)

        record = {
            "company_name": extracted.get("company_name", name) if extracted else name,
            "company_domain": domain,
            "amount_raised": extracted.get("amount_raised", company.get("amount", "")) if extracted else company.get("amount", ""),
            "round_type": company.get("round_type", "Series A"),
            "source_url": source_url,
            "lead_investors": extracted.get("lead_investors", "not_stated") if extracted else "not_stated",
            "round_reasoning": extracted.get("round_reasoning", "not_stated") if extracted else "not_stated",
            "source_count": len(company["sources"]),
            "score": company["best_score"],
            "discovered_by": ",".join(set(s["query_source"] for s in company["sources"])),
        }
        enriched.append(record)
        display_name = record['company_name'].encode('ascii', 'replace').decode()
        display_amt = record['amount_raised'].encode('ascii', 'replace').decode()
        print(f"    => {display_name} | {record['company_domain']} | {display_amt}")

        time.sleep(0.5)

    print(f"\n  Stage 3: {len(enriched)} companies enriched")
    return enriched


# ---------------------------------------------------------------------------
# STAGE 4: Output
# ---------------------------------------------------------------------------

def write_output(enriched: list[dict], date_str: str):
    """Stage 4: Write CSV and JSON output."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Daily CSV
    csv_path = OUTPUT_DIR / f"series-a-{date_str}.csv"
    fieldnames = [
        "date", "company_name", "company_domain", "amount_raised", "round_type",
        "source_url", "lead_investors", "round_reasoning", "discovered_by", "source_count", "score"
    ]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in enriched:
            row = {"date": date_str, **{k: r.get(k, "") for k in fieldnames if k != "date"}}
            writer.writerow(row)

    print(f"\n  CSV: {csv_path} ({len(enriched)} rows)")

    # Daily JSON
    json_path = OUTPUT_DIR / f"series-a-{date_str}.json"
    output_json = {
        "date": date_str,
        "series_a_count": len(enriched),
        "companies": enriched,
        "metadata": {
            "pipeline_version": "1.0",
            "tbs": "qdr:d",
            "generated_at": datetime.now().isoformat(),
        }
    }
    json_path.write_text(json.dumps(output_json, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  JSON: {json_path}")

    # Append to master CSV
    master_path = OUTPUT_DIR / "series-a-master.csv"
    write_header = not master_path.exists()
    with open(master_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        for r in enriched:
            row = {"date": date_str, **{k: r.get(k, "") for k in fieldnames if k != "date"}}
            writer.writerow(row)

    print(f"  Master CSV: {master_path} (appended {len(enriched)} rows)")

    # Supabase upsert
    if SUPABASE_URL and SUPABASE_KEY:
        if check_supabase_table():
            print(f"\n  Pushing to Supabase...")
            upserted = push_to_supabase(enriched, date_str)
            print(f"  Supabase: {upserted}/{len(enriched)} rows upserted")
        else:
            print(f"\n  Supabase: table 'series_a_discoveries' not found")
            create_supabase_table()
    else:
        print(f"\n  Supabase: SKIPPED (no SUPABASE_URL/SUPABASE_KEY)")

    return csv_path, json_path


def supabase_headers(prefer: str = None) -> dict:
    h = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        h["Prefer"] = prefer
    return h


def check_supabase_table() -> bool:
    """Check if series_a_discoveries table exists."""
    try:
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/series_a_discoveries?limit=1",
            headers=supabase_headers(),
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False


def create_supabase_table() -> bool:
    """Create the series_a_discoveries table via Supabase RPC (requires service key or SQL editor)."""
    schema_sql = """
    create table if not exists series_a_discoveries (
      id bigint generated always as identity primary key,
      discovered_date date not null,
      company_name text not null,
      company_domain text,
      amount_raised text,
      round_type text default 'Series A',
      source_url text,
      lead_investors text,
      round_reasoning text,
      discovered_by text,
      source_count integer default 1,
      score integer default 0,
      pipeline_version text default '1.0',
      created_at timestamptz default now(),
      unique (company_name, discovered_date)
    );
    create index if not exists idx_series_a_date on series_a_discoveries (discovered_date desc);
    create index if not exists idx_series_a_company on series_a_discoveries (company_name);
    """
    # Try via Supabase Management API
    mcp_token = os.getenv("SUPABASE_MCP_TOKEN")
    if mcp_token and SUPABASE_URL:
        ref = SUPABASE_URL.replace("https://", "").split(".")[0]
        try:
            resp = requests.post(
                f"https://api.supabase.com/v1/projects/{ref}/database/query",
                headers={
                    "Authorization": f"Bearer {mcp_token}",
                    "Content-Type": "application/json",
                },
                json={"query": schema_sql},
                timeout=15,
            )
            if resp.status_code == 200 or resp.status_code == 201:
                print("    Table created via Management API")
                return True
            else:
                print(f"    Management API: {resp.status_code} {resp.text[:150]}")
        except Exception as e:
            print(f"    Management API error: {e}")

    print("    Run scripts/supabase_schema.sql in Supabase SQL Editor to create the table.")
    return False


def push_to_supabase(enriched: list[dict], date_str: str) -> int:
    """Upsert enriched companies to Supabase. Returns count of successful upserts."""
    rows = []
    for r in enriched:
        rows.append({
            "discovered_date": date_str,
            "company_name": r.get("company_name", ""),
            "company_domain": r.get("company_domain", ""),
            "amount_raised": r.get("amount_raised", ""),
            "round_type": r.get("round_type", "Series A"),
            "source_url": r.get("source_url", ""),
            "lead_investors": r.get("lead_investors", "not_stated"),
            "round_reasoning": r.get("round_reasoning", "not_stated"),
            "discovered_by": r.get("discovered_by", ""),
            "source_count": r.get("source_count", 1),
            "score": r.get("score", 0),
            "pipeline_version": "1.0",
        })

    try:
        resp = requests.post(
            f"{SUPABASE_URL}/rest/v1/series_a_discoveries",
            headers=supabase_headers(prefer="resolution=merge-duplicates"),
            json=rows,
            timeout=15,
        )
        if resp.status_code in (200, 201):
            return len(rows)
        else:
            print(f"    Supabase error {resp.status_code}: {resp.text[:200]}")
            return 0
    except Exception as e:
        print(f"    Supabase error: {e}")
        return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Series A Daily Discovery Pipeline")
    parser.add_argument("--tbs", default="qdr:d", help="Time filter (qdr:d=day, qdr:w=week)")
    parser.add_argument("--stage", type=int, help="Run only this stage (1-4)")
    parser.add_argument("--skip-enrich", action="store_true", help="Skip stage 3 (scraping/extraction)")
    parser.add_argument("--dry-run", action="store_true", help="Preview queries without running")
    parser.add_argument("--max-enrich", type=int, default=20, help="Max companies to enrich in stage 3")
    args = parser.parse_args()

    date_str = datetime.now().strftime("%Y-%m-%d")
    STAGE_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  SERIES A DAILY PIPELINE -- {date_str}")
    print(f"  TBS: {args.tbs} | Skip enrich: {args.skip_enrich}")
    print(f"  API keys: OpenAI={'YES' if OPENAI_API_KEY else 'NO'} | Spider={'YES' if SPIDER_API_KEY else 'NO'} | Supabase={'YES' if (SUPABASE_URL and SUPABASE_KEY) else 'NO'}")
    print(f"{'='*60}")

    # --- STAGE 1: Discovery ---
    stage1_file = STAGE_DIR / f"stage1-{date_str}.json"

    if args.stage and args.stage > 1 and stage1_file.exists():
        print(f"\n  Loading stage 1 from {stage1_file}")
        raw_results = json.loads(stage1_file.read_text(encoding="utf-8"))
    else:
        print(f"\n  STAGE 1: DISCOVERY")
        raw_results = run_discovery(args.tbs, args.dry_run)
        if args.dry_run:
            return
        stage1_file.write_text(json.dumps(raw_results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  Saved: {stage1_file}")

    if args.stage == 1:
        print("\n  Done (stage 1 only)")
        return

    # --- STAGE 2: Score & Filter ---
    print(f"\n  STAGE 2: SCORE & FILTER")
    scored = score_and_filter(raw_results)

    stage2_file = STAGE_DIR / f"stage2-{date_str}.json"
    stage2_file.write_text(json.dumps(scored, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Saved: {stage2_file}")

    if args.stage == 2:
        print("\n  Done (stage 2 only)")
        return

    # --- STAGE 3: Enrich ---
    if args.skip_enrich:
        print(f"\n  STAGE 3: SKIPPED (--skip-enrich)")
        enriched = []
        for c in scored["companies"]:
            enriched.append({
                "company_name": c["company_name"],
                "company_domain": "not_enriched",
                "amount_raised": c.get("amount", ""),
                "round_type": c.get("round_type", "Series A"),
                "source_url": c["best_source_url"],
                "lead_investors": "not_enriched",
                "round_reasoning": "not_enriched",
                "source_count": len(c["sources"]),
                "score": c["best_score"],
                "discovered_by": ",".join(set(s["query_source"] for s in c["sources"])),
            })
    else:
        print(f"\n  STAGE 3: ENRICH & EXTRACT (max {args.max_enrich})")
        # Limit enrichment to top N by score
        scored_limited = dict(scored)
        scored_limited["companies"] = scored["companies"][:args.max_enrich]
        enriched = enrich_companies(scored_limited)

    if args.stage == 3:
        stage3_file = STAGE_DIR / f"stage3-{date_str}.json"
        stage3_file.write_text(json.dumps(enriched, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  Saved: {stage3_file}")
        print("\n  Done (stage 3 only)")
        return

    # --- STAGE 4: Output ---
    print(f"\n  STAGE 4: OUTPUT")
    csv_path, json_path = write_output(enriched, date_str)

    print(f"\n{'='*60}")
    print(f"  PIPELINE COMPLETE")
    print(f"  Companies found: {len(enriched)}")
    print(f"  CSV: {csv_path}")
    print(f"  JSON: {json_path}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
