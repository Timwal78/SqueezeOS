"""
Stellar Forge Protocol — Agent Nucleosynthesis via x402.

Speculative R&D module. Self-contained; does NOT import from or mutate the
live SqueezeOS trading system under `core/`. See README.md for the honest
scope statement on what is real mechanism vs. metaphor.
"""

# Pure-Python economic core — no third-party deps. Always available.
from .x402_settlement import (
    FusionCoordinator,
    FusionSettlement,
    SettlementState,
    verify_settlement_token,
)
from .chandrasekhar import (
    ChandrasekharGuard,
    Stability,
    ForcedSupernova,
    MassReport,
    compute_mass,
)
from .lifecycle import StellarForge, Body, Stage

__all__ = [
    "FusionCoordinator", "FusionSettlement", "SettlementState",
    "verify_settlement_token",
    "ChandrasekharGuard", "Stability", "ForcedSupernova", "MassReport", "compute_mass",
    "StellarForge", "Body", "Stage",
]

# ML layer — requires torch. Import lazily so the economic core stays usable
# (and the lifecycle demo runs) in environments without a torch install.
try:
    from .fusion_engine import (
        AgentWeights, FusionEngine, FusionResult, lora_compatibility,
    )
    from .shard_router import (
        ShardRouter, Protostar, PulledShard,
        InMemoryShardStore, InMemoryEntitlement, IntegrityError,
    )
    from .black_hole import (
        BlackHoleCore, GravitationalLensingGateway, DistillationReport, LensedRequest,
    )
    __all__ += [
        "AgentWeights", "FusionEngine", "FusionResult", "lora_compatibility",
        "ShardRouter", "Protostar", "PulledShard", "InMemoryShardStore",
        "InMemoryEntitlement", "IntegrityError",
        "BlackHoleCore", "GravitationalLensingGateway",
        "DistillationReport", "LensedRequest",
    ]
    TORCH_AVAILABLE = True
except ImportError:  # torch not installed — economic core still works
    TORCH_AVAILABLE = False

__version__ = "0.1.0"
