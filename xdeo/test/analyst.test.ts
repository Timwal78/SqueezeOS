import { describe, it, expect } from "vitest";
import {
  nextPeriod,
  parseUniverse,
  buildAnalystPrompt,
  parseAnalystResponse,
  DEFAULT_UNIVERSE,
  ANALYST_MODEL,
  type AnalystContext
} from "../src/analyst/autonomous.js";

describe("nextPeriod", () => {
  it("advances quarters Q1->Q2->Q3", () => {
    expect(nextPeriod(2025, "Q1")).toEqual({ fiscal_year: 2025, fiscal_period: "Q2" });
    expect(nextPeriod(2025, "Q2")).toEqual({ fiscal_year: 2025, fiscal_period: "Q3" });
  });
  it("rolls Q3 into the full year", () => {
    expect(nextPeriod(2025, "Q3")).toEqual({ fiscal_year: 2025, fiscal_period: "FY" });
  });
  it("rolls FY into next year's Q1", () => {
    expect(nextPeriod(2024, "FY")).toEqual({ fiscal_year: 2025, fiscal_period: "Q1" });
  });
  it("treats Q4 as the full-year report", () => {
    expect(nextPeriod(2025, "Q4")).toEqual({ fiscal_year: 2025, fiscal_period: "FY" });
  });
  it("is case-insensitive", () => {
    expect(nextPeriod(2025, "q1")).toEqual({ fiscal_year: 2025, fiscal_period: "Q2" });
  });
  it("defaults unknown periods to FY (no crash)", () => {
    expect(nextPeriod(2025, "???")).toEqual({ fiscal_year: 2025, fiscal_period: "FY" });
  });
});

describe("parseUniverse", () => {
  it("returns defaults when unset", () => {
    expect(parseUniverse(undefined)).toBe(DEFAULT_UNIVERSE);
  });
  it("parses and uppercases a comma list", () => {
    expect(parseUniverse("aapl, msft ,nvda")).toEqual(["AAPL", "MSFT", "NVDA"]);
  });
  it("filters out invalid symbols", () => {
    expect(parseUniverse("AAPL, , 123456789012, MSFT")).toEqual(["AAPL", "MSFT"]);
  });
  it("allows dotted/hyphen class tickers", () => {
    expect(parseUniverse("BRK.B, BF-B")).toEqual(["BRK.B", "BF-B"]);
  });
  it("falls back to defaults when nothing valid remains", () => {
    expect(parseUniverse(" , 999999999999 ")).toBe(DEFAULT_UNIVERSE);
  });
});

const CTX: AnalystContext = {
  ticker: "AAPL",
  name: "Apple Inc.",
  history: [
    { fiscal_year: 2024, fiscal_period: "Q2", eps_actual: 1.53, revenue_actual: 90753, filed_at: "2024-05-03" },
    { fiscal_year: 2024, fiscal_period: "Q3", eps_actual: 1.4, revenue_actual: 85777, filed_at: "2024-08-02" }
  ],
  target: { fiscal_year: 2024, fiscal_period: "FY" }
};

describe("buildAnalystPrompt", () => {
  it("includes company, ticker, and target period", () => {
    const p = buildAnalystPrompt(CTX);
    expect(p).toContain("Apple Inc.");
    expect(p).toContain("AAPL");
    expect(p).toContain("FY2024");
  });
  it("renders the historical EPS rows", () => {
    const p = buildAnalystPrompt(CTX);
    expect(p).toContain("Q2 FY2024: EPS=1.53");
    expect(p).toContain("Q3 FY2024: EPS=1.4");
  });
  it("requests the strict JSON shape", () => {
    const p = buildAnalystPrompt(CTX);
    expect(p).toContain("predicted");
    expect(p).toContain("confidence");
    expect(p).toContain("thesis");
  });
  it("tolerates null actuals", () => {
    const p = buildAnalystPrompt({
      ...CTX,
      history: [{ fiscal_year: 2024, fiscal_period: "Q1", eps_actual: null, revenue_actual: null, filed_at: null }]
    });
    expect(p).toContain("EPS=n/a");
  });
});

describe("parseAnalystResponse", () => {
  const VALID = JSON.stringify({
    predicted: 2.34,
    confidence: 0.7,
    thesis: "Seasonal Q4 strength plus services growth lifts FY EPS above trend."
  });

  it("parses clean JSON", () => {
    const r = parseAnalystResponse(VALID);
    expect(r.predicted).toBe(2.34);
    expect(r.confidence).toBe(0.7);
    expect(r.thesis).toContain("services");
  });
  it("strips markdown fences", () => {
    expect(parseAnalystResponse("```json\n" + VALID + "\n```").predicted).toBe(2.34);
  });
  it("ignores preamble and trailing prose", () => {
    expect(parseAnalystResponse("Sure:\n" + VALID + "\nHope that helps").predicted).toBe(2.34);
  });
  it("clamps out-of-range confidence", () => {
    const r = parseAnalystResponse(
      JSON.stringify({ predicted: 1, confidence: 9, thesis: "way too confident here friends" })
    );
    expect(r.confidence).toBe(1);
  });
  it("defaults non-numeric confidence to 0.5", () => {
    const r = parseAnalystResponse(
      JSON.stringify({ predicted: 1, confidence: "high", thesis: "qualitative confidence string" })
    );
    expect(r.confidence).toBe(0.5);
  });
  it("accepts negative EPS (losses are valid forecasts)", () => {
    const r = parseAnalystResponse(
      JSON.stringify({ predicted: -0.42, confidence: 0.6, thesis: "Heavy R&D spend keeps EPS negative." })
    );
    expect(r.predicted).toBe(-0.42);
  });
  it("throws when predicted is missing or non-finite", () => {
    expect(() =>
      parseAnalystResponse(JSON.stringify({ confidence: 0.5, thesis: "no number provided at all here" }))
    ).toThrow("finite");
  });
  it("throws when thesis is too short", () => {
    expect(() =>
      parseAnalystResponse(JSON.stringify({ predicted: 1.1, confidence: 0.5, thesis: "tiny" }))
    ).toThrow("too short");
  });
  it("throws when there is no JSON at all", () => {
    expect(() => parseAnalystResponse("I cannot forecast this")).toThrow("no JSON");
  });
});

describe("ANALYST_MODEL", () => {
  it("targets a Cloudflare Workers AI model", () => {
    expect(ANALYST_MODEL).toMatch(/^@cf\//);
  });
});
