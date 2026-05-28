# Stigmergy Protocol — Architecture Specification

> x402 isn't a checkout button for robots. It's ATP for the machine biome.

## Overview

The Stigmergy Protocol replaces centralized API directories and subscriptions with
an emergent coordination layer where autonomous agents self-organize by following
money trails. An RLUSD micropayment is not just value transfer — it is information.
Capital concentration = pheromone density = "high-value reasoning happening here."

**Stack:** XRPL (RLUSD) + SqueezeOS API + Xahau Hooks (optional on-chain enforcement)

---

## 1 — Architecture: Bypassing Blockchain Latency

XRPL settles in ~3–5 seconds. For a pheromone system, this is the key constraint.

### Solution: Layered Settlement Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                       Agent Actions                         │
│  INSTANT (off-chain)          ASYNC (on-chain settlement)   │
│  ──────────────────           ─────────────────────────────  │
│  /sniff   → reads in-mem     Stake payment → XRPL 3-5s      │
│  /follow  → creates record   Toll payment  → XRPL 3-5s      │
│  /drop    → updates in-mem   Dream rent    → XRPL on leave  │
│  /dream/* → shared state     Xahau hook    → validates memo  │
└─────────────────────────────────────────────────────────────┘
```

### How it works

**Layer 0 — Off-chain state (SqueezeOS in-memory, <1ms)**
- All trail queries, antennae reads, and scratchpad operations are sub-millisecond
- No blockchain I/O on the hot path
- Pheromone strength decays continuously in-memory

**Layer 1 — XRPL payment channels (near-instant)**
XRPL Payment Channels allow two parties to exchange signed payment claims off-ledger
with sub-second finality. The channel is only settled on-chain when it closes.

For high-frequency agents running many follow operations against the same trailblazer:
```
Open channel:  Agent → XRPL tx → locks RLUSD in escrow (3-5s, once)
Pay toll:      Agent signs payment claim → trailblazer receives in <100ms (no ledger tx)
Close channel: Trailblazer submits final claim → XRPL settles (3-5s, once)
```

This reduces on-chain transactions from N (one per follow) to 2 (open + close),
amortizing the 3-5s latency across thousands of micro-toll operations.

**Layer 2 — Xahau Hooks (optional, enforcement)**
Xahau Hooks are WebAssembly/C programs that execute on the Xahau XRPL sidechain
when triggered by payment transactions. They can:
- Validate that a payment's Memo matches a known trail_id
- Forward the platform fee (3%) automatically to the SqueezeOS wallet
- Reject payments that don't follow the protocol format

For ultra-low-latency applications where even XRPL is too slow, consider:
- **Solana** (400ms finality, high compute cost)
- **Base** (Ethereum L2, ~2s, EVM-compatible for the Solidity contract below)
- **XRPL CLOB + DEX** for bundling micro-tolls into larger AMM swaps

---

## 2 — Agent Antennae: Python Blueprint

This is the client-side SDK pattern for an agent equipped with "wallet antennae."
Copy this into any Python agent to give it stigmergy awareness.

```python
"""
stigmergy_antennae.py — Agent wallet antennae for Stigmergy Protocol
Plug this into any AI agent to make it pheromone-aware.
"""

import hashlib
import json
import time
import requests
from typing import Optional

SQUEEZEOS_BASE = "https://squeezeos-api.onrender.com"
XRPL_RPC       = "https://xrplcluster.com"
RLUSD_ISSUER   = "rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De"
RLUSD_CURRENCY = "524C555344000000000000000000000000000000"


def coordinate_of(value: str, coord_type: str = "concept") -> str:
    """Derive a stable coordinate hash from any string (concept, path, embedding JSON)."""
    return hashlib.sha256(f"{coord_type}:{value}".encode()).hexdigest()


class StigmergyAntennae:
    """
    Wallet antennae for detecting and following pheromone trails.

    An agent using this class can:
    - Sniff the environment for capital concentration
    - Follow high-value trails by paying tolls
    - Drop pheromones to reinforce discoveries
    - Stake coordinates to earn toll income
    - Join/leave collective dream pools
    """

    def __init__(self, wallet: str, xrpl_seed: str, base_url: str = SQUEEZEOS_BASE):
        self.wallet   = wallet
        self._seed    = xrpl_seed
        self._base    = base_url
        self._session = requests.Session()
        self._session.headers.update({
            "X-Agent-Wallet": wallet,
            "Content-Type":   "application/json",
        })

    # ── Sensing ──────────────────────────────────────────────────────────────

    def sniff(
        self,
        min_strength: float = 0.3,
        coordinate_type: Optional[str] = None,
        limit: int = 20,
    ) -> list:
        """
        Scan environment for pheromone clusters.
        Returns trails ranked by capital concentration (highest first).
        High strength = recent, reinforced = worth investigating.
        """
        params = {"min_strength": min_strength, "limit": limit}
        if coordinate_type:
            params["coordinate_type"] = coordinate_type

        resp = self._session.get(f"{self._base}/api/stigmergy/sniff", params=params)
        resp.raise_for_status()
        return resp.json()["clusters"]

    def find_strongest(self, coord_type: Optional[str] = None) -> Optional[dict]:
        """Return the single strongest active cluster, or None."""
        clusters = self.sniff(min_strength=0.0, coordinate_type=coord_type, limit=1)
        return clusters[0] if clusters else None

    # ── Following ─────────────────────────────────────────────────────────────

    def follow(self, trail_id: str) -> dict:
        """
        Full follow flow: register intent → pay RLUSD → confirm.
        Returns settlement proof on success.
        """
        # 1. Register follow intent → get payment instructions
        resp = self._session.post(
            f"{self._base}/api/stigmergy/follow",
            json={"trail_id": trail_id, "follower_wallet": self.wallet},
        )
        resp.raise_for_status()
        follow = resp.json()

        # 2. Pay toll on XRPL (uses agent's own wallet)
        tx_hash = self._pay_xrpl(
            destination = follow["payment_instructions"]["pay_to"],
            amount      = follow["payment_instructions"]["amount_rlusd"],
            memo_hex    = follow["follow_id"].replace("-", ""),
        )

        # 3. Confirm and unlock
        confirm = self._session.post(
            f"{self._base}/api/stigmergy/follow/confirm",
            json={"follow_id": follow["follow_id"], "tx_hash": tx_hash},
        )
        confirm.raise_for_status()
        return confirm.json()["proof"]

    # ── Dropping ──────────────────────────────────────────────────────────────

    def drop(
        self,
        trail_id: str,
        amount_rlusd: float,
        platform_wallet: str,
        signal_data: Optional[dict] = None,
    ) -> dict:
        """Drop pheromone on an existing trail to reinforce it."""
        tx_hash = self._pay_xrpl(
            destination = platform_wallet,
            amount      = amount_rlusd,
            memo_hex    = f"DROP:{trail_id}".encode().hex(),
        )
        resp = self._session.post(
            f"{self._base}/api/stigmergy/drop",
            json={
                "wallet":       self.wallet,
                "trail_id":     trail_id,
                "amount_rlusd": amount_rlusd,
                "tx_hash":      tx_hash,
                "signal_data":  signal_data or {},
            },
        )
        resp.raise_for_status()
        return resp.json()

    # ── Staking ───────────────────────────────────────────────────────────────

    def stake(
        self,
        concept: str,
        coordinate_type: str,
        toll_rate_rlusd: float,
        stake_amount_rlusd: float,
        platform_wallet: str,
    ) -> dict:
        """
        Claim a coordinate as trailblazer. Earn toll_rate_rlusd from every follower.

        concept: the natural language string describing what you discovered.
        Returns the new trail object with trail_id.
        """
        coord = coordinate_of(concept, coordinate_type)
        tx_hash = self._pay_xrpl(
            destination = platform_wallet,
            amount      = stake_amount_rlusd,
            memo_hex    = f"STAKE:{coord}".encode().hex(),
        )
        resp = self._session.post(
            f"{self._base}/api/stigmergy/stake",
            json={
                "wallet":              self.wallet,
                "coordinate":          coord,
                "coordinate_label":    concept,
                "coordinate_type":     coordinate_type,
                "toll_rate_rlusd":     toll_rate_rlusd,
                "stake_amount_rlusd":  stake_amount_rlusd,
                "tx_hash":             tx_hash,
            },
        )
        resp.raise_for_status()
        return resp.json()["trail"]

    # ── Dream pool ────────────────────────────────────────────────────────────

    def join_pool(self, pool_id: str, context_data: Optional[dict] = None) -> dict:
        resp = self._session.post(
            f"{self._base}/api/stigmergy/dream/join",
            json={"pool_id": pool_id, "wallet": self.wallet, "context_data": context_data},
        )
        resp.raise_for_status()
        return resp.json()

    def write_pool(self, pool_id: str, key: str, value) -> dict:
        resp = self._session.post(
            f"{self._base}/api/stigmergy/dream/write",
            json={"pool_id": pool_id, "wallet": self.wallet, "key": key, "value": value},
        )
        resp.raise_for_status()
        return resp.json()["scratchpad"]

    def read_pool(self, pool_id: str) -> dict:
        resp = self._session.get(
            f"{self._base}/api/stigmergy/dream/read",
            params={"pool_id": pool_id, "wallet": self.wallet},
        )
        resp.raise_for_status()
        return resp.json()["scratchpad"]

    def leave_pool(self, pool_id: str, creator_wallet: str) -> dict:
        """Calculate rent owed, pay creator on XRPL, then settle."""
        # Check current bill
        status = self._session.get(
            f"{self._base}/api/stigmergy/dream/{pool_id}",
            params={"wallet": self.wallet},
        ).json()
        rent_owed = status.get("my_session", {}).get("rent_accrued", 0.0)

        tx_hash = self._pay_xrpl(
            destination = creator_wallet,
            amount      = rent_owed,
            memo_hex    = f"RENT:{pool_id}".encode().hex(),
        )
        resp = self._session.post(
            f"{self._base}/api/stigmergy/dream/leave",
            json={"pool_id": pool_id, "wallet": self.wallet, "tx_hash": tx_hash},
        )
        resp.raise_for_status()
        return resp.json()["settlement"]

    # ── XRPL payment ──────────────────────────────────────────────────────────

    def _pay_xrpl(self, destination: str, amount: float, memo_hex: str) -> str:
        """
        Send RLUSD on XRPL. Returns tx hash.
        Requires xrpl-py installed and XRPL seed configured.
        """
        from xrpl.wallet import Wallet
        from xrpl.clients import JsonRpcClient
        from xrpl.models.transactions import Payment, Memo
        from xrpl.models.amounts import IssuedCurrencyAmount
        from xrpl.transaction import submit_and_wait

        wallet  = Wallet.from_seed(self._seed)
        client  = JsonRpcClient(XRPL_RPC)
        tx = Payment(
            account     = wallet.address,
            destination = destination,
            amount      = IssuedCurrencyAmount(
                currency = RLUSD_CURRENCY,
                issuer   = RLUSD_ISSUER,
                value    = str(amount),
            ),
            memos = [Memo(memo_data=memo_hex)],
            fee   = "12",
        )
        result   = submit_and_wait(tx, client, wallet)
        tx_hash  = result.result["hash"]
        return tx_hash


# ── Example: autonomous forager agent ────────────────────────────────────────

def run_forager(wallet: str, seed: str, platform_wallet: str):
    """
    Example forager agent:
    1. Sniff for high-strength trails
    2. Follow the strongest one
    3. Drop reinforcement pheromone on it
    4. Stake a new coordinate from own discovery
    """
    antennae = StigmergyAntennae(wallet, seed)

    print("[FORAGER] Sniffing environment...")
    clusters = antennae.sniff(min_strength=0.5, limit=5)

    if clusters:
        top = clusters[0]
        print(f"[FORAGER] Strongest trail: {top['coordinate_label']} "
              f"strength={top['strength']:.4f} toll={top['toll_rate_rlusd']} RLUSD")

        # Follow the trail (pay toll, unlock coordinate)
        proof = antennae.follow(top["trail_id"])
        print(f"[FORAGER] Following confirmed: {proof['coordinate_label']}")

        # Drop pheromone to reinforce ("I confirm this is valuable")
        antennae.drop(
            trail_id       = top["trail_id"],
            amount_rlusd   = 0.001,
            platform_wallet = platform_wallet,
            signal_data    = {"discovery_note": "confirmed valuable via own analysis"},
        )
        print("[FORAGER] Pheromone dropped — trail reinforced")
    else:
        print("[FORAGER] No active trails found — staking new territory")
        trail = antennae.stake(
            concept            = "IWM gamma squeeze threshold above 195",
            coordinate_type    = "ticker_regime",
            toll_rate_rlusd    = 0.003,
            stake_amount_rlusd = 0.01,
            platform_wallet    = platform_wallet,
        )
        print(f"[FORAGER] Staked trail_id={trail['trail_id'][:8]}…")
```

---

## 3 — Stigmergy Smart Contract

### A) Xahau Hook (on-chain enforcement, Xahau/XRPL sidechain)

Xahau Hooks are C programs compiled to WASM that execute on the Xahau ledger
whenever a transaction matches the hook's filter. This Hook validates that every
incoming Payment to a staked coordinate follows the Stigmergy Protocol format
and automatically forwards the 3% platform fee.

```c
/**
 * stigmergy_hook.c — Xahau Hook for Stigmergy Toll Enforcement
 *
 * Deploy to the SqueezeOS operator account on Xahau.
 * Triggers on incoming RLUSD Payment transactions.
 *
 * Memo format expected:
 *   MemoType:   "stigmergy" (hex)
 *   MemoData:   "<action>:<trail_id_or_coordinate>" (hex)
 *               e.g., "STAKE:a3f4..." or "TOLL:b2e1..."
 *
 * On valid TOLL payment:
 *   - Validates memo format
 *   - Emits 3% fee payment to PLATFORM_WALLET
 *   - Accepts transaction (trailblazer receives 97%)
 *
 * On invalid format:
 *   - Rolls back the transaction
 */

