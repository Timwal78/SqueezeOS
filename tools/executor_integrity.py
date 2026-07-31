"""
Executor Integrity Check — "am I actually running the current code?"
====================================================================
Built 2026-07-31 after the operator reported stale executor behaviour
returning for the FIFTH time. The diagnosis that prompted this:

A live startup banner showed `Poll every : 300s`, `MIN_GOD : 4/6`,
`Daily cap : 25 orders / $1500 notional`, `stop-loss 5.0%` -- none of which
match this repo. Two independent causes, and confusing them is exactly why
it kept coming back:

  1. THE FILE WAS OLD. The banner was missing three whole lines that are
     hardcoded string literals in the current file (the `Options Δ` /
     `Options exit` / `Options loop` rows) and the `[DESK-LOCKED]` /
     `[LOCKED]` suffixes. No environment variable can remove a hardcoded
     string from a log line, so this could only mean a stale .py.

  2. THE ENV WAS OLD, INDEPENDENTLY. `tools/executor.env` overrides repo
     defaults for most risk constants, and `FORCE_UPDATE_EXECUTOR.ps1`
     deliberately preserves it (`git clean -fd -e tools/executor.env`, so
     local secrets survive). A perfect `git reset --hard` therefore fixes
     cause 1 and leaves cause 2 completely untouched -- the desk comes back
     up with the same wrong numbers and looks like the update "didn't take".

This module makes both states impossible to miss at a glance:

  • a BUILD FINGERPRINT (source hash + git SHA) printed at startup, so
    "is this the current file?" is answerable in one line instead of by
    eyeballing a banner for a missing row;
  • a STALE-ENV REPORT that names every risk-critical value where the live
    setting differs from this repo's intent, showing both numbers.

It only ever reports. It does not modify `executor.env`, does not change a
risk parameter, and by default does not stop the desk -- silently refusing
to start would be its own outage. `EXECUTOR_STRICT_INTEGRITY=true` upgrades
divergence to a hard refusal for operators who want that.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_EXECUTOR_PY = os.path.join(_HERE, "robinhood_executor_sml.py")


def source_hash(path: Optional[str] = None) -> Optional[str]:
    """Short sha256 of the executor source. Two machines showing the same
    fingerprint are provably running byte-identical code -- which a version
    string like 'v3.7' cannot tell you, since it is only bumped by hand and
    stayed 'v3.7' across every change that caused this incident."""
    target = path or _EXECUTOR_PY
    try:
        with open(target, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:12]
    except Exception:
        return None


def git_sha() -> Optional[str]:
    """Short git SHA of the checkout this file lives in, when available."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_HERE, capture_output=True, text=True, timeout=5,
        )
        sha = (out.stdout or "").strip()
        return sha or None
    except Exception:
        return None


def git_is_dirty() -> Optional[bool]:
    """True when the checkout has uncommitted changes to tracked files.
    None when git isn't available -- never guessed."""
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=_HERE, capture_output=True, text=True, timeout=5,
        )
        if out.returncode != 0:
            return None
        return bool((out.stdout or "").strip())
    except Exception:
        return None


# Risk-critical settings whose repo intent is documented in
# robinhood_executor_sml.py. Each entry: env var -> (repo intent, human note).
# These are the exact values a stale executor.env has historically overridden.
RISK_INTENT = {
    "MAX_ORDERS_PER_DAY":    ("0",    "0 = uncapped (operator directive 2026-07-29, semi-day-trading)"),
    "MAX_DAILY_NOTIONAL_USD": ("0",   "0 = uncapped (operator directive 2026-07-29); MAX_DAILY_LOSS_USD is the real brake"),
    "STOP_LOSS_PCT":         ("3.0",  "lowered 5.0 -> 3.0 (operator, 2026-07-30) after a real -6.81% slip"),
    "POLL_INTERVAL_S":       ("45",   "desk-locked at 45s; only ALLOW_SLOW_POLL=true can change it"),
}

# Unlock flags that let a stale env re-open a deliberately locked setting.
# Their presence is itself worth reporting -- a lock that a leftover env var
# quietly disables is not a lock.
UNLOCK_FLAGS = ("ALLOW_SLOW_POLL", "ALLOW_CUSTOM_MIN_GOD")


