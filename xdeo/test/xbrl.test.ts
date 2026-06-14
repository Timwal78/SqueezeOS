import { describe, it, expect } from "vitest";
import {
  selectFact,
  selectByTags,
  normalizePeriod,
  inferPeriod
} from "../src/edgar/xbrl.js";
import type { XbrlFact } from "../src/edgar/client.js";

function fact(p: Partial<XbrlFact>): XbrlFact {
  return {
    end: "2024-06-30",
    val: 1.0,
    fy: 2024,
    fp: "Q2",
    form: "10-Q",
    filed: "2024-08-01",
    accn: "0000320193-24-000081",
    ...p
  };
}

describe("normalizePeriod", () => {
  it("accepts FY and Q1..Q4 case-insensitively", () => {
    expect(normalizePeriod("fy")).toBe("FY");
    expect(normalizePeriod("q3")).toBe("Q3");
  });
  it("rejects junk", () => {
    expect(normalizePeriod("H1")).toBeNull();
    expect(normalizePeriod(null)).toBeNull();
  });
});

describe("selectFact", () => {
  it("matches the requested fiscal period", () => {
    const facts = [
      fact({ fy: 2024, fp: "Q1", val: 1.5 }),
      fact({ fy: 2024, fp: "Q2", val: 1.4 })
    ];
    const got = selectFact(facts, { fiscal_year: 2024, fiscal_period: "Q2" });
    expect(got?.val).toBe(1.4);
  });

  it("prefers the earliest-filed value (avoids restatement look-ahead)", () => {
    const facts = [
      fact({ fy: 2024, fp: "Q2", val: 1.45, filed: "2025-02-01" }), // restated later
      fact({ fy: 2024, fp: "Q2", val: 1.4, filed: "2024-08-01" }) // original
    ];
    const got = selectFact(facts, { fiscal_year: 2024, fiscal_period: "Q2" });
    expect(got?.val).toBe(1.4);
  });

  it("ignores 8-K snapshots, only uses 10-K/10-Q", () => {
    const facts = [fact({ fy: 2024, fp: "Q2", val: 9.9, form: "8-K" })];
    expect(selectFact(facts, { fiscal_year: 2024, fiscal_period: "Q2" })).toBeNull();
  });

  it("returns null when no period matches", () => {
    const facts = [fact({ fy: 2023, fp: "FY" })];
    expect(selectFact(facts, { fiscal_year: 2024, fiscal_period: "Q2" })).toBeNull();
  });
});

describe("selectByTags", () => {
  it("falls through tag priority order", () => {
    const byTag = {
      EarningsPerShareDiluted: [fact({ fy: 2024, fp: "FY", val: 6.1, form: "10-K" })]
    };
    const got = selectByTags(
      byTag,
      ["EarningsPerShareDiluted", "EarningsPerShareBasic"],
      { fiscal_year: 2024, fiscal_period: "FY" }
    );
    expect(got?.tag).toBe("EarningsPerShareDiluted");
    expect(got?.fact.val).toBe(6.1);
  });

  it("skips a tag with no matching period and tries the next", () => {
    const byTag = {
      EarningsPerShareDiluted: [fact({ fy: 2023, fp: "FY", form: "10-K" })],
      EarningsPerShareBasic: [fact({ fy: 2024, fp: "FY", val: 5.5, form: "10-K" })]
    };
    const got = selectByTags(
      byTag,
      ["EarningsPerShareDiluted", "EarningsPerShareBasic"],
      { fiscal_year: 2024, fiscal_period: "FY" }
    );
    expect(got?.tag).toBe("EarningsPerShareBasic");
  });
});

describe("inferPeriod", () => {
  it("maps 10-K to FY of the report date", () => {
    expect(inferPeriod("10-K", "2024-09-28")).toEqual({ fiscal_year: 2024, fiscal_period: "FY" });
  });
  it("maps 10-Q to a calendar quarter", () => {
    expect(inferPeriod("10-Q", "2024-06-30")).toEqual({ fiscal_year: 2024, fiscal_period: "Q2" });
  });
  it("returns null for unsupported forms", () => {
    expect(inferPeriod("8-K", "2024-06-30")).toBeNull();
  });
});
