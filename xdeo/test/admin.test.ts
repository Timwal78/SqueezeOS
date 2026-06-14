import { describe, it, expect } from "vitest";
import { tokensMatch } from "../src/routes/admin.js";

describe("tokensMatch", () => {
  it("returns true for identical tokens", () => {
    expect(tokensMatch("s3cret-token", "s3cret-token")).toBe(true);
  });
  it("returns false for different tokens", () => {
    expect(tokensMatch("s3cret-token", "wrong-token!")).toBe(false);
  });
  it("returns false for different lengths", () => {
    expect(tokensMatch("short", "shorter-value")).toBe(false);
  });
  it("returns false when expected is undefined (unconfigured)", () => {
    expect(tokensMatch(undefined, "anything")).toBe(false);
  });
  it("returns false when provided token is undefined/missing", () => {
    expect(tokensMatch("expected", undefined)).toBe(false);
  });
  it("returns false for empty-string inputs", () => {
    expect(tokensMatch("", "")).toBe(false);
  });
});
