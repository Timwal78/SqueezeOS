"""Singleton ProvenanceSoul for the SqueezeOS service identity.

Loads from VAPL_SOUL_FILE on startup. Generates + persists a new soul if the
file is absent. The soul never changes for the lifetime of the process; key
bytes are never transmitted in API responses.
"""
from __future__ import annotations

import json
import logging
import os
import threading

from .identity import ProvenanceSoul, generate_soul, soul_from_private_key_b64

log = logging.getLogger("vapl.soul")
_lock = threading.Lock()
_soul: ProvenanceSoul | None = None


def _soul_path() -> str:
    return os.environ.get("VAPL_SOUL_FILE", "/tmp/vapl_soul.json")


def _load_or_generate() -> ProvenanceSoul:
    # Env var takes priority — this is the ONLY thing that survives a Render
    # redeploy. VAPL_SOUL_FILE's default (/tmp/vapl_soul.json) lives on an
    # ephemeral filesystem: every container restart wipes it, so without this
    # env var a brand new identity (and DID) was silently generated on every
    # single deploy, orphaning any prior notarized history or reputation tied
    # to the old DID — defeating the entire point of a persistent identity.
    key_b64 = os.environ.get("VAPL_SOUL_PRIVATE_KEY_B64", "")
    if key_b64:
        try:
            soul = soul_from_private_key_b64(key_b64)
            log.info("[VAPL] Soul reconstructed from VAPL_SOUL_PRIVATE_KEY_B64  DID=%s", soul.did)
            return soul
        except Exception as exc:
            log.error("[VAPL] VAPL_SOUL_PRIVATE_KEY_B64 is set but invalid: %s — falling back to file/ephemeral mode", exc)

    path = _soul_path()
    if os.path.exists(path):
        try:
            with open(path) as f:
                soul = ProvenanceSoul.from_dict(json.load(f))
            log.info("[VAPL] Soul loaded from %s  DID=%s", path, soul.did)
            return soul
        except Exception as exc:
            log.warning("[VAPL] Failed to load soul from %s: %s — generating new soul", path, exc)

    soul = generate_soul()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(path) else None
        with open(path, "w") as f:
            json.dump(soul.to_dict(), f, indent=2)
    except Exception as exc:
        log.warning("[VAPL] Could not persist soul to %s: %s (ephemeral mode)", path, exc)

    log.warning(
        "[VAPL] New soul generated  DID=%s — this identity is EPHEMERAL and will be "
        "regenerated on the next deploy/restart unless you set VAPL_SOUL_PRIVATE_KEY_B64 "
        "in Render to this value: %s",
        soul.did, _b64url_encode_for_log(soul.private_key_bytes),
    )
    return soul


def _b64url_encode_for_log(raw: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def get_soul() -> ProvenanceSoul:
    """Return the SqueezeOS service ProvenanceSoul (thread-safe, singleton)."""
    global _soul
    if _soul is None:
        with _lock:
            if _soul is None:
                _soul = _load_or_generate()
    return _soul
