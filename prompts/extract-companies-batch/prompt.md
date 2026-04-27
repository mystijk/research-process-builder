# extract-companies-batch — Graduated Prompt

**Target model:** `gpt-4o-mini`
**API call:** `temperature=0`, `response_format={"type":"json_object"}`, `max_tokens=2000`
**Batch size:** 25 items per call
**Final score:** 1.0000 (range across reruns: 0.98–1.00, mean ~0.99)
**Baseline score:** 0.7594

---

## System message

```
You extract structured data from news search results. Output strict JSON only.
```

## User message template

`{items}` is replaced with the formatted list of `[N] TITLE: ... | SNIPPET: ...` lines (1-indexed within the batch).

```
Identify the COMPANY THAT RAISED FUNDING in each numbered news item.

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
- TITLE: "Lumio eyes Series A round after $4 million seed funding" SNIPPET: "Lumio eyes Series A round after $4 million seed funding..." -> {"company":"Lumio","is_funding":true}  // "eyes" still counts; company named in title
- TITLE: "TechCrunch Mobility: Elon's admission" SNIPPET: "A&K Robotics, a Vancouver maker of AVs, raised $8M Series A led by BDC..." -> {"company":"A&K Robotics","is_funding":true}
- TITLE: "AI Startup Secures $150M..." SNIPPET: "...Amperos Health raised Series A to enhance AI denial mgmt..." -> {"company":"Amperos Health","is_funding":true}
- TITLE: "Itaú Ventures led a Series A in Minter, a startup..." -> {"company":"Minter","is_funding":true}
- TITLE: "Elizabeth Dorman & Megan Gole's Era Raises $11M" SNIPPET: "<unrelated German startup>" -> {"company":"Era","is_funding":true}
- TITLE: "[Korean Startup Weekly News #115] Point2..." SNIPPET: "Dnotitia Raises $63.4M..." -> {"company":null,"is_funding":true}  // weekly roundup, still about funding
- TITLE: "Startups are raising big bucks!..." SNIPPET: "Mindbridge AI raises 8.4M... Whimstay Raises $10M..." -> {"company":null,"is_funding":true}  // roundup, still funding
- TITLE: "Fintech VC Funding Remains Steady..." SNIPPET: "...inKind's $450M, Vestwell's $385M Series E, Fundamental's $225M Series A" -> {"company":null,"is_funding":true}  // aggregator list, still funding
- TITLE: "Latest tech trends - InfotechLead" SNIPPET: "Verda secures $117M... Venture Capital Funding: Realm, Capsule Security, Prefix..." -> {"company":null,"is_funding":true}  // publisher feed of multiple deals, still funding
- TITLE: "OpenAI - 2026 Funding Rounds - Tracxn" SNIPPET: "BigBuy - raised $4.68M Series A..." -> {"company":null,"is_funding":true}  // Tracxn aggregator
- TITLE: "India-based Nava has raised US$22..." SNIPPET: "Foundry Group, key investor in Graphen, led a $23.5M round..." -> {"company":"Nava","is_funding":true}
- TITLE: "WhoaZone Equine - Facebook" SNIPPET: "...Series A investment into Etalon. Series A funding is..." -> {"company":"Etalon","is_funding":true}
- TITLE: "Alphabet may put up to $40B..." SNIPPET: "...• Thrive Capital led the round, with Microsoft, Nvidia... • OpenAI..." -> {"company":"OpenAI","is_funding":true}
- TITLE: "AI Market Watch's Post - LinkedIn" SNIPPET: "... raised 1.7B JPY Series A, led by Angel..." -> {"company":null,"is_funding":true}  // truncated name
- TITLE: "Warehoused Deal Closing for New Fund Managers" SNIPPET: "The company raises Series A at $20M... LPs inherit a 4x markup..." -> {"company":null,"is_funding":false}  // generic LP mechanics explainer
- TITLE: "India Post to open payments bank..." SNIPPET: "Verda secures $117M..." -> {"company":null,"is_funding":false}  // title is non-funding, snippet is unrelated feed

Return STRICT JSON: {"results":[{"idx":1,"company":"Auth0","is_funding":true},{"idx":2,"company":null,"is_funding":false}]}

Items:
{items}
```

## Items format

Each item per line, 1-indexed within the batch (NOT global idx):

```
[1] TITLE: <title text> | SNIPPET: <snippet text>
[2] TITLE: ... | SNIPPET: ...
```

## Notes for integration into pipeline_base.py

In Python, the prompt above uses raw `{` / `}` in JSON examples, so when used as a Python f-string or `.format()` template you must double the braces (`{{` / `}}`). The `candidates/v004.json` file in this directory has the format-ready string with doubled braces.
