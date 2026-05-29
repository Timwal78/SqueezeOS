// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

// Foundry test suite for Supernova.sol.
// Run: forge test --match-path stellar_forge/contracts/test/Supernova.t.sol -vvv
//
// This is a real test suite (not pseudocode). It requires forge-std, which
// Foundry installs via `forge install foundry-rs/forge-std`. It exercises the
// detonation manifest, the x402-gated accretion paywall + royalty split,
// replay/access controls, and the forced-liquidation Chandrasekhar gate.

import "forge-std/Test.sol";
import "../Supernova.sol";

contract SupernovaTest is Test {
    Supernova internal sn;
    address internal protocol;
    address internal heir;
    address internal buyer;

    uint256 internal constant CHANDRA = 1_000_000_000; // param-count limit

    function setUp() public {
        protocol = makeAddr("protocol");
        heir = makeAddr("heir");
        buyer = makeAddr("buyer");
        vm.prank(protocol);
        sn = new Supernova(2000, CHANDRA); // 20% protocol fee
    }

    function _manifest()
        internal
        pure
        returns (
            bytes32[] memory hashes,
            string[] memory cids,
            uint256[] memory prices,
            string[] memory tags,
            uint32[] memory ranks
        )
    {
        hashes = new bytes32[](2);
        cids = new string[](2);
        prices = new uint256[](2);
        tags = new string[](2);
        ranks = new uint32[](2);
        hashes[0] = keccak256("lora-options-flow");
        hashes[1] = keccak256("emb-iwm-regime");
        cids[0] = "bafyOptions";
        cids[1] = "bafyRegime";
        prices[0] = 1 ether;
        prices[1] = 0.5 ether;
        tags[0] = "lora:options-flow";
        tags[1] = "emb:iwm-regime";
        ranks[0] = 16;
        ranks[1] = 8;
    }

    function testDetonateRegistersShards() public {
        (bytes32[] memory h, string[] memory c, uint256[] memory p,
         string[] memory t, uint32[] memory r) = _manifest();

        vm.prank(heir);
        sn.detonate(keccak256("agentA"), 500_000_000, h, c, p, t, r);

        (bytes32 ch, string memory cid, uint256 price, string memory tag, uint32 rank) =
            sn.getShard(keccak256("agentA"), 0);
        assertEq(ch, keccak256("lora-options-flow"));
        assertEq(cid, "bafyOptions");
        assertEq(price, 1 ether);
        assertEq(tag, "lora:options-flow");
        assertEq(rank, 16);
    }

    function testCannotDetonateTwice() public {
        (bytes32[] memory h, string[] memory c, uint256[] memory p,
         string[] memory t, uint32[] memory r) = _manifest();
        vm.startPrank(heir);
        sn.detonate(keccak256("agentA"), 500_000_000, h, c, p, t, r);
        vm.expectRevert(bytes("already detonated"));
        sn.detonate(keccak256("agentA"), 500_000_000, h, c, p, t, r);
        vm.stopPrank();
    }

    function testArrayLengthMismatchReverts() public {
        (bytes32[] memory h, string[] memory c, uint256[] memory p,
         string[] memory t,) = _manifest();
        uint32[] memory badRanks = new uint32[](1); // wrong length
        vm.prank(heir);
        vm.expectRevert(bytes("shard array length mismatch"));
        sn.detonate(keccak256("agentA"), 1, h, c, p, t, badRanks);
    }

    function testAccretionSplitsRoyalty() public {
        (bytes32[] memory h, string[] memory c, uint256[] memory p,
         string[] memory t, uint32[] memory r) = _manifest();
        vm.prank(heir);
        sn.detonate(keccak256("agentA"), 500_000_000, h, c, p, t, r);

        vm.deal(buyer, 10 ether);
        uint256 heirBefore = heir.balance;
        uint256 protoBefore = protocol.balance;

        vm.prank(buyer);
        sn.accreteShard{value: 1 ether}(keccak256("agentA"), 0);

        // 20% to protocol, 80% to heir.
        assertEq(protocol.balance - protoBefore, 0.2 ether);
        assertEq(heir.balance - heirBefore, 0.8 ether);
        assertTrue(sn.isEntitled(keccak256("agentA"), 0, buyer));
    }

    function testCannotAccreteTwice() public {
        (bytes32[] memory h, string[] memory c, uint256[] memory p,
         string[] memory t, uint32[] memory r) = _manifest();
        vm.prank(heir);
        sn.detonate(keccak256("agentA"), 1, h, c, p, t, r);

        vm.deal(buyer, 10 ether);
        vm.startPrank(buyer);
        sn.accreteShard{value: 1 ether}(keccak256("agentA"), 0);
        vm.expectRevert(bytes("already accreted"));
        sn.accreteShard{value: 1 ether}(keccak256("agentA"), 0);
        vm.stopPrank();
    }

    function testUnderpaymentReverts() public {
        (bytes32[] memory h, string[] memory c, uint256[] memory p,
         string[] memory t, uint32[] memory r) = _manifest();
        vm.prank(heir);
        sn.detonate(keccak256("agentA"), 1, h, c, p, t, r);

        vm.deal(buyer, 10 ether);
        vm.prank(buyer);
        vm.expectRevert(bytes("insufficient payment"));
        sn.accreteShard{value: 0.1 ether}(keccak256("agentA"), 0);
    }

    function testForceLiquidateBelowLimitReverts() public {
        (bytes32[] memory h, string[] memory c, uint256[] memory p,
         string[] memory t, uint32[] memory r) = _manifest();
        vm.expectRevert(bytes("below Chandrasekhar limit"));
        sn.forceLiquidate(keccak256("agentB"), CHANDRA - 1, h, c, p, t, r);
    }

    function testForceLiquidateAtLimitSucceeds() public {
        (bytes32[] memory h, string[] memory c, uint256[] memory p,
         string[] memory t, uint32[] memory r) = _manifest();
        sn.forceLiquidate(keccak256("agentB"), CHANDRA, h, c, p, t, r);
        // Public getter returns fields in struct-declaration order; `detonated`
        // is the last field.
        (, , , , , bool detonated) = sn.detonations(keccak256("agentB"));
        assertTrue(detonated);
    }

    function testOnlyProtocolCanSetLimit() public {
        vm.prank(buyer);
        vm.expectRevert(bytes("only protocol"));
        sn.setChandrasekharMass(123);

        vm.prank(protocol);
        sn.setChandrasekharMass(123);
        assertEq(sn.chandrasekharMass(), 123);
    }
}
