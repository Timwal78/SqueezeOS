import { describe, it, expect } from "vitest";
import { formatSSE } from "../src/stream/hub.js";

describe("formatSSE", () => {
  it("emits a well-formed SSE frame with id/event/data", () => {
    const frame = formatSSE({ type: "ESTIMATE_SCORED", data: { score: 92.1 }, ts: 1700000000000 });
    expect(frame).toBe(
      'id: 1700000000000\nevent: ESTIMATE_SCORED\ndata: {"type":"ESTIMATE_SCORED","data":{"score":92.1},"ts":1700000000000}\n\n'
    );
  });

  it("terminates each frame with a blank line (SSE delimiter)", () => {
    const frame = formatSSE({ type: "CONNECTED", data: {}, ts: 1 });
    expect(frame.endsWith("\n\n")).toBe(true);
  });

  it("names the event so clients can addEventListener by type", () => {
    expect(formatSSE({ type: "VERDICT_READY", data: {}, ts: 1 })).toContain("event: VERDICT_READY\n");
  });
});
