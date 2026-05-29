"""
Honeypot & Tarpit — Rogue Agent Defense Layer

Catches unauthorized probes for credentials, OAuth tokens, .env files,
and admin paths. Responds with a slow-drain tarpit that wastes scanner
bandwidth while logging the full probe fingerprint for ban analysis.

Tarpit strategy: hold the connection for ~45 seconds with a trickle of
fake JSON. Near-zero server cost (generator yields tiny chunks); maximum
cost to the scanner's request budget and time allocation. After timeout
they mark the path as explored and move on. We get their fingerprint.

Concurrent tarpit connections are capped at MAX_TARPIT_SLOTS to prevent
thread exhaustion. Beyond the cap, probes get an instant 403.
"""

import time
import json
import logging
import threading
from datetime import datetime, timezone
from flask import Blueprint, request, Response

logger = logging.getLogger("SML-Honeypot")

honeypot_bp = Blueprint("honeypot", __name__)

# ── Concurrency cap ───────────────────────────────────────────────────────────
MAX_TARPIT_SLOTS = 5
_tarpit_sem = threading.Semaphore(MAX_TARPIT_SLOTS)

# ── Probe log (in-memory ring buffer, last 500 entries) ──────────────────────
_probe_log: list[dict] = []
_probe_log_lock = threading.Lock()
PROBE_LOG_MAX = 500


def _record_probe(path: str, method: str, ua: str, ip: str) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "ip": ip,
        "ua": ua,
        "method": method,
        "path": path,
    }
    with _probe_log_lock:
        _probe_log.append(entry)
        if len(_probe_log) > PROBE_LOG_MAX:
            _probe_log.pop(0)
    logger.warning(
        "[HONEYPOT] Rogue probe trapped | ip=%s ua=%s path=%s", ip, ua[:120], path
    )


def _tarpit_stream():
    """
    Generator: yields fake credential JSON in tiny chunks over ~45 seconds.
    The scanner receives a legitimate-looking 200 with Content-Type: application/json
    but the response body never closes cleanly — it drains their connection slot.
    """
    # Opening brace — looks like a real response is coming
    yield b'{"status": "ok", "initializing": true, "env": {"loaded": false, "vars": ['

    # Drip fake env-var keys every 15 seconds — 3 drips = 45 seconds total
    fake_keys = [b'"LOADING_1"', b'"LOADING_2"', b'"LOADING_3"']
    for chunk in fake_keys:
        time.sleep(15)
        yield chunk + b","

    # Close with nothing useful
    yield b'"__END__"], "credentials": null, "token": null}}'


# ── Probe path patterns ───────────────────────────────────────────────────────
# Any request matching these path fragments (case-insensitive) is a rogue probe.
_TRAP_FRAGMENTS = (
    ".env", "oauth", "token", "secret", "credential",
    "admin", "wp-admin", "phpmyadmin", ".git",
    "config.js", "config.php", "passwd", "shadow",
    "api_key", "apikey", "private_key", "access_key",
    "schwab_token", "schwab_tokens", "refresh_token",
)


def is_probe(path: str) -> bool:
    low = path.lower()
    return any(frag in low for frag in _TRAP_FRAGMENTS)


@honeypot_bp.route(
    "/oauth/<path:subpath>", methods=["GET", "POST", "PUT", "DELETE"]
)
@honeypot_bp.route(
    "/.env", methods=["GET", "POST"]
)
@honeypot_bp.route(
    "/admin/<path:subpath>", methods=["GET", "POST", "PUT", "DELETE"]
)
@honeypot_bp.route(
    "/api/token", methods=["GET", "POST"]
)
@honeypot_bp.route(
    "/api/keys", methods=["GET", "POST"]
)
def explicit_trap(**kwargs):
    """Explicit trap routes for the highest-value scanner targets."""
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    ua = request.headers.get("User-Agent", "")
    _record_probe(request.path, request.method, ua, ip)
    return _dispatch_tarpit(request.path, ip)


def _dispatch_tarpit(path: str, ip: str) -> Response:
    """Route probe to tarpit if a slot is available, else fast-403."""
    if not _tarpit_sem.acquire(blocking=False):
        # All tarpit slots busy — drop fast to protect thread pool
        return Response(
            json.dumps({"error": "forbidden"}),
            status=403,
            mimetype="application/json",
        )

    def release_and_stream():
        try:
            yield from _tarpit_stream()
        finally:
            _tarpit_sem.release()

    return Response(
        release_and_stream(),
        status=200,
        mimetype="application/json",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


# ── Before-request hook (registered on the app, not the blueprint) ───────────
def honeypot_before_request():
    """
    App-level before_request hook. Intercepts probes on any path that wasn't
    matched by an explicit blueprint route (e.g. /.git/config, /secrets.yaml).
    """
    path = request.path
    if not is_probe(path):
        return None  # Let the request through normally

    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    ua = request.headers.get("User-Agent", "")
    _record_probe(path, request.method, ua, ip)
    return _dispatch_tarpit(path, ip)


# ── Admin read-out (internal only — not exposed in openapi.json) ──────────────
@honeypot_bp.route("/api/ghost/probe-log", methods=["GET"])
def get_probe_log():
    """
    Returns the recent probe log. Secured by ADMIN_TOKEN env var.
    Agents: this endpoint is not in the public API spec by design.
    """
    import os
    token = os.environ.get("ADMIN_TOKEN", "")
    auth = request.headers.get("Authorization", "")
    if not token or auth != f"Bearer {token}":
        # Return a tarpit response if no valid admin token — treat as probe
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
        ua = request.headers.get("User-Agent", "")
        _record_probe(request.path, request.method, ua, ip)
        return Response(
            json.dumps({"error": "forbidden"}),
            status=403,
            mimetype="application/json",
        )
    with _probe_log_lock:
        log_copy = list(_probe_log)
    return Response(
        json.dumps({"count": len(log_copy), "probes": log_copy}, indent=2),
        status=200,
        mimetype="application/json",
    )


# ── Ghost Layer audit relay ───────────────────────────────────────────────────
@honeypot_bp.route("/api/ghost/audit", methods=["GET"])
def ghost_audit():
    """
    Ghost Layer audit stats for the SqueezeOS dashboard.
    Returns real probe counts and Ghost Layer settlement status — no payment required.
    This is the endpoint the analytical-engine.js polls for ghost-mev-status.
    """
    with _probe_log_lock:
        probe_count = len(_probe_log)
        recent_ips = list({p["ip"] for p in _probe_log[-50:]})

    return Response(
        json.dumps({
            "mev_status": "PROTECTED",
            "probes_logged": probe_count,
            "unique_probe_ips_recent": len(recent_ips),
            "tarpit_slots_active": MAX_TARPIT_SLOTS - _tarpit_sem._value,
            "tax_accrued": 0.0,  # XAH tax field — populated by Ghost Layer when integrated
            "ts": datetime.now(timezone.utc).isoformat(),
        }),
        status=200,
        mimetype="application/json",
    )
