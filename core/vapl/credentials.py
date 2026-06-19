"""VC issuance and verification."""
from __future__ import annotations
import hashlib
import json
import secrets
import base64
from datetime import datetime, timezone, timedelta
from typing import Optional

from .identity import ProvenanceSoul, did_to_public_key_bytes, verify_signature

VAPL_CONTEXT = 'https://vapl.scriptmasterlabs.com/v1/context.jsonld'
VC_CONTEXT_V2 = 'https://www.w3.org/ns/credentials/v2'
CLOCK_SKEW = timedelta(seconds=300)


def _canonical_json(obj: object) -> str:
    if not isinstance(obj, (dict, list)):
        return json.dumps(obj)
    if isinstance(obj, list):
        return '[' + ','.join(_canonical_json(i) for i in obj) + ']'
    return '{' + ','.join(
        f'{json.dumps(k)}:{_canonical_json(obj[k])}'
        for k in sorted(obj.keys())
    ) + '}'


def _nonce(n: int = 16) -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(n)).rstrip(b'=').decode()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _b64url_decode(s: str) -> bytes:
    pad = 4 - len(s) % 4
    return base64.urlsafe_b64decode(s + ('=' * pad if pad != 4 else ''))


def issue_vc(
    soul: ProvenanceSoul,
    subject_did: str,
    credential_type: str,
    claim: dict,
    validity_seconds: int = 86400 * 365,
) -> dict:
    now = datetime.now(timezone.utc)
    uid = f'urn:vapl:vc:{soul.did[-8:]}:{int(now.timestamp())}:{_nonce(6)}'
    valid_until = (now + timedelta(seconds=validity_seconds)).isoformat().replace('+00:00', 'Z')

    body: dict = {
        '@context': [VC_CONTEXT_V2, VAPL_CONTEXT],
        'id': uid,
        'type': ['VerifiableCredential', credential_type],
        'issuer': soul.did,
        'validFrom': now.isoformat().replace('+00:00', 'Z'),
        'validUntil': valid_until,
        'credentialSubject': {'id': subject_did, **claim},
    }

    digest = hashlib.sha256(_canonical_json(body).encode()).digest()
    sig = soul.sign(digest)
    proof_value = base64.urlsafe_b64encode(sig).rstrip(b'=').decode()

    body['proof'] = {
        'type': 'DataIntegrityProof',
        'cryptosuite': 'eddsa-vapl-2024',
        'created': _now(),
        'verificationMethod': soul.verification_method_id,
        'proofPurpose': 'assertionMethod',
        'nonce': _nonce(),
        'proofValue': proof_value,
    }
    return body


def issue_interaction_vc(
    soul: ProvenanceSoul,
    subject_did: str,
    interaction_type: str,
    resource: str,
    outcome: str,
    payment_tx_hash: Optional[str] = None,
    payment_amount: Optional[str] = None,
    payment_currency: Optional[str] = None,
    outcome_hash: Optional[str] = None,
    verifiable_accuracy: Optional[float] = None,
) -> dict:
    claim: dict = {
        'interaction': {
            'type': interaction_type,
            'resource': resource,
            'timestamp': _now(),
            'outcome': outcome,
            'nonce': _nonce(8),
            **({'paymentTxHash': payment_tx_hash} if payment_tx_hash else {}),
            **({'paymentAmount': payment_amount} if payment_amount else {}),
            **({'paymentCurrency': payment_currency} if payment_currency else {}),
            **({'outcomeHash': outcome_hash} if outcome_hash else {}),
            **({'verifiableAccuracy': verifiable_accuracy} if verifiable_accuracy is not None else {}),
        }
    }
    return issue_vc(soul, subject_did, 'InteractionCredential', claim)


def issue_accuracy_vc(
    soul: ProvenanceSoul,
    subject_did: str,
    prediction_id: str,
    prediction_timestamp: str,
    prediction_value: str,
    verification_source: str,
    actual_value: str,
    accuracy_score: float,
    methodology: str,
) -> dict:
    claim = {
        'accuracy': {
            'predictionId': prediction_id,
            'predictionTimestamp': prediction_timestamp,
            'predictionValue': prediction_value,
            'verificationTimestamp': _now(),
            'verificationSource': verification_source,
            'actualValue': actual_value,
            'accuracyScore': accuracy_score,
            'methodology': methodology,
            'nonce': _nonce(8),
        }
    }
    return issue_vc(soul, subject_did, 'AccuracyCredential', claim)