# Protections that silently switch themselves OFF when a piece of config is
# missing. Each entry: env var -> (what goes inert, why it matters).
#
# Added 2026-07-31 after the operator's live log showed, on EVERY buy:
#     [EXEC] GPRE macro regime=UNKNOWN — BUY allowed
#     [EXEC] GPRE 365-day anchor=UNKNOWN — BUY allowed
# Both read like a normal pass. They are not. _get_macro_regime() and
# _get_365_anchor() both begin `if not _MACRO_GATE_SECRET: return "UNKNOWN"`
# with no warning of any kind, so an unset secret disables two real
# direction gates while the desk keeps reporting that trades are "allowed".
#
# Failing open is the right behaviour (an unreachable check must never widen
# what already blocked) -- failing open SILENTLY is not. This makes the
# disabled state announce itself once, at startup, next to everything else.
SILENTLY_DISABLED_GATES = {
    "MACRO_GATE_SECRET": (
        "741 macro-regime gate AND 365-day EMA anchor gate",
        "both return UNKNOWN and allow every BUY; the log line "
        "'macro regime=UNKNOWN — BUY allowed' is what an INERT gate looks like, "
        "not a passing one. Set MACRO_GATE_SECRET in tools/executor.env to the "
        "same value the server uses.",
    ),
}


def disabled_gates_report() -> list:
    """Safety gates currently inert because their config is missing."""
    out = []
    for key, (what, why) in SILENTLY_DISABLED_GATES.items():
        if not os.environ.get(key, "").strip():
            out.append({"setting": key, "disables": what, "detail": why})
    return out


def _num(s: str) -> Optional[float]:
    try:
        return float(str(s).strip())
    except (TypeError, ValueError):
        return None


def stale_env_report() -> list:
    """
    Every risk-critical setting where the live environment differs from this
    repo's documented intent. Compares numerically so "0" and "0.0" don't
    read as a difference.

    Only reports variables that are actually SET -- an unset variable means
    the repo default is in force, which is the desired state, not a finding.
    """
    findings = []
    for key, (intent, note) in RISK_INTENT.items():
        raw = os.environ.get(key)
        if raw is None:
            continue
        a, b = _num(raw), _num(intent)
        differs = (a != b) if (a is not None and b is not None) else (str(raw).strip() != intent)
        if differs:
            findings.append({
                "setting": key,
                "live_value": str(raw).strip(),
                "repo_intent": intent,
                "note": note,
            })

    for flag in UNLOCK_FLAGS:
        if os.environ.get(flag, "false").strip().lower() in ("true", "1", "yes"):
            findings.append({
                "setting": flag,
                "live_value": "true",
                "repo_intent": "false",
                "note": "unlock flag is ON — it re-opens a deliberately locked setting",
            })
    return findings


def report(logger) -> bool:
    """
    Print the integrity block. Returns True when everything matches this
    repo's intent, False when a divergence was reported.

    Never raises: an integrity check that can crash the desk it protects is
    worse than the problem it detects.
    """
    ok = True
    try:
        sh, gs, dirty = source_hash(), git_sha(), git_is_dirty()
        logger.info("-" * 60)
        logger.info("  BUILD CHECK")
        logger.info(f"    executor source : {sh or 'unreadable'}")
        logger.info(f"    git HEAD        : {gs or 'unavailable (not a git checkout?)'}"
                    + ("  [UNCOMMITTED CHANGES]" if dirty else ""))
        logger.info("    Compare 'executor source' against the same line on any other")
        logger.info("    machine — identical hash means provably identical code. The")
        logger.info("    'v3.x' string is hand-maintained and does NOT change per edit.")

        findings = stale_env_report()
        if findings:
            ok = False
            logger.warning("  ⚠️  STALE ENV DETECTED — executor.env is overriding repo intent:")
            for f in findings:
                logger.warning(f"      {f['setting']}: live={f['live_value']} "
                               f"repo_intent={f['repo_intent']}")
                logger.warning(f"        └─ {f['note']}")
            logger.warning("  These come from tools/executor.env, which FORCE_UPDATE_EXECUTOR.ps1")
            logger.warning("  deliberately PRESERVES (git clean -e tools/executor.env) so local")
            logger.warning("  secrets survive. A git reset therefore does NOT clear them — edit or")
            logger.warning("  delete the keys above in tools/executor.env, then restart.")
        else:
            logger.info("  ENV CHECK      : all risk-critical settings match repo intent")

        inert = disabled_gates_report()
        if inert:
            ok = False
            logger.warning("  ⚠️  SAFETY GATES INERT — missing config has switched these OFF:")
            for g in inert:
                logger.warning(f"      {g['setting']} not set → {g['disables']} DISABLED")
                logger.warning(f"        └─ {g['detail']}")
        else:
            logger.info("  GATE CHECK     : all configurable safety gates are active")
        logger.info("-" * 60)
    except Exception as e:  # never break startup
        try:
            logger.warning(f"[INTEGRITY] check failed (non-fatal): {e}")
        except Exception:
            pass
    return ok


