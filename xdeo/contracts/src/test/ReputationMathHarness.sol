// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { ReputationMath } from "../lib/ReputationMath.sol";
import { UD60x18, ud } from "@prb/math/src/UD60x18.sol";

/// @notice Test-only harness exposing the ReputationMath library externally so
///         Hardhat tests can assert it against off-chain parity vectors.
contract ReputationMathHarness {
    function score(int256 predicted, int256 actual, uint256 confWad, uint256 lead)
        external
        pure
        returns (uint256)
    {
        return UD60x18.unwrap(ReputationMath.score(predicted, actual, ud(confWad), lead));
    }

    function streakMultiplier(uint256 streakDays) external pure returns (uint256) {
        return UD60x18.unwrap(ReputationMath.streakMultiplier(streakDays));
    }

    function updateReputation(
        uint256 repWad,
        uint256 scoredCount,
        uint256 scoreWad,
        uint256 streakMultWad
    ) external pure returns (uint256) {
        return
            UD60x18.unwrap(
                ReputationMath.updateReputation(
                    ud(repWad),
                    scoredCount,
                    ud(scoreWad),
                    ud(streakMultWad)
                )
            );
    }
}
