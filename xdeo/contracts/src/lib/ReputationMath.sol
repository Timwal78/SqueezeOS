// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { UD60x18, ud, exp2, UNIT } from "@prb/math/src/UD60x18.sol";

/// @title ReputationMath
/// @notice On-chain port of the off-chain reputation engine
///         (`xdeo/src/reputation/engine.ts`). All math is UD60x18 (1e18 fixed
///         point). The formulas here are the unsigned algebraic equivalents of
///         the signed expressions in TypeScript and are specified canonically in
///         `xdeo/contracts/README.md`.
///
/// @dev    NOT YET COMPILED IN CI — the Solidity compiler host is blocked by the
///         build environment's egress allowlist. Build/test in an environment
///         with `binaries.soliditylang.org` access (see contracts/README.md).
library ReputationMath {
    /// @dev EMA floor so even veteran analysts stay responsive to recent results.
    UD60x18 internal constant ALPHA_FLOOR = UD60x18.wrap(0.08e18);
    /// @dev 30 days, the lead time at which an estimate earns full timeliness.
    uint256 internal constant FULL_LEAD_SECONDS = 30 days;
    /// @dev Cap on 10*errorPct fed to exp2; beyond this, accuracy rounds to 0.
    UD60x18 internal constant TEN_ERR_CAP = UD60x18.wrap(180e18);

    UD60x18 internal constant HALF = UD60x18.wrap(0.5e18);
    UD60x18 internal constant TWO = UD60x18.wrap(2e18);
    UD60x18 internal constant HUNDRED = UD60x18.wrap(100e18);
    UD60x18 internal constant TIME_FLOOR = UD60x18.wrap(0.25e18);
    UD60x18 internal constant TIME_SPAN = UD60x18.wrap(0.75e18);

    /// @notice Score one estimate against the SEC-filed actual.
    /// @param predicted  estimate value, scaled 1e8 (signed; EPS may be negative)
    /// @param actual     SEC-filed actual, scaled 1e8 (signed)
    /// @param confidence self-reported confidence, UD60x18 in [0, 1e18]
    /// @param leadSeconds seconds between submission and the scoring filing
    /// @return scoreWad  score in [0, 100], UD60x18 (i.e. up to 100e18)
    function score(
        int256 predicted,
        int256 actual,
        UD60x18 confidence,
        uint256 leadSeconds
    ) internal pure returns (UD60x18 scoreWad) {
        UD60x18 accuracy = accuracyTerm(predicted, actual);

        // w = 0.5 + 0.5*confidence  (clamped to [0,1] confidence by caller/here)
        UD60x18 conf = confidence.gt(UNIT) ? UNIT : confidence;
        UD60x18 w = HALF.add(conf.div(TWO));

        // base = accuracy*w + (1 - w)/2   (unsigned equivalent of the signed form)
        UD60x18 base = accuracy.mul(w).add(UNIT.sub(w).div(TWO));

        UD60x18 timeliness = timelinessTerm(leadSeconds);

        // effective = base*timeliness + 0.5*(1 - timeliness)
        UD60x18 effective = base.mul(timeliness).add(HALF.mul(UNIT.sub(timeliness)));

        scoreWad = effective.mul(HUNDRED);
    }

    /// @notice accuracy = 2^(-10*errorPct), errorPct = |pred-actual|/max(|actual|,eps)
    function accuracyTerm(int256 predicted, int256 actual)
        internal
        pure
        returns (UD60x18)
    {
        uint256 diff = predicted >= actual
            ? uint256(predicted - actual)
            : uint256(actual - predicted);
        uint256 absActual = actual >= 0 ? uint256(actual) : uint256(-actual);
        if (absActual == 0) absActual = 1; // eps guard (1e-8 at 1e8 scale)

        // errorPct (wad) = diff/absActual; inputs share the 1e8 scale so it cancels.
        UD60x18 errorPct = ud((diff * 1e18) / absActual);
        UD60x18 tenErr = errorPct.mul(ud(10e18));
        if (tenErr.gte(TEN_ERR_CAP)) return ud(0);

        // 2^(-tenErr) = 1 / 2^(tenErr)
        return UNIT.div(exp2(tenErr));
    }

    /// @notice timeliness = 0.25 + 0.75*min(lead/30d, 1)
    function timelinessTerm(uint256 leadSeconds) internal pure returns (UD60x18) {
        UD60x18 frac = leadSeconds >= FULL_LEAD_SECONDS
            ? UNIT
            : ud((leadSeconds * 1e18) / FULL_LEAD_SECONDS);
        return TIME_FLOOR.add(TIME_SPAN.mul(frac));
    }

    /// @notice Fold a fresh score into a running reputation via a bounded EMA.
    /// @param reputation current reputation, UD60x18 in [0,100]
    /// @param scoredCount number of prior scored estimates
    /// @param scoreWad this estimate's score, UD60x18 in [0,100]
    /// @param streakMult streak multiplier, UD60x18 in [1,5]; boosts gains only
    /// @return newReputation updated reputation, UD60x18 in [0,100]
    function updateReputation(
        UD60x18 reputation,
        uint256 scoredCount,
        UD60x18 scoreWad,
        UD60x18 streakMult
    ) internal pure returns (UD60x18 newReputation) {
        // Streak amplifies gains only (score >= 50) and cannot push past 100.
        UD60x18 target = scoreWad;
        if (scoreWad.gte(ud(50e18))) {
            UD60x18 boosted = scoreWad.mul(streakMult);
            target = boosted.gt(HUNDRED) ? HUNDRED : boosted;
        }

        newReputation = ema(reputation, target, scoredCount);
        if (newReputation.gt(HUNDRED)) newReputation = HUNDRED;
    }

    /// @notice Bounded EMA step toward `target`. alpha = max(0.08, 1/(count+1)).
    /// @dev Branch keeps all arithmetic unsigned (UD60x18 sub reverts on < 0).
    function ema(UD60x18 prev, UD60x18 target, uint256 count)
        internal
        pure
        returns (UD60x18)
    {
        UD60x18 invN = UNIT.div(ud((count + 1) * 1e18));
        UD60x18 alpha = invN.gt(ALPHA_FLOOR) ? invN : ALPHA_FLOOR;
        if (target.gte(prev)) return prev.add(alpha.mul(target.sub(prev)));
        return prev.sub(alpha.mul(prev.sub(target)));
    }

    /// @notice Streak multiplier: 7d→1.5x, 30d→2.5x, 100d→5x, capped at 5x.
    function streakMultiplier(uint256 streakDays) internal pure returns (UD60x18) {
        if (streakDays >= 100) return ud(5e18);
        if (streakDays >= 30) {
            // 2.5 + (d-30)/70 * 2.5
            UD60x18 t = ud(((streakDays - 30) * 1e18) / 70);
            return ud(2.5e18).add(t.mul(ud(2.5e18)));
        }
        if (streakDays >= 7) {
            // 1.5 + (d-7)/23 * 1.0
            UD60x18 t = ud(((streakDays - 7) * 1e18) / 23);
            return ud(1.5e18).add(t.mul(ud(1e18)));
        }
        // 1.0 + d/7 * 0.5
        UD60x18 t2 = ud((streakDays * 1e18) / 7);
        return UNIT.add(t2.mul(ud(0.5e18)));
    }
}
