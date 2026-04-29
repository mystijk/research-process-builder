import type { ConfidenceLevel, SignalScores } from "./types.js";

// Signal 1: Name quality
const HEADLINE_FRAMING =
  /\b(ex[-\s]|ceo['s]?|founder['s]?|backed|raises?|raised|secures?|closes?|funding|round|acqui|unveils?|launches?|announces?)\b|'s\s+\w+/i;
const MEDIA_OUTLET_NAMES =
  /\b(Inc42|TechCrunch|VentureBeat|Forbes|Reuters|Bloomberg|Axios|Crunchbase|PitchBook|AlleyWatch|FinSMEs|SiliconAngle|Dealroom|VCNewsDaily|TechEU|EU\.Startups|BusinessWire|PRNewswire)\b/i;
const VC_NAME_IN_COMPANY =
  /\b(Capital|Ventures|Partners|Fund|Investment|Advisors|Management|Sequoia|Andreessen|Bessemer|Greylock|Accel|Lightspeed|GV|YC|a16z|Khosla|NEA|Insight|Tiger Global|Coatue|General Catalyst|Goldman Sachs|Bain)\b/i;
const STARTUP_IN_NAME = /\bstartup\b/i;

function scoreNameQuality(companyName: string): [ConfidenceLevel, string] {
  const name = companyName.trim();
  if (!name || name.length < 2) return ["low", "empty or too short"];
  if (HEADLINE_FRAMING.test(name))
    return ["low", `headline framing in name: '${name.slice(0, 50)}'`];
  if (MEDIA_OUTLET_NAMES.test(name))
    return ["low", `media outlet name: '${name.slice(0, 50)}'`];
  if (STARTUP_IN_NAME.test(name))
    return ["low", `'startup' in name — likely headline extraction: '${name.slice(0, 50)}'`];
  if (VC_NAME_IN_COMPANY.test(name))
    return ["medium", `VC/fund term in name — may be investor not company: '${name.slice(0, 50)}'`];
  if (/^[A-Z]/.test(name) && name.length >= 3 && name.length <= 60)
    return ["high", "clean proper noun"];
  return ["medium", `ambiguous name format: '${name.slice(0, 50)}'`];
}

// Signal 2: Funding round explicitness
const FUNDING_ROUND_RE =
  /\b(?:Series\s+[A-E]|Seed|Pre[-\s]?Seed|Growth|Bridge|Extension|IPO\s+round)\b/i;
const AMOUNT_RE =
  /[$€£¥]\s*[\d,.]+\s*[MBmb](?:illion)?|\d+\s*(?:million|billion)/i;

function scoreFundingExplicit(title: string, snippet: string): [ConfidenceLevel, string] {
  if (FUNDING_ROUND_RE.test(title)) return ["high", "funding round type in title"];
  if (FUNDING_ROUND_RE.test(snippet)) return ["medium", "funding round type in snippet only"];
  if (AMOUNT_RE.test(`${title} ${snippet}`))
    return ["medium", "funding amount present but no explicit round type"];
  return ["low", "no funding round signal in title or snippet"];
}

// Signal 3: Source tier
// These lists are authoritative — copied from confidence_scorer.py.
// Note: vcnewsdaily.com is LOW here (dead source) even though filters.ts scored it TIER_S.
const TIER_HIGH_DOMAINS = new Set([
  "finsmes.com",
  "thesaasnews.com",
  "alleywatch.com",
  "businesswire.com",
  "prnewswire.com",
  "einpresswire.com",
  "techcrunch.com",
  "eu-startups.com",
  "tech.eu",
  "techround.co.uk",
  "ventureburn.com",
  "siliconangle.com",
  "pulse2.com",
]);

const TIER_MEDIUM_DOMAINS = new Set([
  "yahoo.com",
  "finance.yahoo.com",
  "entrepreneur.com",
  "businessinsider.com",
  "zdnet.com",
  "infotechlead.com",
  "citybiz.co",
  "biospace.com",
  "eu.36kr.com",
]);

const TIER_LOW_DOMAINS = new Set([
  "linkedin.com",
  "facebook.com",
  "instagram.com",
  "twitter.com",
  "x.com",
  "cdninstagram.com",
  "wsj.com",
  "ft.com",
  "vcnewsdaily.com",
  "t.co",
  "bit.ly",
  "amazonaws.com",
  "cloudfront.net",
  "binance.com",
]);

function normalizeDomain(domain: string): string {
  return domain
    .toLowerCase()
    .trim()
    .replace(/^https?:\/\//, "")
    .split("/")[0]
    .replace(/^www\./, "");
}

function scoreSourceTier(sourceDomain: string): [ConfidenceLevel, string] {
  const domain = normalizeDomain(sourceDomain);
  if (TIER_LOW_DOMAINS.has(domain)) return ["low", `low-tier source: ${domain}`];
  if (TIER_HIGH_DOMAINS.has(domain)) return ["high", `tier-HIGH source: ${domain}`];
  if (TIER_MEDIUM_DOMAINS.has(domain)) return ["medium", `tier-MEDIUM source: ${domain}`];
  return ["medium", `unknown source domain: ${domain}`];
}

function composite(signals: ConfidenceLevel[]): ConfidenceLevel {
  if (signals.includes("low")) return "low";
  if (signals.every((s) => s === "high")) return "high";
  return "medium";
}

export function scoreConfidence(
  companyName: string,
  title: string,
  snippet: string,
  sourceDomain: string
): SignalScores {
  const [nameQuality, nameReason] = scoreNameQuality(companyName);
  const [fundingExplicit, fundingReason] = scoreFundingExplicit(title, snippet);
  const [sourceTier, tierReason] = scoreSourceTier(sourceDomain);

  return {
    nameQuality,
    fundingExplicit,
    sourceTier,
    composite: composite([nameQuality, fundingExplicit, sourceTier]),
    reasons: [nameReason, fundingReason, tierReason],
  };
}