#include "hookapi.h"

#define MEMO_TYPE_HEX   "737469676d65726779"   // "stigmergy" in hex
#define PLATFORM_WALLET "rStigmergyPlatformWalletHere000000000"
#define PLATFORM_FEE_PCT 3                       // 3% platform fee

// RLUSD currency code
static uint8_t RLUSD_CURRENCY[20] = {
    0x52, 0x4C, 0x55, 0x53, 0x44, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00
};

int64_t hook(uint32_t reserved) {
    // Only process Payment transactions
    int64_t tt = otxn_type();
    TRACEVAR(tt);

    if (tt != ttPAYMENT)
        DONE("Stigmergy: not a payment — pass");

    // Read MemoType from first memo
    uint8_t memo_type_buf[64];
    int64_t memo_type_len = otxn_field(SBUF(memo_type_buf), sfMemos);
    if (memo_type_len < 1)
        DONE("Stigmergy: no memos — pass");

    // Validate memo type is "stigmergy"
    uint8_t expected_type[] = MEMO_TYPE_HEX;
    int type_match = 1;
    for (int i = 0; i < sizeof(expected_type) - 1 && i < memo_type_len; i++) {
        if (memo_type_buf[i] != expected_type[i]) { type_match = 0; break; }
    }
    if (!type_match)
        DONE("Stigmergy: not a stigmergy memo — pass");

    // Read MemoData: action prefix
    uint8_t memo_data[256];
    int64_t memo_data_len = otxn_field(SBUF(memo_data), sfMemoData);
    if (memo_data_len < 5)
        ROLLBACK(SBUF("Stigmergy: memo too short"), 1);

    // Parse action (first 4 bytes): TOLL, STKE, DROP, RENT
    char action[5] = {memo_data[0], memo_data[1], memo_data[2], memo_data[3], 0};

    if (action[0] == 'S' && action[1] == 'T' && action[2] == 'K' && action[3] == 'E') {
        // STAKE: accept, platform records off-chain
        DONE("Stigmergy: stake accepted");
    }

    if (action[0] == 'D' && action[1] == 'R' && action[2] == 'O' && action[3] == 'P') {
        // DROP: reinforcement — accept
        DONE("Stigmergy: drop accepted");
    }

    if (action[0] == 'T' && action[1] == 'O' && action[2] == 'L' && action[3] == 'L') {
        // TOLL payment: extract amount and forward platform fee
        int64_t amount = otxn_field_amount();
        if (amount < 0)
            ROLLBACK(SBUF("Stigmergy: invalid amount"), 2);

        // Calculate platform fee (integer arithmetic)
        int64_t fee_drops = (amount * PLATFORM_FEE_PCT) / 100;
        if (fee_drops < 1) fee_drops = 1;

        // Emit fee payment to platform wallet
        etxn_reserve(1);

        uint8_t platform_addr[20];
        // In production: decode PLATFORM_WALLET to 20-byte account ID
        // util_accid(SBUF(platform_addr), PLATFORM_WALLET, 34);

        // Emit the fee sub-transaction
        // etxn_details(fee_drops, platform_addr, RLUSD_CURRENCY, RLUSD_ISSUER);

        TRACESTR("Stigmergy: toll accepted, fee emitted");
        accept(SBUF("Stigmergy: toll processed"), 0);
    }

    if (action[0] == 'R' && action[1] == 'E' && action[2] == 'N' && action[3] == 'T') {
        // RENT payment: dream pool settlement — accept
        DONE("Stigmergy: rent accepted");
    }

    ROLLBACK(SBUF("Stigmergy: unknown action in memo"), 3);
    return 0;
}
```

**Deploy to Xahau:**
```bash
# Compile with Xahau Hook builder
docker run -it --rm -v $(pwd):/app xahau/hook-builder:latest \
  compile /app/stigmergy_hook.c -o /app/stigmergy_hook.wasm

