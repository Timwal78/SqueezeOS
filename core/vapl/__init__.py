"""VAPL — Verifiable Agent Provenance Layer embedded in SqueezeOS.

Inline copy of vapl-py (github.com/timwal78/SML_Portfolio, vapl/py-sdk).
No external package dependency needed — ships with the service.
"""
from .identity import ProvenanceSoul, generate_soul, public_key_bytes_to_did, did_to_public_key_bytes
from .credentials import (
    issue_vc, issue_interaction_vc, issue_accuracy_vc, issue_contribution_vc, verify_vc,
)
from .reputation import compute_reputation_score
from .discovery import generate_provenance_soul_manifest
from .soul_manager import get_soul

__all__ = [
    "ProvenanceSoul", "generate_soul", "public_key_bytes_to_did", "did_to_public_key_bytes",
    "issue_vc", "issue_interaction_vc", "issue_accuracy_vc", "issue_contribution_vc", "verify_vc",
    "compute_reputation_score", "generate_provenance_soul_manifest", "get_soul",
]
