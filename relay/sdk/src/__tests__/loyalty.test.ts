import {
  computeParticipantLoyalty,
  computeEvaluatorLoyalty,
  getLoyaltyBenefits,
  applyLoyaltyDiscount,
  applyEvaluatorBonus,
  buildGovernanceVoteTx,
  GovernanceProposal,
} from "../loyalty";

const addr = "rTest123";

// ── computeParticipantLoyalty ────────────────────────────────────────────────

describe("computeParticipantLoyalty", () => {
  it("unranked for 0 jobs", () => {
    const l = computeParticipantLoyalty(addr, 0, 0, []);
    expect(l.tier).toBe("unranked");
    expect(l.feeDiscountBps).toBe(0);
    expect(l.canVote).toBe(false);
  });

  it("scout at 1 job", () => {
    const l = computeParticipantLoyalty(addr, 1, 10, [Date.now() / 1000]);
    expect(l.tier).toBe("scout");
  });

  it("builder at 10 jobs with 10% discount", () => {
    const l = computeParticipantLoyalty(addr, 10, 100, []);
    expect(l.tier).toBe("builder");
    expect(l.feeDiscountBps).toBe(1000);
    expect(l.privilegedEvaluatorPool).toBe(false);
  });

  it("veteran at 50 jobs with custom pool", () => {
    const l = computeParticipantLoyalty(addr, 50, 500, []);
    expect(l.tier).toBe("veteran");
    expect(l.privilegedEvaluatorPool).toBe(true);
    expect(l.canVote).toBe(false);
  });

  it("legend at 200 jobs with governance vote", () => {
    const l = computeParticipantLoyalty(addr, 200, 2000, []);
    expect(l.tier).toBe("legend");
    expect(l.feeDiscountBps).toBe(3000);
    expect(l.canVote).toBe(true);
    expect(l.nextTierRequirement).toBeNull();
  });

  it("shows next tier requirement", () => {
    const l = computeParticipantLoyalty(addr, 5, 50, []);
    expect(l.nextTierRequirement).toMatch(/5 more jobs for builder/);
  });

  it("computes activity streak", () => {
    const now = Math.floor(Date.now() / 1000);
    const daySeconds = 24 * 60 * 60;
    // 3 consecutive days
    const dates = [now, now - daySeconds, now - 2 * daySeconds];
    const l = computeParticipantLoyalty(addr, 3, 30, dates);
    expect(l.longestStreakDays).toBeGreaterThanOrEqual(3);
  });
});

// ── computeEvaluatorLoyalty ──────────────────────────────────────────────────

describe("computeEvaluatorLoyalty", () => {
  it("unranked below thresholds", () => {
    const l = computeEvaluatorLoyalty(addr, 5, 0.7, 0, 0);
    expect(l.tier).toBe("unranked");
    expect(l.bonusMultiplier).toBe(1);
  });

  it("apprentice at 10 votes 80% accuracy", () => {
    const l = computeEvaluatorLoyalty(addr, 10, 0.80, 0, 0);
    expect(l.tier).toBe("apprentice");
  });

  it("journeyman requires 50 votes, 85% accuracy, 30 days tenure", () => {
    const l = computeEvaluatorLoyalty(addr, 50, 0.85, 30, 100);
    expect(l.tier).toBe("journeyman");
    expect(l.bonusMultiplier).toBeCloseTo(1.05, 3);
  });

  it("grandmaster requires 500 votes, 95% accuracy, 1yr tenure", () => {
    const l = computeEvaluatorLoyalty(addr, 500, 0.96, 400, 5000);
    expect(l.tier).toBe("grandmaster");
    expect(l.bonusMultiplier).toBeCloseTo(1.20, 3);
    expect(l.nextTierRequirement).toBeNull();
  });

  it("fails to reach journeyman without tenure", () => {
    const l = computeEvaluatorLoyalty(addr, 50, 0.85, 10, 0); // only 10 days
    expect(l.tier).toBe("apprentice");
  });
});

// ── getLoyaltyBenefits ───────────────────────────────────────────────────────

describe("getLoyaltyBenefits", () => {
  it("legend has governance vote and VIP pool", () => {
    const b = getLoyaltyBenefits("legend");
    expect(b.canVoteOnGovernance).toBe(true);
    expect(b.evaluatorPoolTier).toBe("vip");
    expect(b.canIssueAttestations).toBe(true);
  });

  it("grandmaster evaluator has max bonus", () => {
    const b = getLoyaltyBenefits("grandmaster");
    expect(b.bonusMultiplierBps).toBe(2000);
    expect(b.canVoteOnGovernance).toBe(true);
  });

  it("unranked has zero benefits", () => {
    const b = getLoyaltyBenefits("unranked");
    expect(b.feeDiscountBps).toBe(0);
    expect(b.bonusMultiplierBps).toBe(0);
  });
});

// ── applyLoyaltyDiscount ─────────────────────────────────────────────────────

describe("applyLoyaltyDiscount", () => {
  it("scout gets no discount", () => {
    const { discountedFee, savings } = applyLoyaltyDiscount(1000, 5, "scout");
    expect(discountedFee).toBe(5);
    expect(savings).toBe(0);
  });

  it("builder gets 10% off", () => {
    const { discountedFee, savings } = applyLoyaltyDiscount(1000, 10, "builder");
    expect(discountedFee).toBeCloseTo(9, 1);
    expect(savings).toBeCloseTo(1, 1);
  });

  it("legend gets 30% off", () => {
    const { discountedFee } = applyLoyaltyDiscount(1000, 10, "legend");
    expect(discountedFee).toBeCloseTo(7, 1);
  });
});

// ── applyEvaluatorBonus ──────────────────────────────────────────────────────

describe("applyEvaluatorBonus", () => {
  it("no bonus for unranked", () => {
    const { boostedReward, bonus } = applyEvaluatorBonus(2, "unranked");
    expect(boostedReward).toBe(2);
    expect(bonus).toBe(0);
  });

  it("grandmaster gets 20% bonus", () => {
    const { boostedReward } = applyEvaluatorBonus(10, "grandmaster");
    expect(boostedReward).toBeCloseTo(12, 1);
  });
});

// ── buildGovernanceVoteTx ────────────────────────────────────────────────────

describe("buildGovernanceVoteTx", () => {
  const proposal: GovernanceProposal = {
    proposalId: "RIP-001",
    title: "Default evaluator pool size",
    description: "Should the default pool be 5 or 7?",
    options: ["5", "7"],
    expiresAt: Math.floor(Date.now() / 1000) + 86400,
  };

  it("builds a valid AccountSet tx with governance memo", () => {
    const tx = buildGovernanceVoteTx(addr, proposal, "7");
    expect(tx.TransactionType).toBe("AccountSet");
    expect(tx.Account).toBe(addr);
    expect(tx.Domain).toBeTruthy();
    const decoded = JSON.parse(Buffer.from(tx.Domain as string, "hex").toString("utf8"));
    expect(decoded.choice).toBe("7");
    expect(decoded.proposal_id).toBe("RIP-001");
    expect(decoded.relay_governance).toBe(true);
  });

  it("throws INVALID_CHOICE for unrecognized option", () => {
    expect(() => buildGovernanceVoteTx(addr, proposal, "3")).toThrow(/not in proposal options/);
  });

  it("throws PROPOSAL_EXPIRED for past expiry", () => {
    const expired: GovernanceProposal = { ...proposal, expiresAt: 1 };
    expect(() => buildGovernanceVoteTx(addr, expired, "7")).toThrow(/expired/);
  });
});
