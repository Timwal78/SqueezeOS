#!/usr/bin/env python3
"""
Gamma Ramp → Robinhood route
============================
Tradier = data (GEX / chain / Δ pick / VPIN).
Robinhood = funded primary execution (no PDT choke).

Emits RH-ready option intents the PC executor already understands:

  sniper = {
    strike, expiration (YYYY-MM-DD), ask/premium, delta, bid, mid, occ, gamma, dte
  }

Delivery rails (first that works wins for "sent"; all safe rails may fire):
  1) Local outbox JSON  (GAMMA_RAMP_OUTBOX_DIR) — PC executor polls this
  2) Optional webhook   (ROBINHOOD_EXECUTOR_URL + WEBHOOK_SECRET)
  3) Optional SqueezeOS queue POST if GAMMA_RAMP_QUEUE_URL set
  4) Direct robin_stocks only if ROBINHOOD_USERNAME/PASSWORD present AND
     GAMMA_RAMP_RH_DIRECT=1 (this host usually has no RH session)

Never places on underfunded Tradier when EXEC_BROKER=robinhood (default).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import uuid
import urllib.request
import urllib.error
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("gamma_ramp.rh_route")

_HERE = Path(__file__).resolve().parent
DEFAULT_OUTBOX = Path(
    os.environ.get(
        "GAMMA_RAMP_OUTBOX_DIR",
        str(_HERE / "rh_outbox"),
    )
)


@dataclass
class RHOptionIntent:
    """Payload shape compatible with robinhood_executor_sml._execute_option sniper."""

    id: str
    ts: float
    source: str = "gamma_ramp"
    underlying: str = ""
    side: str = "CALL"  # CALL | PUT
    action: str = "BUY_TO_OPEN"  # BUY_TO_OPEN | SELL_TO_CLOSE
    option_type: str = "call"  # robin_stocks: call|put
    strike: float = 0.0
    expiration: str = ""
    occ: str = ""
    delta: float = 0.0
    gamma: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    mid: float = 0.0
    limit_price: float = 0.0
    qty: int = 1
    dte: int = -1
    nbbo_buy: float = 0.0
    nbbo_sell: float = 0.0
    gex_total: float = 0.0
    gex_regime: str = ""
    vpin: float = 0.0
    signed_flow: float = 0.0
    rvol: float = 0.0
    reason: str = ""
    status: str = "pending"  # pending|sent|acked|error
    broker: str = "robinhood"
    data_broker: str = "tradier"
    scale_rules: Dict[str, Any] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def sniper(self) -> Dict[str, Any]:
        """Shape expected by robinhood_executor_sml._execute_option."""
        return {
            "strike": self.strike,
            "expiration": self.expiration,
            "ask": self.ask or self.limit_price,
            "premium": self.mid or self.ask or self.limit_price,
            "bid": self.bid,
            "mid": self.mid,
            "delta": self.delta,
            "gamma": self.gamma,
            "symbol": self.occ,
            "occ": self.occ,
            "dte": self.dte,
            "source": "gamma_ramp",
            "limit_price": self.limit_price,
        }

    def sml_proxy(self) -> Dict[str, Any]:
        return {
            "god_stacked": 6,
            "tier": "GOD_MODE",
            "execute_gate": True,
            "signal": f"GAMMA_RAMP_{self.side}_{self.action}",
            "confidence": 90.0,
            "gamma_ramp": True,
            "reason": self.reason,
            "gex_regime": self.gex_regime,
            "vpin": self.vpin,
        }


def _nbbo_buy(bid: float, ask: float) -> float:
    if bid <= 0 and ask <= 0:
        return 0.0
    if bid <= 0:
        return round(ask, 2)
    pin = round(bid + 0.01, 2)
    if ask > 0:
        pin = min(pin, ask)
    return pin


def _nbbo_sell(bid: float, ask: float) -> float:
    if bid <= 0 and ask <= 0:
        return 0.0
    if ask <= 0:
        return round(bid, 2)
    pin = round(ask - 0.01, 2)
    if bid > 0:
        pin = max(pin, bid)
    return pin


def build_entry_intent(
    *,
    underlying: str,
    side: str,
    pick: Dict[str, Any],
    qty: int = 1,
    gex: Optional[Dict[str, Any]] = None,
    vpin: Optional[Dict[str, Any]] = None,
    rvol: float = 0.0,
    reason: str = "",
) -> RHOptionIntent:
    side_u = (side or "CALL").upper()
    opt = "call" if side_u == "CALL" else "put"
    bid = float(pick.get("bid") or 0)
    ask = float(pick.get("ask") or 0)
    mid = float(pick.get("mid") or ((bid + ask) / 2 if bid and ask else 0))
    nbbo_b = float(pick.get("nbbo_buy") or _nbbo_buy(bid, ask))
    nbbo_s = float(pick.get("nbbo_sell") or _nbbo_sell(bid, ask))
    # Prefer NBBO pin; RH executor historically uses ask*1.05 — we pass limit_price
    # so PC path can honor desk pin when patched; sniper.ask still set for compat.
    limit = nbbo_b if nbbo_b > 0 else round(ask * 1.02, 2) if ask > 0 else mid
    gex = gex or {}
    vpin = vpin or {}
    return RHOptionIntent(
        id=f"gr_{int(time.time())}_{uuid.uuid4().hex[:8]}",
        ts=time.time(),
        underlying=underlying.upper(),
        side=side_u,
        action="BUY_TO_OPEN",
        option_type=opt,
        strike=float(pick.get("strike") or 0),
        expiration=str(pick.get("expiration") or "")[:10],
        occ=str(pick.get("symbol") or pick.get("occ") or ""),
        delta=float(pick.get("delta") or 0),
        gamma=float(pick.get("gamma") or 0),
        bid=bid,
        ask=ask,
        mid=mid,
        limit_price=float(limit),
        qty=max(1, int(qty)),
        dte=int(pick.get("dte") or -1),
        nbbo_buy=nbbo_b,
        nbbo_sell=nbbo_s,
        gex_total=float(gex.get("total_gex") or 0),
        gex_regime=str(gex.get("regime") or ""),
        vpin=float(vpin.get("vpin") or 0),
        signed_flow=float(vpin.get("signed_flow") or 0),
        rvol=float(rvol or 0),
        reason=reason or str(pick.get("reason") or "gamma_ramp_entry"),
        scale_rules={
            "hard_stop": -0.20,
            "scale_1": 0.50,
            "scale_2": 1.50,
            "trail": 0.22,
            "delta_exit": 0.60,
            "capture_band": [0.50, 5.0],
        },
    )


def build_exit_intent(
    *,
    underlying: str,
    side: str,
    occ: str,
    strike: float,
    expiration: str,
    qty: int,
    bid: float,
    ask: float,
    reason: str = "exit",
) -> RHOptionIntent:
    side_u = (side or "CALL").upper()
    opt = "call" if side_u == "CALL" else "put"
    mid = (bid + ask) / 2 if bid and ask else (bid or ask)
    return RHOptionIntent(
        id=f"grx_{int(time.time())}_{uuid.uuid4().hex[:8]}",
        ts=time.time(),
        underlying=underlying.upper(),
        side=side_u,
        action="SELL_TO_CLOSE",
        option_type=opt,
        strike=float(strike),
        expiration=str(expiration)[:10],
        occ=occ,
        bid=float(bid or 0),
        ask=float(ask or 0),
        mid=float(mid or 0),
        limit_price=_nbbo_sell(float(bid or 0), float(ask or 0)),
        qty=max(1, int(qty)),
        nbbo_sell=_nbbo_sell(float(bid or 0), float(ask or 0)),
        reason=reason,
    )


def _write_outbox(intent: RHOptionIntent, outbox: Path = DEFAULT_OUTBOX) -> Path:
    outbox.mkdir(parents=True, exist_ok=True)
    path = outbox / f"{intent.id}.json"
    path.write_text(json.dumps(intent.to_dict(), indent=2))
    # append journal
    journal = outbox / "journal.jsonl"
    with journal.open("a") as f:
        f.write(json.dumps(intent.to_dict()) + "\n")
    return path


def _post_webhook(intent: RHOptionIntent) -> Dict[str, Any]:
    rh_url = (os.environ.get("ROBINHOOD_EXECUTOR_URL") or "").strip()
    if not rh_url:
        return {"ok": False, "reason": "ROBINHOOD_EXECUTOR_URL unset"}
    secret = (os.environ.get("WEBHOOK_SECRET") or "").strip()
    if not secret:
        return {"ok": False, "reason": "WEBHOOK_SECRET unset — refuse unsigned RH webhook"}
    payload_obj = {
        "ticker": intent.underlying,
        "action": "BUY" if intent.action == "BUY_TO_OPEN" else "SELL",
        "mode": "option",
        "option_type": intent.option_type,
        "options_sniper": intent.sniper(),
        "sml_matrix": intent.sml_proxy(),
        "gamma_ramp": intent.to_dict(),
        "qty": intent.qty,
        "limit_price": intent.limit_price,
    }
    payload = json.dumps(payload_obj).encode()
    sig = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    req = urllib.request.Request(
        rh_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-SqueezeOS-Signature": sig,
            "User-Agent": "SqueezeOS-GammaRamp-RH/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return {"ok": True, "status": resp.status, "body": resp.read()[:300].decode(errors="ignore")}
    except Exception as e:
        return {"ok": False, "reason": str(e)}


def _post_queue_url(intent: RHOptionIntent) -> Dict[str, Any]:
    url = (os.environ.get("GAMMA_RAMP_QUEUE_URL") or "").strip()
    if not url:
        return {"ok": False, "reason": "GAMMA_RAMP_QUEUE_URL unset"}
    data = json.dumps(intent.to_dict()).encode()
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "SqueezeOS-GammaRamp-RH/1.0",
    }
    tok = (os.environ.get("GAMMA_RAMP_QUEUE_TOKEN") or os.environ.get("WEBHOOK_SECRET") or "").strip()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
        headers["X-Webhook-Secret"] = tok
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return {"ok": True, "status": resp.status}
    except Exception as e:
        return {"ok": False, "reason": str(e)}



# Anti-loop guards for the direct rh.login() call below -- this function
# used to call rh.login() fresh on EVERY order with zero session reuse and
# zero rate limiting, unlike tools/robinhood_executor_sml.py's carefully
# guarded _ensure_login(). Each real rh.login() call is a real Robinhood
# authentication attempt and can trigger the "trying to log in?" device
# verification prompt -- with a signal firing per order, that produced a
# real, repeated login-verification loop whenever GAMMA_RAMP_RH_DIRECT=1
# was set. Mirrors _ensure_login()'s core rule: verify the existing shared
# pickle session first (robin_stocks' store_session writes the SAME
# pickle_name="rh_session" file both scripts use), only call rh.login()
# when that verify actually fails, and rate-limit real login attempts.
_DIRECT_LAST_LOGIN_TS = 0.0
_DIRECT_LOGIN_COOLDOWN_S = int(os.environ.get("GAMMA_RAMP_RH_LOGIN_COOLDOWN_S", "60"))


def _direct_rh_verify_session(rh) -> bool:
    try:
        profile = rh.profiles.load_account_profile()
        return bool(profile and profile.get("account_number"))
    except Exception:
        return False


def _direct_rh_ensure_login(rh, user: str, pw: str) -> bool:
    global _DIRECT_LAST_LOGIN_TS
    if _direct_rh_verify_session(rh):
        return True
    now = time.time()
    if now - _DIRECT_LAST_LOGIN_TS < _DIRECT_LOGIN_COOLDOWN_S:
        logging.warning(
            "[GAMMA-RAMP-RH] Skipping rh.login() -- attempted <%ss ago, session still invalid",
            _DIRECT_LOGIN_COOLDOWN_S,
        )
        return False
    _DIRECT_LAST_LOGIN_TS = now
    try:
        rh.login(user, pw, store_session=True, pickle_name="rh_session")
    except Exception as e:
        logging.error("[GAMMA-RAMP-RH] rh.login() failed: %s", e)
        return False
    return _direct_rh_verify_session(rh)


def _direct_rh_option(intent: RHOptionIntent) -> Dict[str, Any]:
    """Only if this host has RH creds and operator armed GAMMA_RAMP_RH_DIRECT=1."""
    if os.environ.get("GAMMA_RAMP_RH_DIRECT", "0") != "1":
        return {"ok": False, "reason": "GAMMA_RAMP_RH_DIRECT!=1"}
    user = os.environ.get("ROBINHOOD_USERNAME") or os.environ.get("ROBINHOOD_USER") or ""
    pw = os.environ.get("ROBINHOOD_PASSWORD") or os.environ.get("ROBINHOOD_PASS") or ""
    if not user or not pw:
        return {"ok": False, "reason": "no RH user/pass on this host"}
    try:
        import robin_stocks.robinhood as rh  # type: ignore
        if not _direct_rh_ensure_login(rh, user, pw):
            return {"ok": False, "reason": "robinhood session unavailable (see [GAMMA-RAMP-RH] logs)"}
        if intent.action == "BUY_TO_OPEN":
            r = rh.orders.order_buy_option_limit(
                positionEffect="open",
                creditOrDebit="debit",
                price=float(intent.limit_price),
                symbol=intent.underlying,
                quantity=int(intent.qty),
                expirationDate=intent.expiration,
                strike=float(intent.strike),
                optionType=intent.option_type,
                timeInForce="gfd",
            )
        else:
            r = rh.orders.order_sell_option_limit(
                positionEffect="close",
                creditOrDebit="credit",
                price=float(intent.limit_price),
                symbol=intent.underlying,
                quantity=int(intent.qty),
                expirationDate=intent.expiration,
                strike=float(intent.strike),
                optionType=intent.option_type,
                timeInForce="gfd",
            )
        return {"ok": True, "raw": r}
    except Exception as e:
        return {"ok": False, "reason": str(e)}


def route_intent(intent: RHOptionIntent, live: bool = False) -> Dict[str, Any]:
    """
    Persist + fan-out RH intent.
    live=False → outbox only (signal pack for PC).
    live=True  → outbox + webhook/queue + optional direct.
    """
    path = _write_outbox(intent)
    result: Dict[str, Any] = {
        "status": "queued_rh",
        "broker": "robinhood",
        "data_broker": "tradier",
        "intent_id": intent.id,
        "outbox": str(path),
        "live": bool(live),
        "rails": {},
    }
    result["rails"]["outbox"] = {"ok": True, "path": str(path)}

    if not live:
        intent.status = "pending"
        path.write_text(json.dumps(intent.to_dict(), indent=2))
        return result

    wh = _post_webhook(intent)
    result["rails"]["webhook"] = wh
    q = _post_queue_url(intent)
    result["rails"]["queue"] = q
    d = _direct_rh_option(intent)
    result["rails"]["direct"] = d

    if wh.get("ok") or q.get("ok") or d.get("ok"):
        intent.status = "sent"
        result["status"] = "sent_rh"
        if d.get("ok"):
            result["status"] = "placed_rh_direct"
            result["broker_raw"] = d.get("raw")
    else:
        # still queued locally for PC pull — not a hard fail
        intent.status = "pending"
        result["status"] = "queued_rh_awaiting_pc"
        result["note"] = "outbox written; webhook/queue/direct not armed on this host"

    path.write_text(json.dumps(intent.to_dict(), indent=2))
    return result


def list_pending(outbox: Path = DEFAULT_OUTBOX, limit: int = 50) -> List[Dict[str, Any]]:
    if not outbox.is_dir():
        return []
    files = sorted(outbox.glob("gr*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for f in files[:limit]:
        try:
            d = json.loads(f.read_text())
            if d.get("status") in ("pending", "sent", None):
                d["_path"] = str(f)
                out.append(d)
        except Exception:
            continue
    return out


def mark_acked(intent_id: str, outbox: Path = DEFAULT_OUTBOX, meta: Optional[Dict] = None) -> bool:
    path = outbox / f"{intent_id}.json"
    if not path.is_file():
        # search
        for f in outbox.glob("*.json"):
            try:
                d = json.loads(f.read_text())
            except Exception:
                continue
            if d.get("id") == intent_id:
                path = f
                break
        else:
            return False
    d = json.loads(path.read_text())
    d["status"] = "acked"
    d["acked_ts"] = time.time()
    if meta:
        d["ack_meta"] = meta
    path.write_text(json.dumps(d, indent=2))
    done = outbox / "done"
    done.mkdir(exist_ok=True)
    path.rename(done / path.name)
    return True


def route_status() -> Dict[str, Any]:
    outbox = DEFAULT_OUTBOX
    pending = list_pending(outbox)
    return {
        "exec_broker": os.environ.get("EXEC_BROKER", "robinhood"),
        "data_broker": "tradier",
        "outbox_dir": str(outbox),
        "pending_n": len(pending),
        "pending_ids": [p.get("id") for p in pending[:10]],
        "webhook_configured": bool(os.environ.get("ROBINHOOD_EXECUTOR_URL")),
        "webhook_secret_set": bool(os.environ.get("WEBHOOK_SECRET")),
        "queue_url_set": bool(os.environ.get("GAMMA_RAMP_QUEUE_URL")),
        "rh_direct_armed": os.environ.get("GAMMA_RAMP_RH_DIRECT", "0") == "1",
        "rh_user_present": bool(os.environ.get("ROBINHOOD_USERNAME") or os.environ.get("ROBINHOOD_USER")),
    }


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    if "--status" in sys.argv:
        print(json.dumps(route_status(), indent=2))
    elif "--list" in sys.argv:
        print(json.dumps(list_pending(), indent=2)[:4000])
    else:
        # demo intent
        demo = build_entry_intent(
            underlying="SPY",
            side="CALL",
            pick={
                "strike": 746.0,
                "expiration": "2026-07-31",
                "symbol": "SPY260731C00746000",
                "delta": 0.35,
                "bid": 2.80,
                "ask": 2.84,
                "mid": 2.82,
                "nbbo_buy": 2.81,
                "dte": 3,
            },
            qty=1,
            gex={"total_gex": -1e9, "regime": "SHORT_GAMMA"},
            vpin={"vpin": 0.35, "signed_flow": 0.2},
            reason="demo",
        )
        print(json.dumps(route_intent(demo, live=False), indent=2))
