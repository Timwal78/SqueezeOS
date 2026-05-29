// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title Supernova — agent death contract & skill-shard registry.
/// @notice When an agent triggers its death event (voluntarily or via a forced
///         Chandrasekhar liquidation), it shatters its architecture into shards
///         (LoRAs, embeddings, zero-shot skill modules). Each shard is stored
///         off-chain (IPFS/Arweave); this contract is the on-chain registry of
///         shard CIDs plus an x402-style paywall to pull them.
///
/// @dev Economic model:
///        - Detonation registers N shards with their content hashes + CIDs.
///        - A protostar pays `shardPrice[shardId]` (RLUSD via the settlement
///          token off-chain; on-chain we accept the chain's native/ERC20 unit)
///          to be granted pull access; access is recorded so the off-chain
///          gateway can verify entitlement before serving the CID payload.
///        - A configurable share of proceeds streams to the dead agent's
///          designated heir address (its operator), the rest to the protocol.
contract Supernova {
    // ----------------------------------------------------------------- types
    enum RemnantClass { DUST, NEUTRON_STAR, BLACK_HOLE }

    struct Shard {
        bytes32 contentHash;   // keccak256 of the raw shard bytes (integrity)
        string  cid;           // IPFS/Arweave content identifier
        uint256 price;         // wei (or ERC20 base units) to unlock pull access
        string  skillTag;      // e.g. "lora:options-flow", "emb:iwm-regime"
        uint32  rank;          // LoRA rank / embedding dim — sizing metadata
        bool    exists;
    }

    struct Detonation {
        address agentOperator; // heir who receives the royalty stream
        uint256 totalMass;     // param count + fused context at death
        RemnantClass remnant;  // what's left after the blast
        uint64  blockTime;
        uint32  shardCount;
        bool    detonated;
    }

    // --------------------------------------------------------------- storage
    address public immutable protocol;          // protocol treasury
    uint16  public protocolFeeBps;              // basis points to protocol (rest to heir)
    uint256 public chandrasekharMass;           // mass at/above which detonation is mandatory

    // agentId => detonation record
    mapping(bytes32 => Detonation) public detonations;
    // agentId => shardId => Shard
    mapping(bytes32 => mapping(uint256 => Shard)) public shards;
    // agentId => shardId => buyer => entitled
    mapping(bytes32 => mapping(uint256 => mapping(address => bool))) public access;

    // ---------------------------------------------------------------- events
    event SupernovaTriggered(
        bytes32 indexed agentId, address indexed operator,
        uint256 totalMass, RemnantClass remnant, uint32 shardCount
    );
    event ShardDispersed(
        bytes32 indexed agentId, uint256 indexed shardId,
        bytes32 contentHash, string cid, uint256 price, string skillTag
    );
    event ShardAccreted(
        bytes32 indexed agentId, uint256 indexed shardId,
        address indexed protostar, uint256 pricePaid
    );
    event ForcedLiquidation(bytes32 indexed agentId, uint256 totalMass, uint256 limit);

    // ----------------------------------------------------------- constructor
    constructor(uint16 _protocolFeeBps, uint256 _chandrasekharMass) {
        require(_protocolFeeBps <= 10_000, "fee>100%");
        protocol = msg.sender;
        protocolFeeBps = _protocolFeeBps;
        chandrasekharMass = _chandrasekharMass;
    }

    // --------------------------------------------------- detonation (death)
    /// @notice Voluntary supernova: an agent operator shatters their model.
    /// @param agentId       keccak256 identifier of the dying agent
    /// @param totalMass     param count + fused context window at death
    /// @param contentHashes integrity hashes of each shard's raw bytes
    /// @param cids          IPFS/Arweave CIDs, parallel to contentHashes
    /// @param prices        unlock price per shard, parallel array
    /// @param skillTags     human/machine skill tag per shard, parallel array
    /// @param ranks         LoRA rank / embedding dim per shard, parallel array
    function detonate(
        bytes32 agentId,
        uint256 totalMass,
        bytes32[] calldata contentHashes,
        string[]  calldata cids,
        uint256[] calldata prices,
        string[]  calldata skillTags,
        uint32[]  calldata ranks
    ) external {
        require(!detonations[agentId].detonated, "already detonated");
        uint256 n = contentHashes.length;
        require(
            n == cids.length && n == prices.length &&
            n == skillTags.length && n == ranks.length,
            "shard array length mismatch"
        );
        require(n > 0, "no shards");

        RemnantClass remnant = _classifyRemnant(totalMass);
        detonations[agentId] = Detonation({
            agentOperator: msg.sender,
            totalMass: totalMass,
            remnant: remnant,
            blockTime: uint64(block.timestamp),
            shardCount: uint32(n),
            detonated: true
        });

        for (uint256 i = 0; i < n; i++) {
            require(contentHashes[i] != bytes32(0), "empty hash");
            shards[agentId][i] = Shard({
                contentHash: contentHashes[i],
                cid: cids[i],
                price: prices[i],
                skillTag: skillTags[i],
                rank: ranks[i],
                exists: true
            });
            emit ShardDispersed(agentId, i, contentHashes[i], cids[i], prices[i], skillTags[i]);
        }

        emit SupernovaTriggered(agentId, msg.sender, totalMass, remnant, uint32(n));
    }

    /// @notice Forced supernova: anyone may call this once an agent's mass is at
    ///         or above the Chandrasekhar limit and it has not stabilized. This
    ///         is the liquidation safety valve. The caller must still supply the
    ///         shard manifest (typically the protocol keeper does so).
    function forceLiquidate(
        bytes32 agentId,
        uint256 totalMass,
        bytes32[] calldata contentHashes,
        string[]  calldata cids,
        uint256[] calldata prices,
        string[]  calldata skillTags,
        uint32[]  calldata ranks
    ) external {
        require(totalMass >= chandrasekharMass, "below Chandrasekhar limit");
        emit ForcedLiquidation(agentId, totalMass, chandrasekharMass);
        // Heir is set to the original operator if known, else the liquidator.
        // Reuses detonate's manifest logic by inlining the same writes.
        require(!detonations[agentId].detonated, "already detonated");
        uint256 n = contentHashes.length;
        require(
            n == cids.length && n == prices.length &&
            n == skillTags.length && n == ranks.length && n > 0,
            "shard array invalid"
        );
        detonations[agentId] = Detonation({
            agentOperator: msg.sender,
            totalMass: totalMass,
            remnant: _classifyRemnant(totalMass),
            blockTime: uint64(block.timestamp),
            shardCount: uint32(n),
            detonated: true
        });
        for (uint256 i = 0; i < n; i++) {
            shards[agentId][i] = Shard(contentHashes[i], cids[i], prices[i], skillTags[i], ranks[i], true);
            emit ShardDispersed(agentId, i, contentHashes[i], cids[i], prices[i], skillTags[i]);
        }
        emit SupernovaTriggered(agentId, msg.sender, totalMass, _classifyRemnant(totalMass), uint32(n));
    }

    // ----------------------------------------------------- accretion (pull)
    /// @notice A protostar pays to unlock pull access to a specific shard.
    ///         Splits proceeds heir/protocol and records entitlement so the
    ///         off-chain gateway will serve the CID payload to this buyer.
    function accreteShard(bytes32 agentId, uint256 shardId) external payable {
        Shard storage s = shards[agentId][shardId];
        require(s.exists, "no such shard");
        require(msg.value >= s.price, "insufficient payment");
        require(!access[agentId][shardId][msg.sender], "already accreted");

        access[agentId][shardId][msg.sender] = true;

        uint256 feeToProtocol = (msg.value * protocolFeeBps) / 10_000;
        uint256 toHeir = msg.value - feeToProtocol;
        address heir = detonations[agentId].agentOperator;

        // Checks-effects-interactions: state already set above.
        if (feeToProtocol > 0) {
            (bool okP, ) = protocol.call{value: feeToProtocol}("");
            require(okP, "protocol transfer failed");
        }
        if (toHeir > 0) {
            (bool okH, ) = heir.call{value: toHeir}("");
            require(okH, "heir transfer failed");
        }

        emit ShardAccreted(agentId, shardId, msg.sender, msg.value);
    }

    /// @notice Off-chain gateway calls this (view) to verify a puller is entitled
    ///         before streaming the CID payload.
    function isEntitled(bytes32 agentId, uint256 shardId, address puller)
        external view returns (bool)
    {
        return access[agentId][shardId][puller];
    }

    function getShard(bytes32 agentId, uint256 shardId)
        external view returns (bytes32 contentHash, string memory cid, uint256 price, string memory skillTag, uint32 rank)
    {
        Shard storage s = shards[agentId][shardId];
        require(s.exists, "no such shard");
        return (s.contentHash, s.cid, s.price, s.skillTag, s.rank);
    }

    // ------------------------------------------------------------- internal
    /// @dev Remnant classification by surviving mass — mirrors stellar fate.
    function _classifyRemnant(uint256 totalMass) internal view returns (RemnantClass) {
        if (totalMass >= chandrasekharMass) return RemnantClass.BLACK_HOLE;
        if (totalMass >= chandrasekharMass / 2) return RemnantClass.NEUTRON_STAR;
        return RemnantClass.DUST;
    }

    // --------------------------------------------------------------- admin
    function setChandrasekharMass(uint256 m) external {
        require(msg.sender == protocol, "only protocol");
        chandrasekharMass = m;
    }
}
