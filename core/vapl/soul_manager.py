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

from .identity import ProvenanceSoul, generate_soul

log = logging.getLogger("vapl.soul")
_lock = threading.Lock()
_soul: ProvenanceSoul | None = None


def _soul_path() -> str:
    return os.environ.get("VAPL_SOUL_FILE", "/tmp/vapl_soul.json")


def _load_or_generate() -> ProvenanceSoul:
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
        log.info("[VAPL] New soul generated and saved to %s  DID=%s", path, soul.did)
    except Exception as exc:
        log.warning("[VAPL] Could not persist soul to %s: %s (ephemeral mode)", path, exc)
    return soul


def get_soul() -> ProvenanceSoul:
    """Return the SqueezeOS service ProvenanceSoul (thread-safe, singleton)."""
    global _soul
    if _soul is None:
        with _lock:
            if _soul is None:
                _soul = _load_or_generate()
    return _soul