def issue_contribution_vc(
    soul: ProvenanceSoul,
    subject_did: str,
    contribution_type: str,
    resource_id: str,
    consumers: Optional[int] = None,
    revenue_earned: Optional[str] = None,
) -> dict:
    claim: dict = {
        'contribution': {
            'contributionType': contribution_type,
            'resourceId': resource_id,
            'timestamp': _now(),
            'nonce': _nonce(8),
            **({'consumers': consumers} if consumers is not None else {}),
            **({'revenueEarned': revenue_earned} if revenue_earned else {}),
        }
    }
    return issue_vc(soul, subject_did, 'ContributionCredential', claim)


def verify_vc(
    credential: dict,
    trusted_issuers: Optional[list[str]] = None,
    check_expiry: bool = True,
    now: Optional[datetime] = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    errors: list[str] = []
    warnings: list[str] = []

    ctx = credential.get('@context', [])
    if VC_CONTEXT_V2 not in ctx:
        errors.append('Missing W3C VC v2 context')
    if 'VerifiableCredential' not in credential.get('type', []):
        errors.append('Missing VerifiableCredential type')
    if not credential.get('issuer'):
        errors.append('Missing issuer')
    if not credential.get('proof'):
        errors.append('Missing proof')
    if not credential.get('credentialSubject', {}).get('id'):
        errors.append('Missing credentialSubject.id')

    if errors:
        return {'valid': False, 'errors': errors, 'warnings': warnings, 'verified_at': now.isoformat()}

    issuer: str = credential['issuer']

    if trusted_issuers is not None and issuer not in trusted_issuers:
        errors.append(f'Issuer {issuer} is not in trusted issuers list')
    if not issuer.startswith('did:key:'):
        errors.append('Issuer must be a did:key DID')

    proof = credential['proof']
    if proof.get('type') != 'DataIntegrityProof':
        errors.append(f"Unsupported proof type: {proof.get('type')}")
    if proof.get('cryptosuite') != 'eddsa-vapl-2024':
        errors.append(f"Unsupported cryptosuite: {proof.get('cryptosuite')}")
    if proof.get('proofPurpose') != 'assertionMethod':
        errors.append(f"Unexpected proofPurpose: {proof.get('proofPurpose')}")
    if not proof.get('verificationMethod', '').startswith(issuer):
        errors.append('Verification method does not match issuer DID')

    if errors:
        return {'valid': False, 'errors': errors, 'warnings': warnings, 'verified_at': now.isoformat()}

    if check_expiry:
        vf = datetime.fromisoformat(credential['validFrom'].replace('Z', '+00:00'))
        if vf > now + CLOCK_SKEW:
            errors.append(f"Credential not yet valid (validFrom: {credential['validFrom']})")
        if 'validUntil' in credential:
            vu = datetime.fromisoformat(credential['validUntil'].replace('Z', '+00:00'))
            if vu < now - CLOCK_SKEW:
                errors.append(f"Credential expired (validUntil: {credential['validUntil']})")

    if errors:
        return {'valid': False, 'errors': errors, 'warnings': warnings, 'verified_at': now.isoformat()}

    try:
        pub = did_to_public_key_bytes(issuer)
        body = {k: v for k, v in credential.items() if k != 'proof'}
        digest = hashlib.sha256(_canonical_json(body).encode()).digest()
        sig = _b64url_decode(proof['proofValue'])
        if not verify_signature(pub, digest, sig):
            errors.append('Invalid signature: credential has been tampered with')
    except Exception as e:
        errors.append(f'Signature verification error: {e}')

    valid = not errors
    return {
        'valid': valid,
        'credential': credential if valid else None,
        'errors': errors,
        'warnings': warnings,
        'issuer_did': issuer,
        'subject_did': credential['credentialSubject']['id'],
        'verified_at': now.isoformat(),
    }
