// XBRL fact selection. Translates the raw companyconcept fact stream into the
// single "actual" number that matters for scoring a given fiscal period.
//
// This is pure logic (no I/O) so it is unit-tested directly in test/xbrl.test.ts.

import type { XbrlFact } from "./client.js";

// Concepts an issuer might use for diluted EPS. We try in priority order.
export const EPS_TAGS = [
  "EarningsPerShareDiluted",
  "EarningsPerShareBasicAndDiluted",
  "EarningsPerShareBasic"
];

export const REVENUE_TAGS = [
  "RevenueFromContractWithCustomerExcludingAssessedTax",
  "Revenues",
  "SalesRevenueNet",
  "RevenueFromContractWithCustomerIncludingAssessedTax"
];

export interface PeriodKey {
  fiscal_year: number;
  fiscal_period: string; // "Q1".."Q4" | "FY"
}

/**
 * Find the fact that reports `metric` for the exact fiscal period. EDGAR often
 * carries the same period restated across later filings; we pick the EARLIEST
 * filed value for that period so analysts are scored against the number that
 * was first published (avoids look-ahead from restatements).
 */
export function selectFact(
  facts: XbrlFact[],
  period: PeriodKey
): XbrlFact | null {
  const matches = facts.filter(
    (f) =>
      f.fy === period.fiscal_year &&
      normalizePeriod(f.fp) === period.fiscal_period &&
      // 10-K/10-Q are audited/reviewed; ignore 8-K snapshots which can be
      // preliminary and lack fy/fp consistency.
      (f.form === "10-K" || f.form === "10-Q")
  );
  if (matches.length === 0) return null;
  matches.sort((a, b) => a.filed.localeCompare(b.filed));
  return matches[0]!;
}

/** Try a list of candidate tags and return the first that yields a fact. */
export function selectByTags(
  factsByTag: Record<string, XbrlFact[]>,
  tags: string[],
  period: PeriodKey
): { tag: string; fact: XbrlFact } | null {
  for (const tag of tags) {
    const facts = factsByTag[tag];
    if (!facts) continue;
    const fact = selectFact(facts, period);
    if (fact) return { tag, fact };
  }
  return null;
}

export function normalizePeriod(fp: string | null): string | null {
  if (!fp) return null;
  const up = fp.toUpperCase();
  if (up === "FY") return "FY";
  if (/^Q[1-4]$/.test(up)) return up;
  return null;
}

/** Infer the {fy, fp} a filing reports from its form + report date. */
export function inferPeriod(
  form: string,
  reportDate: string | undefined
): PeriodKey | null {
  if (!reportDate) return null;
  const d = new Date(reportDate + "T00:00:00Z");
  if (Number.isNaN(d.getTime())) return null;
  const year = d.getUTCFullYear();
  if (form === "10-K") return { fiscal_year: year, fiscal_period: "FY" };
  if (form === "10-Q") {
    // Calendar-quarter approximation; the authoritative fp comes from XBRL fp
    // when we actually pull the concept. This is only a hint for the row.
    const month = d.getUTCMonth(); // 0-based
    const q = Math.floor(month / 3) + 1;
    return { fiscal_year: year, fiscal_period: `Q${q}` };
  }
  return null;
}