def strict_mode() -> bool:
    return os.environ.get("EXECUTOR_STRICT_INTEGRITY", "false").strip().lower() in ("true", "1", "yes")


# ── Single-instance lock ──────────────────────────────────────────────────────
# Built 2026-07-31 after TWO executors were observed running against the SAME
# Robinhood account simultaneously: PM2's `sml-executor` on current code
# (MIN_GOD 6/6) alongside a separately-launched stale copy (MIN_GOD 4/6,
# 300s poll, $1500 notional cap). Neither knew about the other's cooldowns,
# daily order caps, or PDT counter -- every gate this desk relies on is
# per-process state, so a second instance silently doubles orders while both
# report they are within their limits.
#
# A localhost TCP bind is used rather than a PID file on purpose: the bind is
# atomic, and the OS releases it the instant the process dies. A PID file
# would go stale on a crash or a `Stop-Process -Force` and then either block
# a legitimate restart or need liveness-checking logic that is itself another
# thing to get wrong.
#
# The socket is intentionally leaked (never closed, never garbage collected)
# for the life of the process -- that is what holds the lock.
_INSTANCE_LOCK_SOCKET = None


def instance_lock_port() -> int:
    try:
        return int(os.environ.get("EXECUTOR_LOCK_PORT", "49731"))
    except (TypeError, ValueError):
        return 49731


def acquire_single_instance_lock(logger) -> bool:
    """
    True when this process is the only executor. False when another instance
    already holds the lock -- the caller must then exit rather than trade.

    Set EXECUTOR_ALLOW_MULTIPLE=true to bypass (there is no legitimate reason
    to on one brokerage account; it exists so the lock can never become an
    unbreakable outage).
    """
    global _INSTANCE_LOCK_SOCKET
    if os.environ.get("EXECUTOR_ALLOW_MULTIPLE", "false").strip().lower() in ("true", "1", "yes"):
        try:
            logger.warning("[INSTANCE] EXECUTOR_ALLOW_MULTIPLE=true — single-instance lock BYPASSED. "
                           "Two executors on one account double every order; each one's cooldowns, "
                           "daily caps and PDT counter are per-process and cannot see the other.")
        except Exception:
            pass
        return True

    import socket
    port = instance_lock_port()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Deliberately NOT SO_REUSEADDR: reuse is exactly what would let a
        # second instance bind the same port and defeat the lock.
        s.bind(("127.0.0.1", port))
        s.listen(1)
        _INSTANCE_LOCK_SOCKET = s
        return True
    except OSError:
        try:
            logger.error("=" * 60)
            logger.error("[INSTANCE] ANOTHER EXECUTOR IS ALREADY RUNNING — refusing to start.")
            logger.error(f"[INSTANCE] Lock port {port} on 127.0.0.1 is already held.")
            logger.error("[INSTANCE] Two executors on ONE brokerage account double every order:")
            logger.error("[INSTANCE]   cooldowns, daily order/notional caps and the PDT counter are")
            logger.error("[INSTANCE]   all per-process, so both stay 'within limits' while the")
            logger.error("[INSTANCE]   account takes twice the position.")
            logger.error("[INSTANCE] Find it:  Get-CimInstance Win32_Process | ? { $_.CommandLine -like '*executor*' }")
            logger.error("[INSTANCE] Or just: pm2 restart sml-executor   (PM2 stops the old one first)")
            logger.error("=" * 60)
        except Exception:
            pass
        return False