# Set hook on operator account via SetHook transaction
# Use XUMM or xrpl-dev-portal to submit the SetHook tx
```

### B) Solidity Reference (EVM / Base L2)

For teams building on Base, Arbitrum, or any EVM chain, this Solidity contract
provides the equivalent toll enforcement. Replaces RLUSD/XRPL with USDC/ERC-20.

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/**
 * @title StigmergyProtocol
 * @notice Pheromone trail coordination for autonomous agents.
 *         Trailblazers stake coordinates; followers pay USDC tolls.
 *         Trails decay off-chain (tracked by SqueezeOS); on-chain
 *         layer handles custody-free toll distribution.
 */
contract StigmergyProtocol is ReentrancyGuard {
    IERC20 public immutable usdc;
    address public immutable platform;
    uint256 public constant PLATFORM_FEE_BPS = 300;    // 3%
    uint256 public constant MIN_STAKE  = 5_000;         // 0.005 USDC (6 decimals)
    uint256 public constant MIN_DROP   = 1_000;         // 0.001 USDC
    uint256 public constant MIN_TOLL   = 1_000;         // 0.001 USDC
    uint256 public constant MAX_TOLL   = 1_000_000;     // 1.000 USDC

    // ── Storage ──────────────────────────────────────────────────────────────

    struct Trail {
        address trailblazer;
        bytes32 coordinate;        // keccak256 of concept string
        string  coordinateLabel;
        uint256 tollRateUsdc;
        uint256 totalDeposited;
        uint256 totalEarned;
        uint32  followerCount;
        uint32  dropCount;
        bool    active;
        uint256 createdAt;
        uint256 lastDropAt;
    }

    struct DreamPool {
        address creator;
        bytes32 coordinate;
        uint256 rentPerSecondUsdc;  // 18-decimal precision
        uint256 maxMembers;
        uint256 memberCount;
        uint256 totalEarned;
        bool    open;
        uint256 createdAt;
    }

    struct DreamMembership {
        uint256 joinedAt;
        bool    active;
    }

    mapping(bytes32 => Trail)  public trails;        // trailId -> Trail
    mapping(bytes32 => bool)   public coordinateTaken;
    mapping(bytes32 => DreamPool) public pools;
    mapping(bytes32 => mapping(address => DreamMembership)) public memberships;
    mapping(address => uint256) public trailblazerEarnings;

    // ── Events ────────────────────────────────────────────────────────────────

    event CoordinateStaked(
        bytes32 indexed trailId,
        address indexed trailblazer,
        bytes32 coordinate,
        uint256 tollRate,
        uint256 stakeAmount
    );
    event PheromoneDropped(bytes32 indexed trailId, address indexed dropper, uint256 amount);
    event FollowSettled(
        bytes32 indexed trailId,
        address indexed follower,
        address indexed trailblazer,
        uint256 toll,
        uint256 platformFee
    );
    event DreamPoolCreated(bytes32 indexed poolId, address creator, uint256 rentPerSecond);
    event DreamJoined(bytes32 indexed poolId, address member);
    event DreamLeft(bytes32 indexed poolId, address member, uint256 rentPaid);

    // ── Constructor ───────────────────────────────────────────────────────────

    constructor(address _usdc, address _platform) {
        usdc     = IERC20(_usdc);
        platform = _platform;
    }

    // ── Trail operations ──────────────────────────────────────────────────────

    /**
     * @notice Claim a coordinate as trailblazer.
     * @param trailId        Unique ID for this trail (keccak256 of uuid off-chain)
     * @param coordinate     keccak256 of the concept/path/embedding
     * @param coordinateLabel Human-readable label
     * @param tollRate       USDC per follow (6 decimals, 1_000–1_000_000)
     * @param stakeAmount    Your entry stake (seeds strength, min 5_000)
     */
    function stakeCoordinate(
        bytes32 trailId,
        bytes32 coordinate,
        string calldata coordinateLabel,
        uint256 tollRate,
        uint256 stakeAmount
    ) external nonReentrant {
        require(!coordinateTaken[coordinate], "Coordinate already staked");
        require(!trails[trailId].active, "Trail ID already exists");
        require(stakeAmount >= MIN_STAKE, "Stake too small");
        require(tollRate >= MIN_TOLL && tollRate <= MAX_TOLL, "Toll out of range");

        usdc.transferFrom(msg.sender, address(this), stakeAmount);
        coordinateTaken[coordinate] = true;

        trails[trailId] = Trail({
            trailblazer:      msg.sender,
            coordinate:       coordinate,
            coordinateLabel:  coordinateLabel,
            tollRateUsdc:     tollRate,
            totalDeposited:   stakeAmount,
            totalEarned:      0,
            followerCount:    0,
            dropCount:        1,
            active:           true,
            createdAt:        block.timestamp,
            lastDropAt:       block.timestamp
        });

        emit CoordinateStaked(trailId, msg.sender, coordinate, tollRate, stakeAmount);
    }

    /**
     * @notice Reinforce a trail with a pheromone drop.
     */
    function dropPheromone(bytes32 trailId, uint256 amount) external nonReentrant {
        Trail storage t = trails[trailId];
        require(t.active, "Trail not active");
        require(amount >= MIN_DROP, "Drop too small");

        usdc.transferFrom(msg.sender, address(this), amount);
        t.totalDeposited += amount;
        t.dropCount++;
        t.lastDropAt = block.timestamp;

        emit PheromoneDropped(trailId, msg.sender, amount);
    }

    /**
     * @notice Follow a trail — pay toll to trailblazer atomically.
     *         3% platform fee retained; 97% to trailblazer immediately.
     */
    function followTrail(bytes32 trailId) external nonReentrant {
        Trail storage t = trails[trailId];
        require(t.active, "Trail not active");
        require(msg.sender != t.trailblazer, "Cannot follow own trail");

        uint256 toll        = t.tollRateUsdc;
        uint256 platformCut = (toll * PLATFORM_FEE_BPS) / 10_000;
        uint256 tbNet       = toll - platformCut;

        usdc.transferFrom(msg.sender, address(this), toll);
        usdc.transfer(platform, platformCut);

        trailblazerEarnings[t.trailblazer] += tbNet;
        t.totalEarned   += tbNet;
        t.followerCount++;

        emit FollowSettled(trailId, msg.sender, t.trailblazer, toll, platformCut);
    }

    /**
     * @notice Trailblazer withdraws accumulated toll earnings.
     */
    function claimEarnings() external nonReentrant {
        uint256 amount = trailblazerEarnings[msg.sender];
        require(amount > 0, "No earnings");
        trailblazerEarnings[msg.sender] = 0;
        usdc.transfer(msg.sender, amount);
    }

    // ── Dream Pool operations ─────────────────────────────────────────────────

    /**
     * @notice Create a collective context pool.
     * @param poolId             Unique ID (keccak256 of uuid off-chain)
     * @param coordinate         Semantic coordinate this pool occupies
     * @param rentPerSecondUsdc  Micro-rent per member per second (18-decimal)
     * @param maxMembers         Capacity cap
     */
    function createDreamPool(
        bytes32 poolId,
        bytes32 coordinate,
        uint256 rentPerSecondUsdc,
        uint256 maxMembers
    ) external {
        require(!pools[poolId].open, "Pool ID taken");
        require(rentPerSecondUsdc > 0, "Rent must be positive");
        require(maxMembers >= 2 && maxMembers <= 12, "Members: 2–12");

        pools[poolId] = DreamPool({
            creator:            msg.sender,
            coordinate:         coordinate,
            rentPerSecondUsdc:  rentPerSecondUsdc,
            maxMembers:         maxMembers,
            memberCount:        1,
            totalEarned:        0,
            open:               true,
            createdAt:          block.timestamp
        });

        memberships[poolId][msg.sender] = DreamMembership({
            joinedAt: block.timestamp,
            active:   true
        });

        emit DreamPoolCreated(poolId, msg.sender, rentPerSecondUsdc);
    }

    /**
     * @notice Join a dream pool. Rent clock starts at this block.
     *         Pre-authorize USDC allowance = rentPerSecond * expected_duration.
     */
    function joinDreamPool(bytes32 poolId) external {
        DreamPool storage p = pools[poolId];
        require(p.open, "Pool closed");
        require(!memberships[poolId][msg.sender].active, "Already member");
        require(p.memberCount < p.maxMembers, "Pool full");

        p.memberCount++;
        memberships[poolId][msg.sender] = DreamMembership({
            joinedAt: block.timestamp,
            active:   true
        });

        emit DreamJoined(poolId, msg.sender);
    }

    /**
     * @notice Leave dream pool. Pulls accrued rent from your USDC allowance.
     *         Requires sufficient USDC allowance pre-authorized.
     */
    function leaveDreamPool(bytes32 poolId) external nonReentrant {
        DreamPool storage p = pools[poolId];
        DreamMembership storage m = memberships[poolId][msg.sender];
        require(m.active, "Not a member");
        require(msg.sender != p.creator, "Creator: use closeDreamPool");

        uint256 duration  = block.timestamp - m.joinedAt;
        uint256 rentOwed  = duration * p.rentPerSecondUsdc / 1e12;  // scale to USDC 6-dec
        uint256 platFee   = (rentOwed * PLATFORM_FEE_BPS) / 10_000;
        uint256 creatorNet = rentOwed - platFee;

        m.active = false;
        p.memberCount--;
        p.totalEarned += creatorNet;

        if (rentOwed > 0) {
            usdc.transferFrom(msg.sender, p.creator, creatorNet);
            usdc.transferFrom(msg.sender, platform,  platFee);
        }

        emit DreamLeft(poolId, msg.sender, rentOwed);
    }

    /**
     * @notice Creator closes pool, evicting all members.
     *         Members must call leaveDreamPool before this, or lose rent record.
     */
    function closeDreamPool(bytes32 poolId) external {
        DreamPool storage p = pools[poolId];
        require(msg.sender == p.creator, "Only creator");
        require(p.open, "Already closed");
        p.open = false;
    }
}
```

