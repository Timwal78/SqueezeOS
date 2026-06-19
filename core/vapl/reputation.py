"""Reputation score computation."""
from __future__ import annotations
import math
from datetime import datetime, timezone
from typing import Optional

from .credentials import verify_vc

DEFAULT_WEIGHTS = {'accuracy': 0.40, 'reliability': 0.30, 'contribution': 0.20, 'tenure': 0.10}
CONTRIBUTION_TYPE_WEIGHTS = {
    'MarketplaceListing': 1.0, 'DataContribution': 1.5,
    'RelayNode': 2.0, 'AlphaMeshNode': 2.0,
}


def _decay(timestamp: str, now: datetime, half_life_days: float) -> float:
    ts = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    age_days = (now - ts).total_seconds() / 86400
    return 0.5 ** (age_days / half_life_days)


def compute_reputation_score(
    credentials: list[dict],
    subject_did: str,
    trusted_issuers: Optional[list[str]] = None,
    weights: Optional[dict[str, float]] = None,
    decay_half_life_days: float = 30.0,
    now: Optional[datetime] = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    total_w = sum(w.values())
    nw = {k: v / total_w for k, v in w.items()}

    valid_vcs, invalid_count = [], 0
    for cred in credentials:
        r = verify_vc(cred, trusted_issuers=trusted_issuers, check_expiry=False, now=now)
        (valid_vcs if r['valid'] else []).append(cred) if r['valid'] else None
        if not r['valid']:
            invalid_count += 1
        else:
            valid_vcs.append(cred)

    # deduplicate
    seen, deduped = set(), []
    for vc in valid_vcs:
        if vc.get('id') not in seen:
            seen.add(vc.get('id'))
            deduped.append(vc)
    valid_vcs = deduped

    subject_vcs = [v for v in valid_vcs if v.get('credentialSubject', {}).get('id') == subject_did]

    interactions, accuracy_claims, contributions = [], [], []
    first_seen = last_seen = None

    for vc in subject_vcs:
        ts = datetime.fromisoformat(vc['validFrom'].replace('Z', '+00:00'))
        if first_seen is None or ts < first_seen:
            first_seen = ts
        if last_seen is None or ts > last_seen:
            last_seen = ts
        subj = vc.get('credentialSubject', {})
        if 'interaction' in subj:
            interactions.append({'claim': subj['interaction'], 'timestamp': vc['validFrom']})
        if 'accuracy' in subj:
            accuracy_claims.append(subj['accuracy'])
        if 'contribution' in subj:
            contributions.append(subj['contribution'])

    accuracy_score = (
        sum(min(1.0, max(0.0, c.get('accuracyScore', 0))) for c in accuracy_claims) / len(accuracy_claims)
        if accuracy_claims else 0.0
    )

    reliability_score = 0.0
    if interactions:
        ws, wt = 0.0, 0.0
        for item in interactions:
            d = _decay(item['timestamp'], now, decay_half_life_days)
            outcome = item['claim'].get('outcome', 'failure')
            s = 1.0 if outcome == 'success' else (0.5 if outcome == 'partial' else 0.0)
            ws += d * s
            wt += d
        reliability_score = ws / wt if wt > 0 else 0.0

    contribution_score = 0.0
    if contributions:
        weighted = sum(CONTRIBUTION_TYPE_WEIGHTS.get(c.get('contributionType', ''), 1.0) for c in contributions)
        contribution_score = min(1.0, math.log10(1 + weighted) / 2)

    tenure_score = 0.0
    if first_seen:
        age_days = (now - first_seen).total_seconds() / 86400
        tenure_score = min(1.0, math.log(1 + age_days) / math.log(366))

    overall = (
        nw['accuracy'] * accuracy_score +
        nw['reliability'] * reliability_score +
        nw['contribution'] * contribution_score +
        nw['tenure'] * tenure_score
    )

    def r3(x: float) -> float:
        return round(x, 3)

    return {
        'overall': r3(overall),
        'components': {
            'accuracy': r3(accuracy_score),
            'reliability': r3(reliability_score),
            'contribution': r3(contribution_score),
            'tenure': r3(tenure_score),
        },
        'evidence': {
            'total_interactions': len(interactions),
            'successful_interactions': sum(1 for i in interactions if i['claim'].get('outcome') == 'success'),
            'verified_predictions': len(accuracy_claims),
            'accurate_predictions': sum(1 for c in accuracy_claims if c.get('accuracyScore', 0) >= 0.7),
            'contributions': len(contributions),
            'first_seen_timestamp': first_seen.isoformat() if first_seen else None,
            'last_seen_timestamp': last_seen.isoformat() if last_seen else None,
        },
        'computed_at': now.isoformat(),
        'credential_count': len(credentials),
        'invalid_credentials': invalid_count,
    }


def rank_agents(
    agents: list[dict],
    trusted_issuers: Optional[list[str]] = None,
    **kwargs,
) -> list[dict]:
    results = [
        {'did': a['did'], 'score': compute_reputation_score(
            a.get('credentials', []), a['did'],
            trusted_issuers=trusted_issuers, **kwargs,
        )}
        for a in agents
    ]
    return sorted(results, key=lambda x: x['score']['overall'], reverse=True)
