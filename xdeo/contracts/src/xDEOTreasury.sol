// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { AccessControl } from "@openzeppelin/contracts/access/AccessControl.sol";
import { IERC20 } from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import { SafeERC20 } from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import { xDEOReputation } from "./xDEOReputation.sol";
import { IxDEOCore } from "./IxDEOCore.sol";

/// @title xDEOTreasury
/// @notice Community treasury (5% of protocol fees). ORACLE-tier analysts
///         propose and vote on allocations (grants, marketing, dev). Execution
///         is gated behind a configurable approval threshold and an admin/
///         timelock executor, per the build spec's multisig+timelock posture.
///
/// @dev    Voting weight is one-analyst-one-vote among ORACLE/LEGEND tiers, read
///         live from xDEOReputation. NOT YET COMPILED IN CI (solc host blocked).
contract xDEOTreasury is AccessControl {
    using SafeERC20 for IERC20;

    bytes32 public constant EXECUTOR_ROLE = keccak256("EXECUTOR_ROLE");

    IERC20 public immutable usdc;
    xDEOReputation public immutable reputation;

    struct Proposal {
        address to;
        uint256 amount;
        string memo;
        uint64 forVotes;
        uint64 createdAt;
        bool executed;
        mapping(address => bool) voted;
    }

    uint256 public proposalCount;
    mapping(uint256 => Proposal) private _proposals;
    /// @dev minimum FOR votes required before an executor may release funds.
    uint64 public quorum = 3;

    event Proposed(uint256 indexed id, address to, uint256 amount, string memo);
    event Voted(uint256 indexed id, address voter, uint64 forVotes);
    event Executed(uint256 indexed id, address to, uint256 amount);

    error NotGovernor();
    error AlreadyVoted();
    error AlreadyExecuted();
    error QuorumNotMet();

    constructor(IERC20 _usdc, xDEOReputation _reputation, address admin) {
        usdc = _usdc;
        reputation = _reputation;
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(EXECUTOR_ROLE, admin);
    }

    /// @dev ORACLE and LEGEND tiers are the governing class.
    modifier onlyGovernor() {
        (, IxDEOCore.Tier tier) = reputation.reputationOf(msg.sender);
        if (tier != IxDEOCore.Tier.ORACLE && tier != IxDEOCore.Tier.LEGEND) {
            revert NotGovernor();
        }
        _;
    }

    function propose(address to, uint256 amount, string calldata memo)
        external
        onlyGovernor
        returns (uint256 id)
    {
        id = ++proposalCount;
        Proposal storage p = _proposals[id];
        p.to = to;
        p.amount = amount;
        p.memo = memo;
        p.createdAt = uint64(block.timestamp);
        emit Proposed(id, to, amount, memo);
    }

    function vote(uint256 id) external onlyGovernor {
        Proposal storage p = _proposals[id];
        if (p.executed) revert AlreadyExecuted();
        if (p.voted[msg.sender]) revert AlreadyVoted();
        p.voted[msg.sender] = true;
        p.forVotes += 1;
        emit Voted(id, msg.sender, p.forVotes);
    }

    /// @notice Release funds once quorum is met. Executor (admin/timelock) only.
    function execute(uint256 id) external onlyRole(EXECUTOR_ROLE) {
        Proposal storage p = _proposals[id];
        if (p.executed) revert AlreadyExecuted();
        if (p.forVotes < quorum) revert QuorumNotMet();
        p.executed = true;
        usdc.safeTransfer(p.to, p.amount);
        emit Executed(id, p.to, p.amount);
    }

    function setQuorum(uint64 q) external onlyRole(DEFAULT_ADMIN_ROLE) {
        quorum = q;
    }

    function proposalInfo(uint256 id)
        external
        view
        returns (address to, uint256 amount, string memory memo, uint64 forVotes, bool executed)
    {
        Proposal storage p = _proposals[id];
        return (p.to, p.amount, p.memo, p.forVotes, p.executed);
    }
}
