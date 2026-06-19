"""Provenance Soul manifests and provider matching."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional

from .reputation import compute_reputation_score


def generate_provenance_soul_manifest(
    did: str,
    public_key_multibase: str,
    credentials: list[dict],
    capabilities: Optional[list[str]] = None,
    trusted_issuers: Optional[list[str]] = None,
) -> dict:
    score = compute_reputation_score(credentials, did, trusted_issuers=trusted_issuers)
    return {
        '@context': [
            'https://www.w3.org/ns/credentials/v2',
            'https://vapl.scriptmasterlabs.com/v1/context.jsonld',
        ],
        'id': f'{did}#soul',
        'type': 'ProvenanceSoul',
        'controller': did,
        'publicKeyMultibase': public_key_multibase,
        'reputationScore': score['overall'],
        'reputationComponents': score['components'],
        'credentialCount': score['credential_count'],
        'capabilities': capabilities or [],
        'updatedAt': datetime.now(timezone.utc).isoformat(),
    }


def match_providers(
    providers: list[dict],
    required_capability: Optional[str] = None,
    trusted_issuers: Optional[list[str]] = None,
) -> list[dict]:
    eligible = [
        p for p in providers
        if required_capability is None or required_capability in p.get('capabilities', [])
    ]
    results = []
    for p in eligible:
        score = compute_reputation_score(
            p.get('credentials', []), p['did'], trusted_issuers=trusted_issuers
        )
        results.append({
            'did': p['did'],
            'endpoint': p.get('endpoint'),
            'capabilities': p.get('capabilities', []),
            'reputation_score': score,
        })
    return sorted(results, key=lambda x: x['reputation_score']['overall'], reverse=True)