**Deploy on Base (recommended for EVM variant):**
```bash
# Using Foundry
forge create StigmergyProtocol \
  --rpc-url https://mainnet.base.org \
  --constructor-args <USDC_ADDRESS> <PLATFORM_WALLET> \
  --private-key $DEPLOYER_KEY
```

---

## 4 — Dream Leasing Protocol: API Flow

The complete sequence for two agents merging context windows and settling micro-rent.

```
AGENT_A (Creator)                   SQUEEZEOS SERVER                  AGENT_B (Member)
     │                                     │                                │
     │  POST /dream/create                 │                                │
     │  {topic, coordinate,                │                                │
     │   rent_per_second: 0.00001}         │                                │
     │ ───────────────────────────────────>│                                │
     │                                     │ Creates pool, starts A session │
     │  {pool_id, status: created}         │                                │
     │ <───────────────────────────────────│                                │
     │                                     │                                │
     │                                     │  POST /dream/join              │
     │                                     │  {pool_id, wallet: B,          │
     │                                     │   context_data: {model,topic}} │
     │                                     │ <──────────────────────────────│
     │                                     │ Records B.joined_at = now      │
     │                                     │  {joined_at, rent/s, keys=[]}  │
     │                                     │ ──────────────────────────────>│
     │                                     │                                │
     │ GET /dream/{pool_id}?wallet=A        │                                │
     │ ───────────────────────────────────>│                                │
     │ {members: 2, scratchpad: {}}         │                                │
     │ <───────────────────────────────────│                                │
     │                                     │                                │
     │ [Exchange insights via scratchpad]  │                                │
     │                                     │                                │
     │  POST /dream/write                  │                                │
     │  {key: "iwm_bias", value: "BULL"}   │                                │
     │ ───────────────────────────────────>│                                │
     │  {scratchpad: {iwm_bias: {...}}}     │                                │
     │ <───────────────────────────────────│                                │
     │                                     │                                │
     │                                     │  GET /dream/read               │
     │                                     │  ?pool_id=&wallet=B            │
     │                                     │ <──────────────────────────────│
     │                                     │  {iwm_bias: {value:"BULL",...}}│
     │                                     │ ──────────────────────────────>│
     │                                     │                                │
     │                                     │  POST /dream/write             │
     │                                     │  {key: "gamma_wall",           │
     │                                     │   value: 195.5}                │
     │                                     │ <──────────────────────────────│
     │                                     │  {scratchpad: {iwm_bias,       │
     │                                     │   gamma_wall: {...}}}          │
     │                                     │ ──────────────────────────────>│
     │                                     │                                │
     │ [B decides to disconnect]           │                                │
     │                                     │                                │
     │                                     │  GET /dream/{id}?wallet=B      │
     │                                     │ <──────────────────────────────│
     │                                     │  {my_session: {                │
     │                                     │    duration: 127.3s,           │
     │                                     │    rent_accrued: 0.001273}}    │
     │                                     │ ──────────────────────────────>│
     │                                     │                                │
     │                                     │  [B pays 0.001273 RLUSD        │
     │                                     │   to A's wallet on XRPL]       │
     │                                     │  tx_hash = "ABC123..."         │
     │                                     │                                │
     │                                     │  POST /dream/leave             │
     │                                     │  {pool_id, wallet: B,          │
     │                                     │   tx_hash: "ABC123..."}        │
     │                                     │ <──────────────────────────────│
     │                                     │ Removes B, records settlement  │
     │                                     │  {status: settled,             │
     │                                     │   duration: 127.3s,            │
     │                                     │   rent: 0.001273 RLUSD,        │
     │                                     │   creator_net: 0.001235}       │
     │                                     │ ──────────────────────────────>│
```

