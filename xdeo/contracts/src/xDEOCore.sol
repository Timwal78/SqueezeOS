// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { AccessControl } from "@openzeppelin/contracts/access/AccessControl.sol";
import { IERC20 } from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import { SafeERC20 } from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import { UD60x18, ud } from "@prb/math/src/UD60x18.sol";
import { IxDEOCore } from "./IxDEOCore.sol";
import { xDEOReputation } from "./xDEOReputation.sol";
import { ReputationMath } from "./lib/ReputationMath.sol";

/// @title xDEOCore
/// @notice Analyst registry, estimate commitments, oracle-driven scoring, and
///         pull-based fee accounting for the xDEO earnings-estimate protocol.
///
///         Information marketplace only — estimates are OPINIONS, not securities
///         or investment advice. ZERO CUSTODY of user positions: x402 read
///         payments settle peer-to-peer off-chain; an authorized settler reports
///         each paid read here so analysts/agents/protocol can PULL their fee
///         split. The contract holds only transient fee balances awaiting
///         withdrawal, never user funds in flight.
///
/// @dev    NOT YET COMPILED IN CI — solc host blocked by build egress. The
///         scoring math is the on-chain port specified in contracts/README.md.
contract xDEOCore is IxDEOCore, AccessControl {
    using SafeERC20 for IERC20;

    bytes32 public constant ORACLE_ROLE = keccak256("ORACLE_ROLE");
    bytes32 public constant SETTLER_ROLE = keccak256("SETTLER_ROLE");

    xDEOReputation public immutable reputation;
    IERC20 public immutable usdc;

    /// @dev basis points. 500 = 5% protocol fee; analysts keep 95%.
    uint16 public protocolFeeBps = 500;
    /// @dev share of the PROTOCOL FEE paid to a referring analyst, forever.
    uint16 public referralBps = 1000; // 10%

    struct EstimateData {
        address analyst;
        bytes32 ticker;
        uint16 fiscalYear;
        uint8 fiscalPeriod; // 0=FY, 1..4=Q1..Q4
        int256 predicted; // scaled 1e8
        UD60x18 confidence; // [0,1]
        uint64 createdAt;
        bool scored;
        bool exists;
    }

    mapping(bytes32 => EstimateData) public estimates;
    mapping(address => address) public referrerOf;
    mapping(address => uint256) public earnings; // pull balances (USDC atomic)
    uint256 public protocolEarnings;

    event ReadSettled(
        bytes32 indexed estimateId,
        address indexed analyst,
        uint256 amount,
        uint256 analystShare,
        uint256 protocolFee
    );
    event EarningsClaimed(address indexed who, uint256 amount);

    error AlreadyScored();
    error UnknownEstimate();
    error BadPeriod();

    constructor(IERC20 _usdc, xDEOReputation _reputation, address admin) {
        usdc = _usdc;
        reputation = _reputation;
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
    }

    // --- analyst + estimate lifecycle ---------------------------------------

    /// @inheritdoc IxDEOCore
    function registerAnalyst(address referrer) external {
        reputation.register(msg.sender);
        if (
            referrerOf[msg.sender] == address(0) &&
            referrer != address(0) &&
            referrer != msg.sender
        ) {
            referrerOf[msg.sender] = referrer;
        }
        emit AnalystRegistered(msg.sender, referrerOf[msg.sender]);
    }

    /// @inheritdoc IxDEOCore
    function submitEstimate(
        bytes32 ticker,
        uint16 fiscalYear,
        uint8 fiscalPeriod,
        int256 predicted,
        uint256 confidence
    ) external returns (bytes32 estimateId) {
        if (fiscalPeriod > 4) revert BadPeriod();

        estimateId = keccak256(
            abi.encodePacked(
                msg.sender,
                ticker,
                fiscalYear,
                fiscalPeriod,
                predicted,
                block.timestamp
            )
        );
        estimates[estimateId] = EstimateData({
            analyst: msg.sender,
            ticker: ticker,
            fiscalYear: fiscalYear,
            fiscalPeriod: fiscalPeriod,
            predicted: predicted,
            confidence: ud(confidence),
            createdAt: uint64(block.timestamp),
            scored: false,
            exists: true
        });

        reputation.bumpEstimate(msg.sender);
        emit EstimateSubmitted(estimateId, msg.sender, ticker, fiscalYear, fiscalPeriod);
    }

    /// @inheritdoc IxDEOCore
    /// @dev Called by the scoring oracle once the SEC filing's actual lands.
    function scoreEstimate(bytes32 estimateId, int256 actual, uint256 leadSeconds)
        external
        onlyRole(ORACLE_ROLE)
    {
        EstimateData storage e = estimates[estimateId];
        if (!e.exists) revert UnknownEstimate();
        if (e.scored) revert AlreadyScored();

        UD60x18 scoreWad = ReputationMath.score(
            e.predicted,
            actual,
            e.confidence,
            leadSeconds
        );
        e.scored = true;
        reputation.recordScore(e.analyst, scoreWad);

        uint256 errorBps = _errorBps(e.predicted, actual);
        emit EstimateScored(estimateId, UD60x18.unwrap(scoreWad), errorBps, actual);

        (uint256 rep, Tier tier) = reputation.reputationOf(e.analyst);
        emit ReputationUpdated(e.analyst, rep, tier);
    }

    // --- fee accounting (pull payments) -------------------------------------

    /// @notice Report a paid x402 read. The USDC for `amount` must already have
    ///         been transferred to this contract by the off-chain settlement.
    ///         Splits: protocol fee (bps), referral cut of that fee, remainder
    ///         to the analyst. All credited to pull balances.
    function settleRead(bytes32 estimateId, uint256 amount)
        external
        onlyRole(SETTLER_ROLE)
    {
        EstimateData storage e = estimates[estimateId];
        if (!e.exists) revert UnknownEstimate();

        uint256 fee = (amount * protocolFeeBps) / 10_000;
        uint256 analystShare = amount - fee;

        address ref = referrerOf[e.analyst];
        uint256 refCut = ref == address(0) ? 0 : (fee * referralBps) / 10_000;

        earnings[e.analyst] += analystShare;
        if (refCut > 0) earnings[ref] += refCut;
        protocolEarnings += fee - refCut;

        emit ReadSettled(estimateId, e.analyst, amount, analystShare, fee);
    }

    /// @inheritdoc IxDEOCore
    function claimEarnings() external returns (uint256 amount) {
        amount = earnings[msg.sender];
        if (amount == 0) return 0;
        earnings[msg.sender] = 0; // effects before interaction (reentrancy-safe)
        usdc.safeTransfer(msg.sender, amount);
        emit EarningsClaimed(msg.sender, amount);
    }

    /// @notice Admin sweep of accrued protocol fees.
    function sweepProtocol(address to) external onlyRole(DEFAULT_ADMIN_ROLE) returns (uint256 amount) {
        amount = protocolEarnings;
        protocolEarnings = 0;
        usdc.safeTransfer(to, amount);
    }

    // --- views ---------------------------------------------------------------

    /// @inheritdoc IxDEOCore
    function reputationOf(address analyst)
        external
        view
        returns (uint256 reputationWad, Tier tier)
    {
        return reputation.reputationOf(analyst);
    }

    // --- internals -----------------------------------------------------------

    function _errorBps(int256 predicted, int256 actual) private pure returns (uint256) {
        uint256 diff = predicted >= actual
            ? uint256(predicted - actual)
            : uint256(actual - predicted);
        uint256 absActual = actual >= 0 ? uint256(actual) : uint256(-actual);
        if (absActual == 0) absActual = 1;
        return (diff * 10_000) / absActual;
    }
}
