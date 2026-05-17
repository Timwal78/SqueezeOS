import { calculateMilestoneAmounts } from "../jobs";
import { Milestone } from "../types";

describe("calculateMilestoneAmounts", () => {
  const makeMilestone = (percent: number): Milestone => ({
    description: `Milestone ${percent}%`,
    amountPercent: percent,
    deadline: Date.now() + 86400000,
    acceptanceCriteria: "Tests pass",
  });

  it("splits single milestone at 100%", () => {
    const amounts = calculateMilestoneAmounts("1000000", [makeMilestone(100)]);
    expect(amounts).toEqual(["1000000"]);
  });

  it("splits two equal milestones", () => {
    const amounts = calculateMilestoneAmounts("1000000", [
      makeMilestone(50),
      makeMilestone(50),
    ]);
    expect(amounts).toEqual(["500000", "500000"]);
  });

  it("handles 25/75 split", () => {
    const amounts = calculateMilestoneAmounts("1000000", [
      makeMilestone(25),
      makeMilestone(75),
    ]);
    expect(parseInt(amounts[0], 10) + parseInt(amounts[1], 10)).toBe(1000000);
  });

  it("throws if percentages do not sum to 100", () => {
    expect(() =>
      calculateMilestoneAmounts("1000000", [makeMilestone(60), makeMilestone(60)])
    ).toThrow(/Milestone percentages must sum to 100/);
  });
});
