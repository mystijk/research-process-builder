"""Iteration runner: pass version + system + user template inline."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from anneal import run_candidate

VERSIONS = {}

# ---- v002: Add explicit decision rules + handle is_funding semantics ----
VERSIONS["v002"] = {
    "system": "You extract structured data from news search results. Output strict JSON only.",
    "user_template": """Identify the COMPANY THAT RAISED FUNDING in each numbered news item.

DECISION RULES (apply in order):
1. is_funding=true if the item is about ANY company raising/securing/closing funding (even if multiple). is_funding=false ONLY for non-funding content (profile pages, generic explainers, 404 pages, unrelated news).
2. company = the SINGLE startup that received the money. Never an investor/VC firm. Never a publication name.
3. Return company=null if ANY of these apply:
   - Roundup / weekly digest / multi-company list (2+ funded companies named with no clear single subject)
   - Snippet is truncated mid-name with "..." before the company is identifiable
   - Title and snippet describe DIFFERENT funding deals (conflict, can't decide which is "the" subject)
   - Aggregator/data-platform listing (Tracxn, Crunchbase feed, publisher feed)

TITLE vs SNIPPET PRIORITY:
- If title clearly names a funded company with a funding verb (raises/secures/closes/lands/snags), TRUST TITLE even if snippet is unrelated boilerplate.
- If title is generic ("AI Startup Secures $X"), publisher column ("TechCrunch Mobility:..."), social platform junk ("X - Facebook", "X - LinkedIn", "X - Instagram"), or a person's possessive ("Jane Doe's Era Raises..." -> use "Era", not "Jane Doe"), USE SNIPPET to find the company.
- For investor-led syntax like "Itaú Ventures led a Series A in Minter", the funded company is the OBJECT after "in/into" — return "Minter", not the VC.
- For bullet-style snippets ("• Thrive Capital led the round... • OpenAI..."), the company is the one being described as the recipient (OpenAI here, since Thrive Capital "led the round" = investor).

Return STRICT JSON: {{"results":[{{"idx":1,"company":"Auth0","is_funding":true}},{{"idx":2,"company":null,"is_funding":false}}]}}

Items:
{items}""",
    "notes": "v002: explicit decision rules, title-vs-snippet priority, investor-led/bullet/possessive guidance",
}

# ---- v003: add few-shot examples for hard classes ----
VERSIONS["v003"] = {
    "system": "You extract structured data from news search results. Output strict JSON only.",
    "user_template": """Identify the COMPANY THAT RAISED FUNDING in each numbered news item.

RULES:
1. is_funding=true if the item is about ANY company raising funding. is_funding=false ONLY for non-funding (profile pages, explainers, 404s, unrelated news).
2. company = the SINGLE startup that got the money. NEVER an investor/VC firm. NEVER a publication name.
3. company=null if: roundup/multi-company digest, truncated/unrecoverable name, title+snippet describe DIFFERENT deals, aggregator listing (Tracxn/Crunchbase feed).

TITLE vs SNIPPET:
- Title names funded company with funding verb -> trust title even if snippet is unrelated.
- Title is generic ("AI Startup Secures..."), publisher column ("TechCrunch Mobility:..."), social junk ("...- Facebook/LinkedIn/Instagram"), or a person's possessive ("Jane's Era Raises..." -> "Era") -> use snippet.
- "Investor led a round in Company" -> Company is the OBJECT after "in/into".
- Bullet snippets where one entity "led the round" = investor; the other named entity is the funded co.

EXAMPLES:
- TITLE: "TechCrunch Mobility: Elon's admission" SNIPPET: "A&K Robotics, a Vancouver maker of AVs, raised $8M Series A led by BDC..." -> {{"company":"A&K Robotics","is_funding":true}}
- TITLE: "AI Startup Secures $150M..." SNIPPET: "...Amperos Health raised Series A to enhance AI denial mgmt..." -> {{"company":"Amperos Health","is_funding":true}}
- TITLE: "Itaú Ventures led a Series A in Minter, a startup..." -> {{"company":"Minter","is_funding":true}}
- TITLE: "Elizabeth Dorman & Megan Gole's Era Raises $11M" SNIPPET: "<unrelated German startup>" -> {{"company":"Era","is_funding":true}}
- TITLE: "[Korean Startup Weekly News #115] Point2..." SNIPPET: "Dnotitia Raises $63.4M..." -> {{"company":null,"is_funding":true}}  // weekly roundup
- TITLE: "Startups are raising big bucks! Latest funding..." SNIPPET: "Mindbridge AI raises 8.4M... Whimstay Raises $10M..." -> {{"company":null,"is_funding":true}}  // roundup
- TITLE: "OpenAI - 2026 Funding Rounds - Tracxn" SNIPPET: "BigBuy - raised $4.68M Series A..." -> {{"company":null,"is_funding":true}}  // Tracxn aggregator
- TITLE: "India-based Nava has raised US$22..." SNIPPET: "Foundry Group, key investor in Graphen, led a $23.5M round..." -> {{"company":"Nava","is_funding":true}}  // title wins on conflict
- TITLE: "WhoaZone Equine - Facebook" SNIPPET: "...Series A investment into Etalon. Series A funding is..." -> {{"company":"Etalon","is_funding":true}}
- TITLE: "Alphabet may put up to $40B..." SNIPPET: "...• Thrive Capital led the round, with Microsoft, Nvidia... • OpenAI..." -> {{"company":"OpenAI","is_funding":true}}
- TITLE: "AI Market Watch's Post - LinkedIn" SNIPPET: "... raised 1.7B JPY Series A, led by Angel..." -> {{"company":null,"is_funding":true}}  // truncated, name lost

Return STRICT JSON: {{"results":[{{"idx":1,"company":"Auth0","is_funding":true}},{{"idx":2,"company":null,"is_funding":false}}]}}

Items:
{items}""",
    "notes": "v003: v002 + 11 few-shot examples covering each failure class",
}

# ---- v004: tighten is_funding semantics + clarify "eyes" verb ----
VERSIONS["v004"] = {
    "system": "You extract structured data from news search results. Output strict JSON only.",
    "user_template": """Identify the COMPANY THAT RAISED FUNDING in each numbered news item.

CRITICAL: company and is_funding are INDEPENDENT.
- is_funding=true if the item is ANY way about a funding round (announced, closed, eyed, secured, raising, even multi-company roundups, even aggregator listings of past rounds). Funding verbs: raises/raised/secures/closes/lands/snags/announces/eyes (eyeing future round still counts).
- is_funding=false ONLY for: profile pages with no funding mention, generic explainers about VC mechanics, 404/empty pages, or news fully unrelated to funding.
- company = the SINGLE startup that got the money. Returning null does NOT make is_funding false. A roundup of 5 funded startups is is_funding=true with company=null.

NEVER return as company:
- An investor / VC firm / fund
- A publication name (TechCrunch, AI Market Watch, FemWealth, InforCapital, etc.)
- A person's name (founder, journalist)

RETURN company=null WHEN:
- Roundup / weekly digest / multi-company list (2+ funded companies named)
- Snippet truncates the company name with "..." before it can be read
- Title and snippet describe DIFFERENT funding deals (conflict where neither is clearly "the" subject)
- Aggregator listing (Tracxn / Crunchbase feed where title is unrelated to snippet contents)
- Publisher feed (multiple unrelated funded companies in the snippet)

TITLE vs SNIPPET PRIORITY:
- Title clearly names a funded company with a funding verb -> trust title even if snippet is unrelated boilerplate.
- Title generic ("AI Startup Secures..."), publisher column ("TechCrunch Mobility:..."), social junk ("...- Facebook/LinkedIn/Instagram"), or possessive ("Jane's Era Raises..." -> "Era") -> use snippet to find company.
- Investor-led syntax "X led a Series A in Y" -> Y is the funded company.
- Bullet snippets where one entity "led the round" = investor; the other named entity is the funded co.

EXAMPLES:
- TITLE: "Lumio eyes Series A round after $4 million seed funding" SNIPPET: "Lumio eyes Series A round after $4 million seed funding..." -> {{"company":"Lumio","is_funding":true}}  // "eyes" still counts; company named in title
- TITLE: "TechCrunch Mobility: Elon's admission" SNIPPET: "A&K Robotics, a Vancouver maker of AVs, raised $8M Series A led by BDC..." -> {{"company":"A&K Robotics","is_funding":true}}
- TITLE: "AI Startup Secures $150M..." SNIPPET: "...Amperos Health raised Series A to enhance AI denial mgmt..." -> {{"company":"Amperos Health","is_funding":true}}
- TITLE: "Itaú Ventures led a Series A in Minter, a startup..." -> {{"company":"Minter","is_funding":true}}
- TITLE: "Elizabeth Dorman & Megan Gole's Era Raises $11M" SNIPPET: "<unrelated German startup>" -> {{"company":"Era","is_funding":true}}
- TITLE: "[Korean Startup Weekly News #115] Point2..." SNIPPET: "Dnotitia Raises $63.4M..." -> {{"company":null,"is_funding":true}}  // weekly roundup, still about funding
- TITLE: "Startups are raising big bucks!..." SNIPPET: "Mindbridge AI raises 8.4M... Whimstay Raises $10M..." -> {{"company":null,"is_funding":true}}  // roundup, still funding
- TITLE: "Fintech VC Funding Remains Steady..." SNIPPET: "...inKind's $450M, Vestwell's $385M Series E, Fundamental's $225M Series A" -> {{"company":null,"is_funding":true}}  // aggregator list, still funding
- TITLE: "Latest tech trends - InfotechLead" SNIPPET: "Verda secures $117M... Venture Capital Funding: Realm, Capsule Security, Prefix..." -> {{"company":null,"is_funding":true}}  // publisher feed of multiple deals, still funding
- TITLE: "OpenAI - 2026 Funding Rounds - Tracxn" SNIPPET: "BigBuy - raised $4.68M Series A..." -> {{"company":null,"is_funding":true}}  // Tracxn aggregator
- TITLE: "India-based Nava has raised US$22..." SNIPPET: "Foundry Group, key investor in Graphen, led a $23.5M round..." -> {{"company":"Nava","is_funding":true}}
- TITLE: "WhoaZone Equine - Facebook" SNIPPET: "...Series A investment into Etalon. Series A funding is..." -> {{"company":"Etalon","is_funding":true}}
- TITLE: "Alphabet may put up to $40B..." SNIPPET: "...• Thrive Capital led the round, with Microsoft, Nvidia... • OpenAI..." -> {{"company":"OpenAI","is_funding":true}}
- TITLE: "AI Market Watch's Post - LinkedIn" SNIPPET: "... raised 1.7B JPY Series A, led by Angel..." -> {{"company":null,"is_funding":true}}  // truncated name
- TITLE: "Warehoused Deal Closing for New Fund Managers" SNIPPET: "The company raises Series A at $20M... LPs inherit a 4x markup..." -> {{"company":null,"is_funding":false}}  // generic LP mechanics explainer
- TITLE: "India Post to open payments bank..." SNIPPET: "Verda secures $117M..." -> {{"company":null,"is_funding":false}}  // title is non-funding, snippet is unrelated feed

Return STRICT JSON: {{"results":[{{"idx":1,"company":"Auth0","is_funding":true}},{{"idx":2,"company":null,"is_funding":false}}]}}

Items:
{items}""",
    "notes": "v004: clarify is_funding independence from company=null; add Lumio 'eyes' + roundup-still-funding examples",
}

# ---- v005: subtractive — keep only highest-leverage examples (~half) ----
VERSIONS["v005"] = {
    "system": "You extract structured data from news search results. Output strict JSON only.",
    "user_template": """Identify the COMPANY THAT RAISED FUNDING in each numbered news item.

CRITICAL: company and is_funding are INDEPENDENT.
- is_funding=true if the item is in any way about a funding round (closed, eyed, secured, raising, multi-company roundups, aggregator listings of past rounds count). Funding verbs include eyes/raises/secures/closes/lands/snags/announces.
- is_funding=false ONLY for: profile pages, generic explainers about VC mechanics, 404/empty pages, news fully unrelated to funding.
- company = the SINGLE startup that got the money. Returning null does NOT make is_funding false.

NEVER return as company: investor/VC firm, publication name, person name.

RETURN company=null WHEN:
- Roundup / weekly digest / multi-company list (2+ funded companies named)
- Snippet truncates the company name with "..." before it can be read
- Title and snippet describe DIFFERENT funding deals (conflict)
- Aggregator listing (Tracxn / Crunchbase / publisher feed)

TITLE vs SNIPPET PRIORITY:
- Title clearly names a funded company with a funding verb -> trust title.
- Title generic ("AI Startup Secures..."), publisher column ("TechCrunch Mobility:..."), social junk ("...- Facebook/LinkedIn/Instagram"), or possessive ("Jane's Era Raises..." -> "Era") -> use snippet.
- "Investor led a Series A in Y" -> Y is the funded company, never the investor.
- Bullet snippets: the entity that "led the round" is the investor; the other named entity is the funded co.

EXAMPLES:
- TITLE: "Lumio eyes Series A round after $4M seed" -> {{"company":"Lumio","is_funding":true}}
- TITLE: "TechCrunch Mobility: Elon's admission" SNIPPET: "A&K Robotics raised $8M Series A..." -> {{"company":"A&K Robotics","is_funding":true}}
- TITLE: "AI Startup Secures $150M..." SNIPPET: "...Amperos Health raised Series A..." -> {{"company":"Amperos Health","is_funding":true}}
- TITLE: "Itaú Ventures led a Series A in Minter, a startup..." -> {{"company":"Minter","is_funding":true}}
- TITLE: "Elizabeth Dorman & Megan Gole's Era Raises $11M" SNIPPET: "<unrelated>" -> {{"company":"Era","is_funding":true}}
- TITLE: "[Korean Startup Weekly News]" SNIPPET: "Dnotitia Raises $63.4M..." -> {{"company":null,"is_funding":true}}  // roundup
- TITLE: "Latest tech trends - InfotechLead" SNIPPET: "Verda secures $117M... VC Funding: Realm, Capsule Security, Prefix" -> {{"company":null,"is_funding":true}}  // feed
- TITLE: "OpenAI - 2026 Funding Rounds - Tracxn" SNIPPET: "BigBuy raised $4.68M..." -> {{"company":null,"is_funding":true}}
- TITLE: "WhoaZone Equine - Facebook" SNIPPET: "...investment into Etalon..." -> {{"company":"Etalon","is_funding":true}}
- TITLE: "Alphabet may put $40B..." SNIPPET: "• Thrive Capital led... • OpenAI..." -> {{"company":"OpenAI","is_funding":true}}
- TITLE: "Warehoused Deal Closing for Fund Managers" SNIPPET: "The company raises Series A at $20M... LPs inherit a 4x markup..." -> {{"company":null,"is_funding":false}}  // generic explainer

Return STRICT JSON: {{"results":[{{"idx":1,"company":"Auth0","is_funding":true}},{{"idx":2,"company":null,"is_funding":false}}]}}

Items:
{items}""",
    "notes": "v005: subtractive — compressed examples, removed 4 redundant ones",
}

if __name__ == "__main__":
    version = sys.argv[1]
    v = VERSIONS[version]
    run_candidate(version, v["system"], v["user_template"], v["notes"])
