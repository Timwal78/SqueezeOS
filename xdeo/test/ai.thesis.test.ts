import { describe, it, expect } from "vitest";
import { buildPrompt, parseThesisResponse, AI_THESIS_MODEL } from "../src/ai/thesis.js";
import type { ThesisContext } from "../src/ai/thesis.js";

const BASE_CTX: ThesisContext = {
  estimate: {
    ticker: "AAPL",
    analyst: "0xdeadbeefdeadbeef01234567",
    metric: "eps",
    fiscal_year: 2025,
    fiscal_period: "Q1",
    predicted: 2.18,
    confidence: 0.82,
    thesis: "Strong iPhone upgrade cycle driven by AI features.",
    status: "SCORED",
    score: 87.4,
    error_pct: 0.031
  },
  analyst: {
    handle: "quantsage",
    reputation: 0.73,
    accuracy: 0.81,
    tier: "SAGE",
    scored_count: 42
  },
  filing: {
    eps_actual: 2.11,
    revenue_actual: null,
    period_end: "2025-03-29"
  }
};

describe("buildPrompt", () => {
  it("includes ticker and metric label", () => {
    const p = buildPrompt(BASE_CTX);
    expect(p).toContain("AAPL");
    expect(p).toContain("EPS");
  });

  it("includes analyst handle when available", () => {
    const p = buildPrompt(BASE_CTX);
    expect(p).toContain("quantsage");
    expect(p).toContain("SAGE");
  });

  it("falls back to truncated address when no handle", () => {
    const ctx = { ...BASE_CTX, analyst: { ...BASE_CTX.analyst, handle: null } };
    const p = buildPrompt(ctx);
    expect(p).toContain("0xdeadbeef…");
  });

  it("includes confidence as percentage", () => {
    const p = buildPrompt(BASE_CTX);
    expect(p).toContain("82%");
  });

  it("includes actual filing data when present", () => {
    const p = buildPrompt(BASE_CTX);
    expect(p).toContain("2.11");
    expect(p).toContain("2025-03-29");
  });

  it("reports not-yet-scored when no filing", () => {
    const ctx = { ...BASE_CTX, filing: null };
    const p = buildPrompt(ctx);
    expect(p).toContain("not yet scored");
  });

  it("uses Revenue label for revenue metric", () => {
    const ctx = { ...BASE_CTX, estimate: { ...BASE_CTX.estimate, metric: "revenue" as const } };
    expect(buildPrompt(ctx)).toContain("Revenue");
    expect(buildPrompt(ctx)).not.toContain("EPS =");
  });

  it("includes the analyst's thesis text", () => {
    const p = buildPrompt(BASE_CTX);
    expect(p).toContain("Strong iPhone upgrade cycle");
  });

  it("includes historical accuracy and scored count", () => {
    const p = buildPrompt(BASE_CTX);
    expect(p).toContain("81.0%");
    expect(p).toContain("42");
  });

  it("specifies JSON output format with required keys", () => {
    const p = buildPrompt(BASE_CTX);
    expect(p).toContain("summary");
    expect(p).toContain("bull_case");
    expect(p).toContain("bear_case");
    expect(p).toContain("key_assumptions");
    expect(p).toContain("risks");
    expect(p).toContain("confidence_rationale");
  });
});

describe("parseThesisResponse", () => {
  const VALID_JSON = JSON.stringify({
    summary: "Strong beat driven by AI-accelerated iPhone cycle.",
    bull_case: "Services revenue expanding with 82% gross margin.",
    bear_case: "China macro headwinds could pressure unit volumes.",
    key_assumptions: ["iPhone cycle holds", "Services growth 15%+", "Stable margins"],
    risks: ["Tariff escalation", "AI feature adoption slower than expected", "USD strength"],
    confidence_rationale: "81% historical accuracy strongly supports the 82% confidence claim."
  });

  it("parses clean JSON correctly", () => {
    const r = parseThesisResponse(VALID_JSON);
    expect(r.summary).toContain("AI-accelerated");
    expect(r.bull_case).toContain("Services");
    expect(r.bear_case).toContain("China");
    expect(r.key_assumptions).toHaveLength(3);
    expect(r.risks).toHaveLength(3);
    expect(r.confidence_rationale).toContain("81%");
  });

  it("strips markdown code fences before parsing", () => {
    const fenced = "```json\n" + VALID_JSON + "\n```";
    const r = parseThesisResponse(fenced);
    expect(r.summary).toBeTruthy();
  });

  it("strips triple-backtick without language tag", () => {
    const r = parseThesisResponse("```\n" + VALID_JSON + "\n```");
    expect(r.summary).toBeTruthy();
  });

  it("handles preamble text before JSON", () => {
    const r = parseThesisResponse("Here is the analysis:\n" + VALID_JSON);
    expect(r.summary).toBeTruthy();
  });

  it("handles trailing text after JSON closing brace", () => {
    const r = parseThesisResponse(VALID_JSON + "\n\nNote: not investment advice.");
    expect(r.summary).toBeTruthy();
  });

  it("coerces non-array key_assumptions to empty array", () => {
    const bad = JSON.parse(VALID_JSON);
    bad.key_assumptions = "oops — a string";
    const r = parseThesisResponse(JSON.stringify(bad));
    expect(Array.isArray(r.key_assumptions)).toBe(true);
    expect(r.key_assumptions).toHaveLength(0);
  });

  it("coerces missing fields to empty strings", () => {
    const minimal = JSON.stringify({ summary: "ok" });
    const r = parseThesisResponse(minimal);
    expect(r.bull_case).toBe("");
    expect(r.bear_case).toBe("");
    expect(r.confidence_rationale).toBe("");
  });

  it("throws when no JSON object is present", () => {
    expect(() => parseThesisResponse("sorry, I cannot generate this")).toThrow(
      "no JSON object found"
    );
  });

  it("throws on malformed JSON", () => {
    expect(() => parseThesisResponse("{ broken json }")).toThrow();
  });
});

describe("AI_THESIS_MODEL constant", () => {
  it("names a Cloudflare Workers AI model", () => {
    expect(AI_THESIS_MODEL).toMatch(/^@cf\//);
  });
});
