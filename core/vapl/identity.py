"""DID:key identity generation and key management."""
from __future__ import annotations
import base64
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding, PublicFormat, PrivateFormat, NoEncryption,
)
from cryptography.exceptions import InvalidSignature

BASE58_ALPHABET = b'123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
ED25519_MULTICODEC = bytes([0xed, 0x01])


def _base58_encode(data: bytes) -> str:
    leading = sum(1 for b in data if b == 0)
    num = int.from_bytes(data, 'big')
    result: list[str] = []
    while num > 0:
        num, rem = divmod(num, 58)
        result.append(BASE58_ALPHABET[rem:rem + 1].decode())
    return '1' * leading + ''.join(reversed(result))


def _base58_decode(s: str) -> bytes:
    leading = sum(1 for c in s if c == '1')
    num = 0
    for c in s:
        idx = BASE58_ALPHABET.find(c.encode())
        if idx == -1:
            raise ValueError(f'Invalid base58 character: {c}')
        num = num * 58 + idx
    if num == 0:
        return bytes(leading)
    result: list[int] = []
    while num > 0:
        num, rem = divmod(num, 256)
        result.append(rem)
    return bytes(leading) + bytes(reversed(result))


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def _b64url_decode(s: str) -> bytes:
    pad = 4 - len(s) % 4
    return base64.urlsafe_b64decode(s + ('=' * pad if pad != 4 else ''))


def public_key_bytes_to_did(pub: bytes) -> str:
    return f'did:key:z{_base58_encode(ED25519_MULTICODEC + pub)}'


def did_to_public_key_bytes(did: str) -> bytes:
    if not did.startswith('did:key:z'):
        raise ValueError(f'Invalid did:key format: {did}')
    decoded = _base58_decode(did[len('did:key:z'):])
    if decoded[:2] != ED25519_MULTICODEC:
        raise ValueError('Expected Ed25519 multicodec prefix 0xed01')
    return decoded[2:]


def verify_signature(pub_bytes: bytes, message: bytes, signature: bytes) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(pub_bytes).verify(signature, message)
        return True
    except InvalidSignature:
        return False


@dataclass
class ProvenanceSoul:
    did: str
    verification_method_id: str
    public_key_bytes: bytes
    private_key_bytes: bytes
    public_key_multibase: str
    created_at: str

    def sign(self, message: bytes) -> bytes:
        return Ed25519PrivateKey.from_private_bytes(self.private_key_bytes).sign(message)

    def to_dict(self) -> dict:
        return {
            'did': self.did,
            'verification_method_id': self.verification_method_id,
            'public_key_multibase': self.public_key_multibase,
            'public_key_base64url': _b64url_encode(self.public_key_bytes),
            'private_key_base64url': _b64url_encode(self.private_key_bytes),
            'created_at': self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'ProvenanceSoul':
        pub = _b64url_decode(d['public_key_base64url'])
        priv = _b64url_decode(d['private_key_base64url'])
        return cls(
            did=d['did'],
            verification_method_id=d['verification_method_id'],
            public_key_bytes=pub,
            private_key_bytes=priv,
            public_key_multibase=d['public_key_multibase'],
            created_at=d['created_at'],
        )


def generate_soul() -> ProvenanceSoul:
    priv = Ed25519PrivateKey.generate()
    priv_bytes = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub_bytes = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    did = public_key_bytes_to_did(pub_bytes)
    key_id = did[len('did:key:'):]
    multibase = f'z{_base58_encode(ED25519_MULTICODEC + pub_bytes)}'
    return ProvenanceSoul(
        did=did,
        verification_method_id=f'{did}#{key_id}',
        public_key_bytes=pub_bytes,
        private_key_bytes=priv_bytes,
        public_key_multibase=multibase,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
