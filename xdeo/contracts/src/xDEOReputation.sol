// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { ERC721 } from "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import { AccessControl } from "@openzeppelin/contracts/access/AccessControl.sol";
import { UD60x18, ud, UNIT } from "@prb/math/src/UD60x18.sol";
import { ReputationMath } from "./lib/ReputationMath.sol";
import { IxDEOCore } from "./IxDEOCore.sol";

/// @title xDEOReputation
/// @notice Soulbound (non-transferable) reputation + tier badge. One badge per
///         analyst (tokenId = uint160(address)). Reputation compounds via the
///         shared ReputationMath EMA. Only the core contract may mutate state.
///
/// @dev    Tier here uses reputation thresholds as a gas-pragmatic approximation;
///         the authoritative top-10 (ORACLE/LEGEND) ranking is computed off-chain
///         where global ordering is cheap. NOT YET COMPILED IN CI (see README).
contract xDEOReputation is ERC721, AccessControl {
    using ReputationMath for UD60x18;

    bytes32 public constant CORE_ROLE = keccak256("CORE_ROLE");

    struct Profile {
        UD60x18 reputation; // [0,100]
        UD60x18 accuracy; // [0,1]
        uint64 scoredCount;
        uint64 estimateCount;
        uint64 streakDays;
        IxDEOCore.Tier tier;
        bool exists;
    }

    mapping(address => Profile) private _profiles;

    event Registered(address indexed analyst, uint256 tokenId);
    event Scored(address indexed analyst, uint256 reputationWad, IxDEOCore.Tier tier);

    error Soulbound();
    error NotRegistered();

    constructor(address admin) ERC721("xDEO Reputation", "xREP") {
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
    }

    // --- core-only mutations -------------------------------------------------

    /// @notice Mint a soulbound badge for a new analyst (idempotent).
    function register(address analyst) external onlyRole(CORE_ROLE) {
        Profile storage p = _profiles[analyst];
        if (p.exists) return;
        p.exists = true;
        p.tier = IxDEOCore.Tier.OBSERVER;
        uint256 tokenId = uint256(uint160(analyst));
        _safeMint(analyst, tokenId);
        emit Registered(analyst, tokenId);
    }

    /// @notice Record a submission: bump count, promote OBSERVER→ANALYST at 5.
    function bumpEstimate(address analyst) external onlyRole(CORE_ROLE) {
        Profile storage p = _profiles[analyst];
        if (!p.exists) revert NotRegistered();
        p.estimateCount += 1;
        if (p.tier == IxDEOCore.Tier.OBSERVER && p.estimateCount >= 5) {
            p.tier = IxDEOCore.Tier.ANALYST;
        }
    }

    /// @notice Fold a freshly-scored estimate into reputation + accuracy.
    /// @param scoreWad estimate score, UD60x18 in [0,100]
    function recordScore(address analyst, UD60x18 scoreWad)
        external
        onlyRole(CORE_ROLE)
    {
        Profile storage p = _profiles[analyst];
        if (!p.exists) revert NotRegistered();

        UD60x18 streakMult = ReputationMath.streakMultiplier(p.streakDays);
        p.reputation = ReputationMath.updateReputation(
            p.reputation,
            p.scoredCount,
            scoreWad,
            streakMult
        );
        // accuracy EMA over score/100, no streak.
        UD60x18 acc01 = scoreWad.div(ud(100e18));
        p.accuracy = ReputationMath.ema(p.accuracy, acc01, p.scoredCount);
        p.scoredCount += 1;
        p.tier = _tier(p);

        emit Scored(analyst, UD60x18.unwrap(p.reputation), p.tier);
    }

    /// @notice Set the current streak (driven by the core/oracle on activity).
    function setStreak(address analyst, uint64 streakDays)
        external
        onlyRole(CORE_ROLE)
    {
        if (!_profiles[analyst].exists) revert NotRegistered();
        _profiles[analyst].streakDays = streakDays;
    }

    // --- views ---------------------------------------------------------------

    function reputationOf(address analyst)
        external
        view
        returns (uint256 reputationWad, IxDEOCore.Tier tier)
    {
        Profile storage p = _profiles[analyst];
        return (UD60x18.unwrap(p.reputation), p.tier);
    }

    function profileOf(address analyst) external view returns (Profile memory) {
        return _profiles[analyst];
    }

    // --- tier (reputation-threshold approximation) ---------------------------

    function _tier(Profile storage p) private view returns (IxDEOCore.Tier) {
        uint256 rep = UD60x18.unwrap(p.reputation);
        uint256 acc = UD60x18.unwrap(p.accuracy);
        if (rep >= 97e18) return IxDEOCore.Tier.LEGEND;
        if (rep >= 90e18) return IxDEOCore.Tier.ORACLE;
        if (acc >= 0.8e18 && p.estimateCount >= 20) return IxDEOCore.Tier.SAGE;
        if (p.estimateCount >= 5) return IxDEOCore.Tier.ANALYST;
        return IxDEOCore.Tier.OBSERVER;
    }

    // --- soulbound enforcement (OZ v5 _update hook) --------------------------

    function _update(address to, uint256 tokenId, address auth)
        internal
        override
        returns (address)
    {
        address from = _ownerOf(tokenId);
        // Allow mint (from == 0) and burn (to == 0); block all transfers.
        if (from != address(0) && to != address(0)) revert Soulbound();
        return super._update(to, tokenId, auth);
    }

    function supportsInterface(bytes4 interfaceId)
        public
        view
        override(ERC721, AccessControl)
        returns (bool)
    {
        return super.supportsInterface(interfaceId);
    }
}
