"""Temporary debug blueprint — remove after forge is fixed."""
import os, traceback, logging
from flask import Blueprint, jsonify

forge_debug_bp = Blueprint("forge_debug", __name__)
logger = logging.getLogger("ForgeDebug")

@forge_debug_bp.route("/forge-debug", methods=["GET"])
def forge_debug():
    try:
        from stellar_forge.economy import (
            Store, Proof402Client, LoyaltyResolver, DryRunSubmitter,
            PayoutRunner, ReferralEngine, GrowthEngine,
            RegistrationRateLimiter, EarnEligibility,
        )
        db = os.environ.get("STELLAR_FORGE_DB", ":memory:")
        store = Store(db)
        client = Proof402Client()
        loyalty = LoyaltyResolver(client)
        tier, info = loyalty.resolve("rUJhaK2ibfTFVdAn8m9jMCcJQ1xo6FmNPZ")
        return jsonify({"ok": True, "tier": tier.name if hasattr(tier,'name') else str(tier), "db": db[:40]})
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"[ForgeDebug] {e}\n{tb}")
        return jsonify({"error": str(e), "traceback": tb[-800:]}), 500
