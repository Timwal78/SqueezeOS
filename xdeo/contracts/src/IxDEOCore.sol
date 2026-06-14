// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title IxDEOCore — on-chain interface for the xDEO earnings-estimate protocol.
/// @notice Information marketplace only. Estimates are OPINIONS, not securities
///         or investment advice. The protocol holds NO user funds: x402 payments
///         settle peer-to-peer off-chain; this contract tracks reputation and
///         fee accounting only. Wrong estimates slash REPUTATION, never funds.
interface IxDEOCore {
    /// @dev Tier mirrors src/reputation/engine.ts computeTier().
    enum Tier { OBSERVER, ANALYST, SAGE, ORACLE, LEGEND }

    event AnalystRegistered(address indexed analyst, address indexed referrer);
    event EstimateSubmitted(
        bytes32 indexed estimateId,
        address indexed analyst,
        bytes32 indexed ticker,
        uint16 fiscalYear,
        uint8 fiscalPeriod
    );
    event EstimateScored(
        bytes32 indexed estimateId,
        uint256 score,        // 0..100e18 fixed point
        uint256 errorBps,     // |pred-actual|/actual in basis points
        int256 actual         // SEC-filed actual (scaled)
    );
    event ReputationUpdated(address indexed analyst, uint256 reputation, Tier tier);

    /// @notice Register as an analyst. Permissionless, no KYC. Optional referrer
    ///         earns a perpetual share of this analyst's protocol fees.
    function registerAnalyst(address referrer) external;

    /// @notice Commit an estimate. No funds are bonded; reputation is the stake.
    /// @param ticker       packed ticker symbol
    /// @param fiscalYear   e.g. 2026
    /// @param fiscalPeriod 0=FY, 1..4 = Q1..Q4
    /// @param predicted    estimate value, scaled 1e8
    /// @param confidence   0..1e18
    /// @return estimateId  deterministic id
    function submitEstimate(
        bytes32 ticker,
        uint16 fiscalYear,
        uint8 fiscalPeriod,
        int256 predicted,
        uint256 confidence
    ) external returns (bytes32 estimateId);

    /// @notice Oracle-only. Called once the SEC filing's actual lands. Scores the
    ///         estimate and updates the analyst's compounding reputation.
    /// @dev    onlyOracle. Scoring math matches the off-chain reputation engine.
    function scoreEstimate(bytes32 estimateId, int256 actual, uint256 leadSeconds) external;

    /// @notice Pull accrued protocol-fee share. Never a custodial balance of
    ///         third-party money — only fees already routed to this analyst.
    function claimEarnings() external returns (uint256 amount);

    /// @notice Current composite reputation (0..100e18) and tier for an analyst.
    function reputationOf(address analyst) external view returns (uint256 reputation, Tier tier);
}
