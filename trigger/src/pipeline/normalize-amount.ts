// Static 3-month average FX rates vs USD. Refresh quarterly from ECB/Frankfurter.
const FX_RATES: Record<string, number> = {
  USD: 1.0,
  EUR: 1.08,
  GBP: 1.27,
  KRW: 0.00072,
  JPY: 0.0067,
  INR: 0.012,
  CHF: 1.13,
  CAD: 0.73,
  AUD: 0.66,
  SEK: 0.095,
  NOK: 0.093,
  DKK: 0.145,
  BRL: 0.19,
  RUB: 0.011,
};

// Map symbols and variant codes to standard 3-letter currency code.
const CURRENCY_MAP: Record<string, string> = {
  "$": "USD",
  "€": "EUR",
  "£": "GBP",
  "¥": "JPY",
  "₹": "INR",
  USD: "USD",
  EUR: "EUR",
  GBP: "GBP",
  KRW: "KRW",
  JPY: "JPY",
  INR: "INR",
  RS: "INR",  // Indian rupee shorthand (Rs 10 cr)
  CHF: "CHF",
  CAD: "CAD",
  AUD: "AUD",
  SEK: "SEK",
  NOK: "NOK",
  DKK: "DKK",
  BRL: "BRL",
  RUB: "RUB",
};

// Scale multipliers: crore = 10^7 (Indian numbering system)
const SCALE_MULTIPLIERS: Record<string, number> = {
  k: 1_000,
  m: 1_000_000,
  b: 1_000_000_000,
  t: 1_000_000_000_000,
  cr: 10_000_000, // crore
  thousand: 1_000,
  million: 1_000_000,
  billion: 1_000_000_000,
  trillion: 1_000_000_000_000,
};

export interface NormalizedAmount {
  currency: string; // "USD", "EUR", etc.
  value: number; // raw numeric amount in native currency
  value_usd: number; // converted to USD
}

/**
 * Parse a raw amount string into a normalized structure.
 * Returns null for unparseable or undisclosed amounts.
 */
export function normalizeAmount(raw: string): NormalizedAmount | null {
  if (!raw || !raw.trim()) return null;

  const s = raw.trim();

  // Skip non-amount strings
  if (/^(?:undisclosed|unknown|n\/?a|not.?stated)$/i.test(s)) return null;

  // --- Detect currency ---
  let currency: string | null = null;
  let rest = s;

  // Try symbol prefix: $, €, £, ¥
  const symbolMatch = s.match(/^([\$€£¥₹])\s*/);
  if (symbolMatch) {
    currency = CURRENCY_MAP[symbolMatch[1]] ?? "USD";
    rest = s.slice(symbolMatch[0].length);
  } else {
    // Try alpha currency code prefix (EUR, GBP, KRW, etc.)
    const alphaMatch = s.match(
      /^(EUR|GBP|KRW|INR|JPY|CHF|CAD|AUD|SEK|NOK|DKK|BRL|RUB|USD|RS)(?=\b|\d)\s*/i
    );
    if (alphaMatch) {
      currency = CURRENCY_MAP[alphaMatch[1].toUpperCase()] ?? "USD";
      rest = s.slice(alphaMatch[0].length);
    }
  }

  // Default: no currency detected -> assume USD
  currency = currency ?? "USD";

  // --- Extract numeric part ---
  const numMatch = rest.match(/^([\d,.]+)\s*(.*)$/);
  if (!numMatch) return null;

  const numStr = numMatch[1].replace(/,/g, "");
  if (!numStr) return null;

  const numeric = parseFloat(numStr);
  if (isNaN(numeric)) return null;

  // --- Detect scale ---
  let scaleStr = (numMatch[2] ?? "").trim().toLowerCase();

  // Normalize: strip "illion" suffix
  if (scaleStr.endsWith("illion")) {
    const base = scaleStr.replace(/illion$/, "");
    if (base === "m" || base === "mill") scaleStr = "million";
    else if (base === "b" || base === "bill") scaleStr = "billion";
    else if (base === "tr" || base === "trill") scaleStr = "trillion";
  }

  let scale = 1;
  if (scaleStr) {
    if (SCALE_MULTIPLIERS[scaleStr] !== undefined) {
      scale = SCALE_MULTIPLIERS[scaleStr];
    } else {
      // Check single-letter abbreviation
      const single = scaleStr[0];
      if (SCALE_MULTIPLIERS[single] !== undefined) {
        scale = SCALE_MULTIPLIERS[single];
      }
    }
  }

  const value = numeric * scale;
  const rate = FX_RATES[currency] ?? 1.0;
  const value_usd = Math.round(value * rate);

  return { currency, value, value_usd };
}
