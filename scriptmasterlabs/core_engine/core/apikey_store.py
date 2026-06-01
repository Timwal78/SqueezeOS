"""
SML API Key Store
=================
Lightweight key management. Source of truth is Stripe.
On startup: loads from disk file (if present).
On each key event: persists to disk + updates in-memory cache.
On restart after deploy: Stripe sync rebuilds the cache.

Storage: JSON file at API_KEYS_PATH env var (default /tmp/sml_keys.json)
"""

import os
import json
import secrets
import time
import logging
import threading
from typing import Optional, Dict

logger = logging.getLogger("SML-APIKeys")

_lock = threading.Lock()

# In-memory: {api_key: {plan, calls_used, calls_limit, subscription_id, email, created_at, active}}
_KEYS: Dict[str, dict] = {}

# ── Plans ─────────────────────────────────────────────────────────────────────

PLANS = {
    "dev": {
        "name":        "Dev Pack",
        "calls":       100,
        "price_cents": 900,
        "one_time":    True,
        "description": "100 calls · one-time · never expires",
    },
    "starter": {
        "name":        "Starter",
        "calls":       500,
        "price_cents": 2900,
        "one_time":    False,
        "description": "500 calls/month · reset on renewal",
    },
    "pro": {
        "name":        "Pro",
        "calls":       2000,
        "price_cents": 7900,
        "one_time":    False,
        "description": "2,000 calls/month · reset on renewal",
    },
}


# ── Key operations ─────────────────────────────────────────────────────────────

def generate_key() -> str:
    return f"sml_live_{secrets.token_hex(24)}"


def create_key(plan: str, email: str, subscription_id: str = "") -> str:
    key = generate_key()
    with _lock:
        _KEYS[key] = {
            "plan":            plan,
            "calls_used":      0,
            "calls_limit":     PLANS[plan]["calls"],
            "subscription_id": subscription_id,
            "email":           email,
            "created_at":      time.time(),
            "active":          True,
        }
    _persist()
    logger.info(f"[APIKeys] Created key plan={plan} email={email} sub={subscription_id}")
    return key


def validate_key(key: str) -> Optional[dict]:
    """Returns key info dict if valid and has remaining calls, else None."""
    with _lock:
        info = _KEYS.get(key)
    if not info:
        return None
    if not info.get("active"):
        return None
    if info["calls_used"] >= info["calls_limit"]:
        return None
    return info


def consume_call(key: str) -> bool:
    """Increment usage counter. Returns True if call is allowed."""
    with _lock:
        info = _KEYS.get(key)
        if not info or not info.get("active"):
            return False
        if info["calls_used"] >= info["calls_limit"]:
            return False
        info["calls_used"] += 1
    _persist()
    return True


def deactivate_by_subscription(sub_id: str):
    with _lock:
        for info in _KEYS.values():
            if info.get("subscription_id") == sub_id:
                info["active"] = False
    _persist()
    logger.info(f"[APIKeys] Deactivated key for subscription {sub_id}")


def reset_quota_by_subscription(sub_id: str):
    with _lock:
        for info in _KEYS.values():
            if info.get("subscription_id") == sub_id:
                info["calls_used"] = 0
                info["active"] = True
    _persist()
    logger.info(f"[APIKeys] Reset quota for subscription {sub_id}")


def find_key_by_subscription(sub_id: str) -> Optional[str]:
    with _lock:
        for k, v in _KEYS.items():
            if v.get("subscription_id") == str(sub_id):
                return k
    return None


# ── Persistence ───────────────────────────────────────────────────────────────

def _get_path() -> str:
    return os.environ.get("API_KEYS_PATH", "/tmp/sml_keys.json")


def _persist():
    path = _get_path()
    try:
        with _lock:
            data = dict(_KEYS)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.warning(f"[APIKeys] Persist failed: {e}")


def load_from_disk():
    global _KEYS
    path = _get_path()
    try:
        with open(path) as f:
            data = json.load(f)
        with _lock:
            _KEYS.update(data)
        logger.info(f"[APIKeys] Loaded {len(data)} keys from {path}")
    except FileNotFoundError:
        logger.info("[APIKeys] No key file — starting fresh (will sync from Stripe if configured)")
    except Exception as e:
        logger.warning(f"[APIKeys] Load failed: {e}")


def sync_from_stripe():
    """
    On startup: pull all active Stripe subscriptions and one-time payments,
    rebuild any missing keys. Ensures keys survive Render redeploys.
    """
    import stripe as _stripe
    stripe_key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not stripe_key:
        return
    _stripe.api_key = stripe_key

    price_map = {
        os.environ.get("STRIPE_PRICE_DEV",     ""): "dev",
        os.environ.get("STRIPE_PRICE_STARTER", ""): "starter",
        os.environ.get("STRIPE_PRICE_PRO",     ""): "pro",
    }
    price_map.pop("", None)

    try:
        # Active subscriptions
        subs = _stripe.Subscription.list(status="active", limit=100)
        for sub in subs.auto_paging_iter():
            sub_id = sub["id"]
            price_id = sub["items"]["data"][0]["price"]["id"] if sub["items"]["data"] else ""
            plan = price_map.get(price_id, "starter")
            email = ""
            try:
                cust = _stripe.Customer.retrieve(sub["customer"])
                email = cust.get("email", "")
            except Exception:
                pass
            existing = find_key_by_subscription(sub_id)
            if not existing:
                key = create_key(plan, email, sub_id)
                logger.info(f"[APIKeys] Stripe sync: recreated key for sub {sub_id}")
        logger.info("[APIKeys] Stripe sync complete")
    except Exception as e:
        logger.warning(f"[APIKeys] Stripe sync failed: {e}")
