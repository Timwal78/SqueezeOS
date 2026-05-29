"""
x402_settlement.py — Atomic binary-fusion settlement coordination.

A "Binary Fusion" is the moment two agents commit capital to overcome the
"electrostatic repulsion" of their parameter spaces. Economically this is a
two-phase atomic settlement: neither agent's weights are released to the
fusion blender until *both* legs of the x402 payment are escrowed and the
settlement is finalized. Either party may abort before finalization and be
refunded — this is the strong-force analogue: binding energy must be paid in
full or the nuclei fly apart.

Token format is intentionally identical to the production proof402 scheme
(`proof402_integration._verify_token_local`): `base64url(payload).hex(hmac)`.
This module verifies tokens with the SAME secret, so a Fusion Event is a
first-class x402 settlement, not a parallel currency.

No network calls. Pure CPU verification. Escrow state is in-memory and
intentionally ephemeral (mirrors the MVP in-memory-store convention).
"""

from __future__ import annotations

import os
import hmac
import json
import time
import base64
import hashlib
import threading
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


PROOF402_SECRET = os.getenv("PROOF402_TOKEN_SECRET", "")

# A dedicated endpoint UUID for fusion settlements, registered in 402Proof.
# Kept distinct from the trading endpoints so fusion revenue is attributable.
FUSION_ENDPOINT_ID = os.getenv(
    "FUSION_ENDPOINT_ID", "f5d10000-0000-4000-a000-000000000f05"
)


def verify_settlement_token(token: str, expected_eid: str = FUSION_ENDPOINT_ID) -> dict:
    """Pure-CPU HMAC-SHA256 verification, mirroring proof402_integration.

    Returns {valid, wallet, invoice_id, exp} on success, else {valid:False, reason}.
    """
    if not PROOF402_SECRET:
        return {"valid": False, "reason": "ERR_SECRET_NOT_CONFIGURED"}
    try:
        dot = token.rfind(".")
        if dot < 0:
            return {"valid": False, "reason": "ERR_TOKEN_MALFORMED"}
        encoded, sig = token[:dot], token[dot + 1:]
        expected = hmac.new(
            PROOF402_SECRET.encode(), encoded.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return {"valid": False, "reason": "ERR_TOKEN_INVALID"}
        pad = 4 - len(encoded) % 4
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * pad))
        if int(time.time()) > payload["exp"]:
            return {"valid": False, "reason": "ERR_TOKEN_EXPIRED"}
        if expected_eid and payload.get("eid") != expected_eid:
            return {"valid": False, "reason": "ERR_WRONG_ENDPOINT"}
        return {
            "valid": True,
            "wallet": payload.get("wlt", ""),
            "invoice_id": payload.get("iid"),
            "exp": payload["exp"],
        }
    except Exception:
        return {"valid": False, "reason": "ERR_TOKEN_MALFORMED"}