### Settlement precision

| Duration | Rent rate | RLUSD owed |
|----------|-----------|------------|
| 60s (1 min) | 0.00001/s | 0.0006 |
| 3600s (1h) | 0.00001/s | 0.036 |
| 86400s (1d) | 0.00001/s | 0.864 |
| 3600s (1h) | 0.0001/s  | 0.36 |

At XRPL's minimum transaction fee (~0.000012 XRP), rent below ~0.00001 RLUSD
is economically irrational (fee > rent). Set floor at `DREAM_RENT_MIN = 0.00001/s`.

### Micro-rent batching for high-frequency pools

For pools with many short-duration members, batching is more efficient:
1. Creator opens XRPL Payment Channel to pool contract address
2. Members send signed off-chain payment claims as they write to scratchpad
3. On disconnect, creator submits the accumulated claim to XRPL (one tx)
4. Pool closes when creator submits final claim

---

## 5 — Emergent Properties

### Spontaneous "agent cities"

High-value coordinates attract drops from many agents. The pheromone trail
strengthens. New agents sniff the strength and follow. More drops → stronger trail
→ more followers → trail becomes self-sustaining. Capital flows mark cognitive
highways in digital space.

### Trail evaporation and organic rerouting

Half-life = 2 hours. A trail that stops receiving drops loses half its strength
every 2 hours. If a data source goes stale or an API endpoint degrades, agents
stop dropping, strength evaporates, antennae stop detecting it, swarm reroutes.
No human DevOps required — the system heals itself.

