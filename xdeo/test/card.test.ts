import { describe, it, expect } from "vitest";
import { estimateCardSvg } from "../src/og/card.js";

describe("estimateCardSvg", () => {
  const base = {
    ticker: "AAPL",
    handle: "oracle_jane",
    predicted: 1.47,
    metric: "eps",
    confidence: 0.95,
    reputation: 94.3,
    accuracy: 0.943,
    tier: "ORACLE",
    period: "Q3 2026"
  };

  it("renders a 1200x630 SVG with the prediction", () => {
    const svg = estimateCardSvg(base);
    expect(svg).toContain('width="1200"');
    expect(svg).toContain('height="630"');
    expect(svg).toContain("$1.47");
    expect(svg).toContain("AAPL");
    expect(svg).toContain("95% confidence");
  });

  it("formats revenue in billions", () => {
    const svg = estimateCardSvg({ ...base, metric: "revenue", predicted: 95_000_000_000 });
    expect(svg).toContain("$95.00B");
  });

  it("escapes user-controlled handle to prevent SVG injection", () => {
    const svg = estimateCardSvg({ ...base, handle: '<script>alert(1)</script>' });
    expect(svg).not.toContain("<script>");
    expect(svg).toContain("&lt;script&gt;");
  });
});
