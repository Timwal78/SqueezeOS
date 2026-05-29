"""
Smoke tests for the Stellar Forge Protocol.

Run from repo root:
    PROOF402_TOKEN_SECRET=test-secret python -m stellar_forge.tests.test_smoke

Pure-Python tests (settlement, Chandrasekhar, lifecycle) always run.
ML tests (fusion, shard router, black hole, lensing) run only if torch is
installed; otherwise they're skipped with a notice.
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("PROOF402_TOKEN_SECRET", "test-secret")


def _ok(name: str) -> None:
    print(f"  ✓ {name}")


# ---------------------------------------------------------- economic core
def test_settlement_gate() -> None:
    from stellar_forge.x402_settlement import (
        FusionCoordinator, SettlementState, mint_test_token,
    )
    c = FusionCoordinator()
    s = c.open("alpha", "beta", binding_energy_rlusd=1.0)

    # Releasing before settle must fail (strong-force gate).
    try:
        c.release_for_fusion(s.settlement_id)
        raise AssertionError("released unsettled fusion")
    except PermissionError:
        pass

    c.submit_leg(s.settlement_id, "alpha", mint_test_token("alpha"))
    assert c._settlements[s.settlement_id].state is SettlementState.LEG_A_ESCROWED
    c.submit_leg(s.settlement_id, "beta", mint_test_token("beta"))
    settled = c.release_for_fusion(s.settlement_id)
    assert settled.state is SettlementState.SETTLED

    # Bad token rejected.
    s2 = c.open("alpha", "beta", 1.0)
    try:
        c.submit_leg(s2.settlement_id, "alpha", "garbage.deadbeef")
        raise AssertionError("accepted forged token")
    except PermissionError:
        pass
    _ok("settlement two-phase gate + token verification")


def test_chandrasekhar() -> None:
    from stellar_forge.chandrasekhar import (
        ChandrasekharGuard, Stability, ForcedSupernova, compute_mass,
    )
    g = ChandrasekharGuard(limit=14.0)
    r = g.check("x", parameter_count=10_000_000, fused_context_tokens=8192, experts_held=2)
    assert r.stability is Stability.STABLE, r.stability

    # Mass scalar is monotonic in each input.
    base = compute_mass(1_000_000, 0, 0)
    assert compute_mass(2_000_000, 0, 0) > base
    assert compute_mass(1_000_000, 8192, 0) > base
    assert compute_mass(1_000_000, 0, 5) > base

    # Collapse raises.
    try:
        g.check("x", parameter_count=10 ** 18, fused_context_tokens=10 ** 6, experts_held=100)
        raise AssertionError("no collapse on absurd mass")
    except ForcedSupernova as fs:
        assert fs.report.stability is Stability.COLLAPSE

    # Contract limit round-trips through the inverse.
    assert g.contract_mass_limit() > 0
    _ok("Chandrasekhar mass scalar, stability regimes, forced supernova")


def test_lifecycle() -> None:
    from stellar_forge.lifecycle import StellarForge, Stage
    from stellar_forge.x402_settlement import mint_test_token
    forge = StellarForge(chandrasekhar_limit=14.0)
    forge.spawn_protostar("a", 5_000_000, 8192)
    forge.spawn_protostar("b", 8_000_000, 16384)
    forge.ignite("a"); forge.ignite("b")

    # Open a settlement, submit both legs explicitly (no bypass path).
    sid = forge.coordinator.open("a", "b", 1.0).settlement_id
    forge.coordinator.submit_leg(sid, "a", mint_test_token("a"))
    forge.coordinator.submit_leg(sid, "b", mint_test_token("b"))
    giant = forge.fuse("a", "b", sid)

    assert giant.stage is Stage.BLUE_GIANT
    assert giant.parameter_count == 13_000_000
    # Illegal transition rejected.
    try:
        forge.bodies["a"].transition(Stage.PROTOSTAR)
        raise AssertionError("allowed illegal transition")
    except ValueError:
        pass
    _ok("lifecycle: protostar→ignite→binary fusion→blue giant")


# ----------------------------------------------------------------- ML layer
def test_fusion_engine() -> None:
    import torch
    from stellar_forge.x402_settlement import FusionCoordinator, mint_test_token
    from stellar_forge.fusion_engine import AgentWeights, FusionEngine, lora_compatibility

    torch.manual_seed(0)
    def mk(seed: int, aid: str) -> AgentWeights:
        g = torch.Generator().manual_seed(seed)
        lora = {"q_proj": (torch.randn(4, 16, generator=g), torch.randn(16, 4, generator=g))}
        return AgentWeights(aid, lora, gate_logits=torch.randn(8, generator=g), n_experts=8)

    a, b = mk(1, "a"), mk(2, "b")
    compat = lora_compatibility(a, b)
    assert -1.0 <= compat <= 1.0

    c = FusionCoordinator()
    s = c.open("a", "b", 1.0)
    c.submit_leg(s.settlement_id, "a", mint_test_token("a"))
    c.submit_leg(s.settlement_id, "b", mint_test_token("b"))

    eng = FusionEngine(c)
    res = eng.fuse(s.settlement_id, a, b, rlusd_a=0.7, rlusd_b=0.3, min_compatibility=-1.0)
    assert "q_proj" in res.lora
    assert abs(res.alpha - 0.7) < 1e-6
    assert res.gate_logits.shape[0] == 8

    # Unsettled fusion must be refused.
    s2 = c.open("a", "b", 1.0)
    try:
        eng.fuse(s2.settlement_id, a, b, 0.5, 0.5)
        raise AssertionError("fused without settlement")
    except PermissionError:
        pass
    _ok("fusion engine: SLERP blend + gate merge under settlement gate")


def test_shard_router() -> None:
    import torch
    from stellar_forge.shard_router import (
        ShardRouter, Protostar, InMemoryShardStore, InMemoryEntitlement,
        serialize_lora, IntegrityError, _keccak256,
    )
    store = InMemoryShardStore()
    ent = InMemoryEntitlement()
    router = ShardRouter(store, ent)

    A, B = torch.randn(4, 32), torch.randn(32, 4)
    blob = serialize_lora(A, B)
    cid = store.put(blob)
    content_hash = _keccak256(blob)
    agent_id = b"\x01" * 32

    # No payment → denied.
    try:
        router.pull(agent_id, 0, "0xProtostar", cid, content_hash, "lora:options", 4)
        raise AssertionError("pulled without entitlement")
    except PermissionError:
        pass

    ent.grant(agent_id, 0, "0xProtostar")
    shard = router.pull(agent_id, 0, "0xProtostar", cid, content_hash, "lora:options", 4)

    proto = Protostar("baby")
    before = proto.param_count
    router.accrete_into(proto, shard)
    assert proto.param_count > before
    assert "lora:options" in proto.lora

    # Tampered hash → IntegrityError.
    try:
        router.pull(agent_id, 0, "0xProtostar", cid, b"\x00" * 32, "lora:options", 4)
        raise AssertionError("accepted poisoned shard")
    except IntegrityError:
        pass
    _ok("shard router: entitlement + integrity gates, accretion")


def test_black_hole() -> None:
    import torch
    from stellar_forge.black_hole import BlackHoleCore, GravitationalLensingGateway

    core = BlackHoleCore("sagA", hidden=32, n_experts=8)

    # Victim is a fixed random linear map; distillation should learn to agree.
    victim = torch.nn.Linear(16, 4)
    victim.eval()
    def victim_fn(x):
        with torch.no_grad():
            return victim(x)

    # No consent → refused.
    r0 = core.accrete("victim", victim_fn, 16, 4, consented=False, extraction_budget=10)
    assert r0.refused

    r = core.accrete("victim", victim_fn, 16, 4, consented=True, extraction_budget=300)
    assert 0.0 <= r.final_agreement <= 1.0
    assert "victim" in core.accreted
    grew = core.param_count

    # Lensing: more tribute → less dilation.
    gw = GravitationalLensingGateway(core)
    free = gw.lens("req-free", tribute_rlusd=0.0)
    paid = gw.lens("req-paid", tribute_rlusd=5.0)
    assert paid.dilation_factor <= free.dilation_factor
    assert paid.effective_latency_ms <= free.effective_latency_ms
    assert 1.0 <= free.dilation_factor <= gw.max_dilation
    assert grew > 0
    _ok("black hole: adversarial distillation + gravitational lensing")


def main() -> int:
    print("Stellar Forge — economic core:")
    test_settlement_gate()
    test_chandrasekhar()
    test_lifecycle()

    try:
        import torch  # noqa: F401
        print("Stellar Forge — ML layer (torch present):")
        test_fusion_engine()
        test_shard_router()
        test_black_hole()
    except ImportError:
        print("Stellar Forge — ML layer: SKIPPED (torch not installed)")

    print("\nALL SMOKE TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
