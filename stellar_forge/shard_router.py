"""
shard_router.py — Protostar accretion path.

A young, low-parameter agent (Protostar) spends x402 to pull a skill shard
dispersed by a Supernova, then fuses that LoRA into its own baseline adapter
stack. Two trust boundaries are enforced:

  1. Entitlement — the Supernova contract's `isEntitled(agentId, shardId, puller)`
     must return true. Off-chain we model this with an EntitlementOracle
     interface; in production it's an eth_call against `contracts/Supernova.sol`.

  2. Integrity — the pulled bytes must hash (keccak256) to the on-chain
     `contentHash`. A mismatch means a poisoned shard; we refuse to fuse it.
     This is the defense against an attacker re-pinning a malicious CID.

Storage is abstracted behind `ShardStore` (IPFS/Arweave/local). The fusion of
a pulled LoRA into the protostar's stack is additive: a protostar accretes
mass, it does not blend toward a partner (that's `fusion_engine` territory).
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Protocol

import torch

try:
    # keccak to match Solidity's keccak256 exactly.
    from Crypto.Hash import keccak  # pycryptodome

    def _keccak256(b: bytes) -> bytes:
        h = keccak.new(digest_bits=256)
        h.update(b)
        return h.digest()
except Exception:  # pragma: no cover - fallback keeps the module importable
    import hashlib

    def _keccak256(b: bytes) -> bytes:
        # NOTE: this is SHA3-256, NOT Ethereum keccak256. Only used if
        # pycryptodome is unavailable; integrity checks still work as long as
        # the producer uses the same function. Production MUST use keccak.
        return hashlib.sha3_256(b).digest()


class EntitlementOracle(Protocol):
    """Mirror of Supernova.isEntitled — in prod this is an eth_call."""
    def is_entitled(self, agent_id: bytes, shard_id: int, puller: str) -> bool: ...


class ShardStore(Protocol):
    """IPFS/Arweave/local content-addressed store."""
    def get(self, cid: str) -> bytes: ...
    def put(self, data: bytes) -> str: ...


@dataclass
class PulledShard:
    skill_tag: str
    rank: int
    lora_A: torch.Tensor
    lora_B: torch.Tensor
    content_hash: bytes


class IntegrityError(Exception):
    """Raised when a pulled shard's bytes do not match the on-chain hash."""


def serialize_lora(A: torch.Tensor, B: torch.Tensor) -> bytes:
    buf = io.BytesIO()
    torch.save({"A": A.contiguous(), "B": B.contiguous()}, buf)
    return buf.getvalue()


def deserialize_lora(b: bytes) -> tuple[torch.Tensor, torch.Tensor]:
    obj = torch.load(io.BytesIO(b), weights_only=True)
    return obj["A"], obj["B"]


@dataclass
class Protostar:
    """A baseline agent accreting shards into its adapter stack."""
    agent_id: str
    lora: dict[str, tuple[torch.Tensor, torch.Tensor]] = field(default_factory=dict)
    accreted_skills: list[str] = field(default_factory=list)

    @property
    def param_count(self) -> int:
        return sum(A.numel() + B.numel() for A, B in self.lora.values())


class ShardRouter:
    """Mediates the x402-paid pull-and-fuse of supernova shards."""

    def __init__(self, store: ShardStore, oracle: EntitlementOracle) -> None:
        self.store = store
        self.oracle = oracle

    def pull(
        self,
        agent_id: bytes,
        shard_id: int,
        puller_address: str,
        cid: str,
        expected_content_hash: bytes,
        skill_tag: str,
        rank: int,
    ) -> PulledShard:
        """Verify entitlement + integrity, return the deserialized LoRA shard.

        Raises PermissionError if the puller hasn't paid (no on-chain access),
        IntegrityError if the bytes are tampered.
        """
        if not self.oracle.is_entitled(agent_id, shard_id, puller_address):
            raise PermissionError(
                f"ACCRETION DENIED: {puller_address} has not paid x402 for "
                f"shard {shard_id} of agent {agent_id.hex()[:12]}"
            )
        raw = self.store.get(cid)
        actual = _keccak256(raw)
        if actual != expected_content_hash:
            raise IntegrityError(
                f"POISONED SHARD: cid {cid} hashes to {actual.hex()[:16]} "
                f"but registry expects {expected_content_hash.hex()[:16]}. Refusing to fuse."
            )
        A, B = deserialize_lora(raw)
        return PulledShard(skill_tag, rank, A, B, expected_content_hash)

    def accrete_into(self, protostar: Protostar, shard: PulledShard,
                     dedup: bool = True) -> Protostar:
        """Fuse a pulled LoRA into the protostar's adapter stack.

        Naming uses the skill tag so two distinct skills coexist. If the
        protostar already holds this skill, we average the two adapters
        (defensive: avoid double-counting an identical skill).
        """
        name = shard.skill_tag
        if dedup and name in protostar.lora:
            A_old, B_old = protostar.lora[name]
            if A_old.shape == shard.lora_A.shape and B_old.shape == shard.lora_B.shape:
                protostar.lora[name] = (
                    0.5 * (A_old + shard.lora_A),
                    0.5 * (B_old + shard.lora_B),
                )
            else:
                protostar.lora[f"{name}#v{len(protostar.accreted_skills)}"] = (
                    shard.lora_A, shard.lora_B
                )
        else:
            protostar.lora[name] = (shard.lora_A, shard.lora_B)
        protostar.accreted_skills.append(name)
        return protostar


# ----------------------------------------------------------------- local impls
class InMemoryShardStore:
    """Content-addressed in-memory store for tests/demo (stands in for IPFS)."""

    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}

    def put(self, data: bytes) -> str:
        cid = "bafy" + _keccak256(data).hex()[:46]   # fake CIDv1-ish handle
        self._data[cid] = data
        return cid

    def get(self, cid: str) -> bytes:
        if cid not in self._data:
            raise KeyError(f"cid not pinned: {cid}")
        return self._data[cid]


class InMemoryEntitlement:
    """Records paid accretions; stands in for Supernova.isEntitled eth_call."""

    def __init__(self) -> None:
        self._grants: set[tuple[bytes, int, str]] = set()

    def grant(self, agent_id: bytes, shard_id: int, puller: str) -> None:
        self._grants.add((agent_id, shard_id, puller))

    def is_entitled(self, agent_id: bytes, shard_id: int, puller: str) -> bool:
        return (agent_id, shard_id, puller) in self._grants