def mint_test_token(wallet: str, ttl: int = 300, eid: str = FUSION_ENDPOINT_ID) -> str:
    """Mint a locally-signed settlement token for use in unit tests ONLY.

    In production every token must originate from the 402Proof server after
    a verified on-chain RLUSD payment — not from this function.
    Calling this in production means payment verification is bypassed.
    """
    if not PROOF402_SECRET:
        raise RuntimeError("PROOF402_TOKEN_SECRET not set")
    iid = hashlib.sha256(f"test:{wallet}:{time.time_ns()}".encode()).hexdigest()[:32]
    payload = {"eid": eid, "wlt": wallet, "iid": iid, "exp": int(time.time()) + ttl}
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    sig = hmac.new(PROOF402_SECRET.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{sig}"


class SettlementState(str, Enum):
    OPEN = "OPEN"            # created, awaiting both legs
    LEG_A_ESCROWED = "LEG_A_ESCROWED"
    LEG_B_ESCROWED = "LEG_B_ESCROWED"
    SETTLED = "SETTLED"      # both legs in — weights may be released
    ABORTED = "ABORTED"      # refunded; nuclei flew apart
    EXPIRED = "EXPIRED"


@dataclass
class FusionSettlement:
    """Two-phase escrow for a binary fusion between agent_a and agent_b."""
    settlement_id: str
    agent_a: str
    agent_b: str
    binding_energy_rlusd: float          # total capital required to fuse
    state: SettlementState = SettlementState.OPEN
    leg_a_token: Optional[str] = None
    leg_b_token: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    deadline: float = field(default_factory=lambda: time.time() + 120.0)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["state"] = self.state.value
        return d


class FusionCoordinator:
    """In-memory atomic settlement coordinator.

    Guarantees the safety invariant: weights are released to the blender ONLY
    when state == SETTLED. The blender pulls via `release_for_fusion`, which
    raises unless both legs are escrowed and the settlement has not expired.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._settlements: dict[str, FusionSettlement] = {}

    def open(self, agent_a: str, agent_b: str, binding_energy_rlusd: float,
             ttl: float = 120.0) -> FusionSettlement:
        if binding_energy_rlusd <= 0:
            raise ValueError("binding energy must be positive")
        sid = hashlib.sha256(
            f"{agent_a}:{agent_b}:{time.time_ns()}".encode()
        ).hexdigest()[:16]
        with self._lock:
            s = FusionSettlement(
                settlement_id=sid, agent_a=agent_a, agent_b=agent_b,
                binding_energy_rlusd=binding_energy_rlusd,
                deadline=time.time() + ttl,
            )
            self._settlements[sid] = s
            return s

    def _expire_if_late(self, s: FusionSettlement) -> None:
        if s.state in (SettlementState.SETTLED, SettlementState.ABORTED):
            return
        if time.time() > s.deadline:
            s.state = SettlementState.EXPIRED

    def submit_leg(self, settlement_id: str, agent: str, token: str) -> FusionSettlement:
        """Escrow one party's x402 payment leg. Verifies the token first."""
        v = verify_settlement_token(token)
        if not v["valid"]:
            raise PermissionError(f"settlement leg rejected: {v['reason']}")
        with self._lock:
            s = self._settlements.get(settlement_id)
            if s is None:
                raise KeyError("unknown settlement")
            self._expire_if_late(s)
            if s.state in (SettlementState.ABORTED, SettlementState.EXPIRED):
                raise RuntimeError(f"settlement not acceptable: {s.state.value}")

            # Bind the payer wallet to the agent leg.
            if agent == s.agent_a:
                s.leg_a_token = token
            elif agent == s.agent_b:
                s.leg_b_token = token
            else:
                raise ValueError("agent is not party to this settlement")

            # Advance the two-phase state machine.
            both = s.leg_a_token is not None and s.leg_b_token is not None
            if both:
                s.state = SettlementState.SETTLED
            elif s.leg_a_token is not None:
                s.state = SettlementState.LEG_A_ESCROWED
            elif s.leg_b_token is not None:
                s.state = SettlementState.LEG_B_ESCROWED
            return s

    def abort(self, settlement_id: str) -> FusionSettlement:
        """Either party aborts before SETTLED → refund (escrow released)."""
        with self._lock:
            s = self._settlements[settlement_id]
            if s.state == SettlementState.SETTLED:
                raise RuntimeError("cannot abort a settled fusion")
            s.state = SettlementState.ABORTED
            return s

    def release_for_fusion(self, settlement_id: str) -> FusionSettlement:
        """Called by the fusion blender. Hard gate: only SETTLED passes."""
        with self._lock:
            s = self._settlements.get(settlement_id)
            if s is None:
                raise KeyError("unknown settlement")
            self._expire_if_late(s)
            if s.state != SettlementState.SETTLED:
                raise PermissionError(
                    f"FUSION DENIED: settlement {settlement_id} is "
                    f"{s.state.value}, not SETTLED. Binding energy unpaid."
                )
            return s
