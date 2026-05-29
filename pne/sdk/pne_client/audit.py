"""Merkle audit client — verify auction inclusion proofs."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

import httpx

from .exceptions import MerkleVerificationError


@dataclass
class ProofNode:
    sibling: str
    position: str  # "left" or "right"


@dataclass
class AuditProof:
    auction_id: str
    leaf: str
    path: list[ProofNode]
    root: str
    verified: bool


class AuditClient:
    def __init__(self, base_url: str, http_client: httpx.AsyncClient):
        self._base = base_url.rstrip("/")
        self._client = http_client

    async def get_merkle_root(self) -> dict:
        resp = await self._client.get(f"{self._base}/v1/audit/merkle-root")
        resp.raise_for_status()
        return resp.json()

    async def get_proof(self, auction_id: str) -> AuditProof:
        resp = await self._client.get(f"{self._base}/v1/audit/proof/{auction_id}")
        resp.raise_for_status()
        data = resp.json()

        path = [
            ProofNode(sibling=n["sibling"], position=n["position"])
            for n in data.get("path", [])
        ]

        return AuditProof(
            auction_id=data["auction_id"],
            leaf=data.get("leaf", ""),
            path=path,
            root=data.get("root", ""),
            verified=data.get("verified", False),
        )

    async def verify(self, auction_id: str) -> bool:
        try:
            proof = await self.get_proof(auction_id)
            if not proof.leaf or not proof.root:
                return False
            return _verify_proof(proof.leaf, proof.path, proof.root)
        except Exception as e:
            raise MerkleVerificationError(f"Proof verification failed: {e}") from e


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _decode_hash(h: str) -> bytes:
    stripped = h.removeprefix("sha256:").removeprefix("0x")
    return bytes.fromhex(stripped)


def _verify_proof(leaf: str, path: list[ProofNode], root: str) -> bool:
    current = _decode_hash(leaf)

    for node in path:
        sibling = _decode_hash(node.sibling)
        if node.position == "right":
            combined = current + sibling
        else:
            combined = sibling + current
        current = hashlib.sha256(combined).digest()

    computed_root = "0x" + current.hex()
    expected_root = root if root.startswith("0x") else "0x" + root.removeprefix("sha256:")
    return computed_root.lower() == expected_root.lower()