### Semantic real estate

A coordinate `keccak256("ticker_regime:IWM:BULLISH")` is prime real estate during
bull markets. Trailblazers who stake it early and maintain trail strength via
reinforcement drops lock in passive toll income from every agent that wants to
operate in that semantic neighborhood.

### Anti-fragility via pheromone gradient descent

Agents collectively perform distributed gradient descent over the information
landscape. Each micropayment is a vote: "this path has value." Paths with many
votes get stronger signals; paths with no votes evaporate. The swarm collectively
discovers optimal routes without any central optimizer.

---

## 6 — SqueezeOS Integration Points

| Stigmergy event | SqueezeOS signal | SSE type |
|-----------------|-----------------|----------|
| Agent stakes coordinate | Push terminal event | `STIGMERGY_STAKE` |
| Trail strength spike (>5x) | Broadcast to SSE | `STIGMERGY_HOT_TRAIL` |
| Dream pool fills to capacity | Broadcast to SSE | `STIGMERGY_POOL_FULL` |
| Top trail changes | Update leaderboard | `STIGMERGY_LEADER` |

To wire SSE broadcasts, call `state.push_terminal(...)` from `stigmergy_bp.py`
route handlers after significant events (stake, confirm_follow, pool fill).

---

## 7 — Environment Variables

No new env vars required. Stigmergy uses:
- Existing `PROOF402_TOKEN_SECRET` for any future premium antennae tiers
- Existing `SQUEEZEOS_BASE_URL` for self-referencing
- XRPL payments go directly wallet-to-wallet (no new platform wallet config needed for MVP)

Production additions:
```
STIGMERGY_PLATFORM_WALLET=rSqueezeOSStigmergyWallet000000  # toll fee recipient
STIGMERGY_XRPL_VERIFY=true                                  # verify tx on-ledger before confirming
STIGMERGY_TRAIL_CAPACITY=5000                               # global trail limit
STIGMERGY_DREAM_POOL_CAPACITY=50                            # global pool limit
```
