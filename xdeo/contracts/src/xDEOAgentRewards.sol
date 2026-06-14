// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { AccessControl } from "@openzeppelin/contracts/access/AccessControl.sol";
import { IERC20 } from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import { SafeERC20 } from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

/// @title xDEOAgentRewards
/// @notice Affiliate accounting for AI agents that route paid usage to xDEO
///         (the primary distribution channel). An off-chain settler reports each
///         agent-attributed read; agents PULL their accrued share. Pull-payment
///         pattern; the contract holds only transient reward balances.
///
/// @dev    NOT YET COMPILED IN CI (solc host blocked by build egress).
contract xDEOAgentRewards is AccessControl {
    using SafeERC20 for IERC20;

    bytes32 public constant SETTLER_ROLE = keccak256("SETTLER_ROLE");

    IERC20 public immutable usdc;
    /// @dev share of a read's fee paid to the referring agent. 1500 = 15%.
    uint16 public agentBps = 1500;

    struct Agent {
        address payout;
        uint64 readsDriven;
        uint256 earned; // pull balance (USDC atomic)
        bool exists;
    }

    mapping(bytes32 => Agent) public agents; // keccak256(agentId) => Agent

    event AgentRegistered(bytes32 indexed agentId, address payout);
    event RewardAccrued(bytes32 indexed agentId, uint256 amount, uint64 reads);
    event RewardClaimed(bytes32 indexed agentId, address to, uint256 amount);

    error UnknownAgent();
    error NotPayout();

    constructor(IERC20 _usdc, address admin) {
        usdc = _usdc;
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
    }

    /// @notice Register/declare an agent's payout address (idempotent update).
    function register(bytes32 agentId, address payout) external {
        Agent storage a = agents[agentId];
        a.payout = payout;
        a.exists = true;
        emit AgentRegistered(agentId, payout);
    }

    /// @notice Credit an agent for a paid read it drove. `feeBase` is the read's
    ///         total fee; the agent earns `agentBps` of it. USDC for the reward
    ///         must already be funded to this contract by the settlement.
    function accrue(bytes32 agentId, uint256 feeBase)
        external
        onlyRole(SETTLER_ROLE)
    {
        Agent storage a = agents[agentId];
        if (!a.exists) revert UnknownAgent();
        uint256 reward = (feeBase * agentBps) / 10_000;
        a.earned += reward;
        a.readsDriven += 1;
        emit RewardAccrued(agentId, reward, a.readsDriven);
    }

    /// @notice Pull accrued rewards to the agent's registered payout address.
    function claim(bytes32 agentId) external returns (uint256 amount) {
        Agent storage a = agents[agentId];
        if (!a.exists) revert UnknownAgent();
        if (msg.sender != a.payout) revert NotPayout();
        amount = a.earned;
        if (amount == 0) return 0;
        a.earned = 0;
        usdc.safeTransfer(a.payout, amount);
        emit RewardClaimed(agentId, a.payout, amount);
    }

    function setAgentBps(uint16 bps) external onlyRole(DEFAULT_ADMIN_ROLE) {
        require(bps <= 5000, "bps too high");
        agentBps = bps;
    }
}
