#!/usr/bin/env python3
"""
Gamma Ramp LIVE AM Engine
=========================
Intraday MM forced-move loop — NOT daily-bar proxy.

Pipeline (every scan cycle, premarket → AH):
  1) Dynamic universe fetch (no hardcoded list)
  2) True spot GEX  → KILL if long-gamma stabilizer
  3) Intraday VPIN/BVC on 1m/5m bars
  4) edge_stack gates (RVOL/z/VPIN/flow/short-gamma)
  5) Dynamic OPRA Δ selector (0.30–0.40, target 0.35)
  6) Tradier NBBO-pinned limit orders (bid+0.01 / ask-0.01)
  7) Manage: -20% stop · +50% scale · +150% scale2 · trail · Δ exit

DATA = Tradier (GEX / chain / Δ / VPIN). EXEC = Robinhood (funded, no PDT).

Orders when:
  GAMMA_RAMP_LIVE=1
  EXEC_BROKER=robinhood (default) → rh_route outbox + optional RH webhook/direct
  EXEC_BROKER=tradier → only if account funded (legacy; underfunded rejects)

Without live flags: scan + RH outbox pending packs. Never paper cosplay.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[1]
for p in (_HERE, _ROOT, _ROOT.parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from edge_stack import (  # noqa: E402
    DELTA_TARGET,
    HARD_STOP,
    RVOL_ENTRY,
    RVOL_EXIT,
    SCALE_TP,
    SCALE2_TP,
    RUNNER_TRAIL,
    RUNNER_TRAIL_LATE,
    DELTA_EXIT,
    TARGET_LO,
    TARGET_HI,
    edge_checklist,
)
from gex_engine import fetch_spot_gex, SpotGEXResult  # noqa: E402
from vpin_intraday import vpin_from_tradier_timesales, calculate_intraday_vpin, VPIN_ENTRY  # noqa: E402
from contract_selector import select_from_tradier, ContractPick  # noqa: E402
from universe import fetch_universe  # noqa: E402
from rh_route import (  # noqa: E402
    build_entry_intent,
    build_exit_intent,
    route_intent,
    route_status,
)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [GAMMA-LIVE] %(levelname)s %(message)s",
)
log = logging.getLogger("gamma_ramp.live")

# ── Session / risk rails ─────────────────────────────────────────────────────
SCAN_INTERVAL_SEC = int(os.environ.get("GAMMA_SCAN_INTERVAL", "30"))
MAX_OPEN_POSITIONS = int(os.environ.get("GAMMA_MAX_POSITIONS", "4"))
MAX_RISK_FRAC = float(os.environ.get("GAMMA_MAX_RISK_FRAC", "0.015"))
MAX_CONTRACTS = int(os.environ.get("GAMMA_MAX_CONTRACTS", "10"))
DAILY_LOSS_HALT_FRAC = float(os.environ.get("GAMMA_DAILY_LOSS_HALT", "0.08"))
BAR_INTERVAL = os.environ.get("GAMMA_BAR_INTERVAL", "5min")  # 1min|5min
REQUIRE_SHORT_GEX = os.environ.get("GAMMA_REQUIRE_SHORT_GEX", "1") == "1"
# Continuous harvest rails — bank 50–500%, sell BEFORE gains reverse
GIVEBACK_LOCK_ARM = float(os.environ.get("GAMMA_GIVEBACK_ARM", "0.50"))   # arm after +50%
GIVEBACK_FRAC = float(os.environ.get("GAMMA_GIVEBACK_FRAC", "0.35"))       # exit if give back 35% of peak gain
BANK_FULL_AT = float(os.environ.get("GAMMA_BANK_FULL_AT", "5.00"))         # +500% full exit
BANK_RUNNER_AT = float(os.environ.get("GAMMA_BANK_RUNNER_AT", "3.00"))     # +300% flatten most
MANAGE_ONLY_INTERVAL = int(os.environ.get("GAMMA_MANAGE_INTERVAL", "15"))  # manage loop faster than full scan
RVOL_FADE_EXIT = float(os.environ.get("GAMMA_RVOL_FADE", str(RVOL_EXIT)))
LIVE = os.environ.get("GAMMA_RAMP_LIVE", "0") == "1"
EXEC_BROKER = (os.environ.get("EXEC_BROKER") or "robinhood").strip().lower()
STATE_PATH = Path(os.environ.get("GAMMA_STATE_PATH", str(_ROOT / "logs" / "gamma_ramp_live_state.json")))
SIGNAL_LOG = Path(os.environ.get("GAMMA_SIGNAL_LOG", str(_ROOT / "logs" / "gamma_ramp_signals.jsonl")))


@dataclass
class OpenPos:
    occ: str
    underlying: str
    side: str
    qty: int
    entry: float
    peak: float
    scaled: bool = False
    scale_frac: float = 0.0
    entry_ts: float = field(default_factory=time.time)
    entry_delta: float = DELTA_TARGET
    contracts_remaining: int = 0
    order_id: str = ""

    def __post_init__(self):
        if self.contracts_remaining <= 0:
            self.contracts_remaining = self.qty


@dataclass
class EngineState:
    day: str = ""
    start_equity: float = 0.0
    equity: float = 0.0
    open: List[Dict[str, Any]] = field(default_factory=list)
    closed_today: int = 0
    pnl_today: float = 0.0
    halted: bool = False
    halt_reason: str = ""
    last_scan_ts: float = 0.0
    signals_today: int = 0


def _load_env_file() -> None:
    env_path = _HERE.parent / "gamma_ramp.env"
    if not env_path.is_file():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def _now_et_parts():
    # rough ET via fixed offset fallback if zoneinfo missing
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        from datetime import timedelta
        now = datetime.now(timezone.utc) - timedelta(hours=4)
    return now


def session_window() -> Dict[str, Any]:
    """Premarket 4:00 → AH 20:00 ET. Core 9:30–16:00."""
    now = _now_et_parts()
    mins = now.hour * 60 + now.minute
    pre = 4 * 60
    open_ = 9 * 60 + 30
    close = 16 * 60
    ah_end = 20 * 60
    if mins < pre or mins >= ah_end:
        phase = "closed"
    elif mins < open_:
        phase = "premarket"
    elif mins < close:
        phase = "rth"
    else:
        phase = "afterhours"
    return {
        "phase": phase,
        "tradable": phase in ("premarket", "rth", "afterhours"),
        "rth": phase == "rth",
        "et": now.strftime("%Y-%m-%d %H:%M:%S"),
        "weekday": now.weekday(),  # 0=Mon
    }


def _save_state(st: EngineState) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(asdict(st), indent=2))


def _load_state() -> EngineState:
    if not STATE_PATH.is_file():
        return EngineState()
    try:
        d = json.loads(STATE_PATH.read_text())
        return EngineState(**{k: d.get(k, getattr(EngineState(), k)) for k in EngineState.__dataclass_fields__})
    except Exception:
        return EngineState()


def _append_signal(obj: Dict[str, Any]) -> None:
    SIGNAL_LOG.parent.mkdir(parents=True, exist_ok=True)
    with SIGNAL_LOG.open("a") as f:
        f.write(json.dumps(obj) + "\n")


def tradier_ready() -> Dict[str, Any]:
    try:
        import tradier_api as t
    except ImportError:
        return {"ok": False, "reason": "tradier_api missing"}
    key = bool(t.is_available())
    acct = bool(os.environ.get("TRADIER_ACCOUNT_ID", "").strip())
    env = (os.environ.get("TRADIER_ENV") or "sandbox").lower()
    return {
        "ok": key,
        "key": key,
        "account": acct,
        "env": env,
        "live_orders_allowed": bool(LIVE and key and acct and env == "production"),
        "reason": "ok" if key else "TRADIER_API_KEY missing",
    }


def get_equity() -> float:
    try:
        import tradier_api as t
        bal = t.get_account_balance()
        if bal and bal > 0:
            return float(bal)
    except Exception as e:
        log.warning("equity fetch: %s", e)
    return float(os.environ.get("GAMMA_DEFAULT_EQUITY", "25000"))


def nbbo_buy_price(bid: float, ask: float) -> float:
    if bid <= 0 and ask <= 0:
        return 0.0
    if bid <= 0:
        return round(ask, 2)
    pin = round(bid + 0.01, 2)
    if ask > 0:
        pin = min(pin, ask)
    return pin


def nbbo_sell_price(bid: float, ask: float) -> float:
    if bid <= 0 and ask <= 0:
        return 0.0
    if ask <= 0:
        return round(bid, 2)
    pin = round(ask - 0.01, 2)
    if bid > 0:
        pin = max(pin, bid)
    return pin


def place_entry(
    pick: ContractPick,
    qty: int,
    ready: Dict[str, Any],
    *,
    gex: Optional[Dict[str, Any]] = None,
    vpin: Optional[Dict[str, Any]] = None,
    rvol: float = 0.0,
    reason: str = "",
) -> Dict[str, Any]:
    """Primary: Robinhood route. Tradier only if EXEC_BROKER=tradier and armed."""
    px = pick.nbbo_buy or nbbo_buy_price(pick.bid, pick.ask)
    payload: Dict[str, Any] = {
        "action": "buy_to_open",
        "occ": pick.symbol,
        "qty": qty,
        "limit": px,
        "side": pick.side,
        "underlying": pick.underlying,
        "exec_broker": EXEC_BROKER,
        "data_broker": "tradier",
    }

    if EXEC_BROKER in ("robinhood", "rh", "both"):
        intent = build_entry_intent(
            underlying=pick.underlying,
            side=pick.side,
            pick=pick.to_dict(),
            qty=qty,
            gex=gex,
            vpin=vpin,
            rvol=rvol,
            reason=reason or f"gamma_ramp {pick.side} Δ={pick.delta}",
        )
        routed = route_intent(intent, live=LIVE)
        payload["rh"] = routed
        payload["intent_id"] = intent.id
        payload["status"] = routed.get("status", "queued_rh")
        if EXEC_BROKER != "both":
            return payload

    # Tradier path (legacy / both)
    if not ready.get("live_orders_allowed"):
        payload.setdefault("status", "signal_only")
        payload["tradier_reason"] = "LIVE flag/production account not armed or underfunded"
        return payload
    import tradier_api as t
    resp = t.place_option_order(pick.symbol, qty, "buy_to_open", limit_price=px)
    payload["tradier"] = resp
    payload["status"] = resp.get("status") or payload.get("status")
    payload["order_id"] = (resp or {}).get("order_id")
    return payload


def place_exit(
    occ: str,
    qty: int,
    bid: float,
    ask: float,
    ready: Dict[str, Any],
    *,
    underlying: str = "",
    side: str = "CALL",
    strike: float = 0.0,
    expiration: str = "",
    reason: str = "exit",
) -> Dict[str, Any]:
    px = nbbo_sell_price(bid, ask)
    payload: Dict[str, Any] = {
        "action": "sell_to_close",
        "occ": occ,
        "qty": qty,
        "limit": px,
        "exec_broker": EXEC_BROKER,
    }
    if EXEC_BROKER in ("robinhood", "rh", "both"):
        intent = build_exit_intent(
            underlying=underlying or occ[:3],
            side=side,
            occ=occ,
            strike=strike,
            expiration=expiration,
            qty=qty,
            bid=bid,
            ask=ask,
            reason=reason,
        )
        routed = route_intent(intent, live=LIVE)
        payload["rh"] = routed
        payload["status"] = routed.get("status", "queued_rh")
        if EXEC_BROKER != "both":
            return payload
    if not ready.get("live_orders_allowed"):
        payload.setdefault("status", "signal_only")
        return payload
    import tradier_api as t
    resp = t.place_option_order(occ, qty, "sell_to_close", limit_price=px)
    payload["tradier"] = resp
    payload["status"] = resp.get("status") or payload.get("status")
    payload["order_id"] = (resp or {}).get("order_id")
    return payload


def size_contracts(equity: float, premium: float, full_size: bool) -> int:
    if premium <= 0 or equity <= 0:
        return 0
    risk_frac = MAX_RISK_FRAC * (1.25 if full_size else 1.0)
    risk_budget = equity * risk_frac
    cost = premium * 100.0
    stop_risk = cost * abs(HARD_STOP)
    qty = max(1, int(risk_budget // max(stop_risk, 1.0)))
    qty = min(qty, MAX_CONTRACTS)
    while qty > 1 and cost * qty > equity * 0.10:
        qty -= 1
    if cost * qty > equity * 0.25:
        return 0
    return max(1, qty)


def evaluate_symbol(sym: str) -> Dict[str, Any]:
    """Full intraday gate stack for one name."""
    out: Dict[str, Any] = {"symbol": sym, "ts": time.time(), "trade": False}

    # 1) GEX — hard kill on positive / long gamma
    gex: SpotGEXResult = fetch_spot_gex(sym)
    out["gex"] = {
        "total_gex": gex.total_gex,
        "regime": gex.regime,
        "playable": gex.playable,
        "call_wall": gex.call_wall,
        "put_wall": gex.put_wall,
        "zgl": gex.zero_gamma_line,
        "spot": gex.spot,
        "source": gex.source,
        "note": gex.note,
    }
    if REQUIRE_SHORT_GEX and not gex.playable:
        out["reject"] = f"gex_{gex.regime}_{gex.note}"
        return out

    # 2) Intraday VPIN
    vpin = vpin_from_tradier_timesales(sym, interval=BAR_INTERVAL, days_back=5, window_n=50)
    out["vpin"] = vpin.to_dict()
    if not vpin.toxic:
        out["reject"] = f"vpin_low_{vpin.vpin:.3f}"
        return out

    # 3) Side from VPIN bias (+ optional quote momentum)
    side = vpin.side_bias
    if side == "NONE":
        out["reject"] = "no_side_bias"
        return out

    # 4) RVOL proxy from timesales if possible
    rvol_ok = True
    try:
        import tradier_api as t
        bars = t.get_timesales(sym, interval=BAR_INTERVAL, days_back=5) or []
        if len(bars) >= 30:
            vols = [float(b.get("volume") or 0) for b in bars]
            last = vols[-1]
            base = sum(vols[-21:-1]) / max(1, len(vols[-21:-1]))
            rvol = (last / base) if base > 0 else 0.0
            out["rvol"] = rvol
            rvol_ok = rvol >= RVOL_ENTRY
    except Exception as e:
        out["rvol_err"] = str(e)
        rvol_ok = True  # don't hard-fail if timesales partial; VPIN already toxic

    if not rvol_ok:
        out["reject"] = f"rvol_low_{out.get('rvol')}"
        return out

    # 5) Contract select 0.30-0.40Δ
    pick = select_from_tradier(sym, target_side=side, style="auto")
    out["contract"] = pick.to_dict()
    if not pick.ok:
        out["reject"] = f"no_delta_contract:{pick.reason}"
        return out

    out["trade"] = True
    out["side"] = side
    out["full_size"] = bool(vpin.full_size and gex.playable)
    out["reason"] = (
        f"{side} shortGEX={gex.total_gex:.0f} vpin={vpin.vpin:.2f} "
        f"flow={vpin.signed_flow:+.2f} Δ={pick.delta:.2f} {pick.symbol} "
        f"mid={pick.mid:.2f} spr={pick.spread_pct:.1%}"
    )
    return out


def manage_open(st: EngineState, ready: Dict[str, Any]) -> EngineState:
    """Scale / trail / stop on open option positions."""
    if not st.open:
        return st
    try:
        import tradier_api as t
    except ImportError:
        return st

    still: List[Dict[str, Any]] = []
    for raw in st.open:
        pos = OpenPos(**raw)
        q = t.get_quote(pos.occ) or {}
        bid = float(q.get("bid") or 0)
        ask = float(q.get("ask") or 0)
        last = float(q.get("last") or 0)
        mark = last if last > 0 else ((bid + ask) / 2.0 if bid and ask else bid or ask)
        if mark <= 0:
            still.append(asdict(pos))
            continue
        pos.peak = max(pos.peak, mark)
        ret = (mark - pos.entry) / pos.entry if pos.entry > 0 else 0.0

        exit_qty = 0
        reason = ""
        peak_ret = (pos.peak - pos.entry) / pos.entry if pos.entry > 0 else 0.0

        # 1) Hard stop — cut loser before it nukes the book
        if ret <= HARD_STOP:
            exit_qty, reason = pos.contracts_remaining, "hard_stop"

        # 2) Full bank at +500% (TARGET_HI) — never round-trip a moonshot
        elif ret >= BANK_FULL_AT or ret >= TARGET_HI:
            exit_qty, reason = pos.contracts_remaining, "bank_500"

        # 3) Scale 1 at +50% — sell half, keep runner for 50–500% capture
        elif (not pos.scaled) and ret >= SCALE_TP:
            exit_qty = max(1, pos.contracts_remaining // 2)
            reason = "scale_50"
            pos.scaled = True
            pos.scale_frac = 0.5
            pos.peak = mark

        # 4) Scale 2 at +150% — sell half of runner
        elif pos.scaled and pos.scale_frac < 0.75 and ret >= SCALE2_TP:
            exit_qty = max(1, pos.contracts_remaining // 2)
            reason = "scale_150"
            pos.scale_frac = 0.75
            pos.peak = mark

        # 5) Big runner bank at +300% — flatten most remaining
        elif pos.scaled and ret >= BANK_RUNNER_AT and pos.contracts_remaining > 1:
            exit_qty = max(1, pos.contracts_remaining - 1)  # leave 1 lottery
            reason = "bank_300"

        # 6) GIVEBACK LOCK — once +50% was seen, exit if we give back 35% of peak gain
        #    This is "sell before loss of gains" — protects 50–500% harvests.
        elif peak_ret >= GIVEBACK_LOCK_ARM and peak_ret > 0:
            giveback = (pos.peak - mark) / pos.entry if pos.entry > 0 else 0.0
            # fraction of peak gain surrendered
            frac_lost = giveback / peak_ret if peak_ret > 0 else 0.0
            if frac_lost >= GIVEBACK_FRAC and ret > 0:
                exit_qty, reason = pos.contracts_remaining, "giveback_lock"
            elif ret <= 0 and peak_ret >= GIVEBACK_LOCK_ARM:
                # was green +50%+, now red — dump remainder
                exit_qty, reason = pos.contracts_remaining, "giveback_to_red"

        # 7) Classic peak trail after scale (price trail %)
        if not reason and pos.scaled:
            trail = RUNNER_TRAIL_LATE if pos.scale_frac >= 0.75 else RUNNER_TRAIL
            if pos.peak > 0 and (mark - pos.peak) / pos.peak <= -trail:
                exit_qty, reason = pos.contracts_remaining, "trail"

        # 8) Delta expansion exit — MM hedge complete, torque done
        if not reason:
            g = q.get("greeks") or {}
            try:
                d = abs(float(g.get("delta") or pos.entry_delta or 0))
                if d >= DELTA_EXIT and ret >= 0.50 and pos.contracts_remaining > 0:
                    exit_qty, reason = pos.contracts_remaining, "delta_expansion"
            except Exception:
                pass

        # 9) Near +500% safety (0.9x TARGET_HI) full exit
        if not reason and ret >= TARGET_HI * 0.9:
            exit_qty, reason = pos.contracts_remaining, "target_500"

        if exit_qty > 0:
            resp = place_exit(pos.occ, exit_qty, bid, ask, ready, underlying=pos.underlying, side=pos.side, reason=reason)
            log.info("EXIT %s qty=%s ret=%.1f%% reason=%s → %s", pos.occ, exit_qty, ret * 100, reason, resp.get("status"))
            _append_signal({"type": "exit", "pos": asdict(pos), "ret": ret, "reason": reason, "resp": resp, "ts": time.time()})
            pnl = (mark - pos.entry) * 100 * exit_qty
            st.pnl_today += pnl
            pos.contracts_remaining -= exit_qty
            if pos.contracts_remaining > 0 and reason.startswith("scale"):
                still.append(asdict(pos))
            else:
                st.closed_today += 1
        else:
            still.append(asdict(pos))

    st.open = still
    return st


def scan_once(st: EngineState) -> EngineState:
    ready = tradier_ready()
    sess = session_window()
    log.info("scan phase=%s live_orders=%s tradier=%s", sess["phase"], ready.get("live_orders_allowed"), ready)

    if sess["weekday"] >= 5:
        log.info("weekend — idle")
        return st
    if not sess["tradable"]:
        log.info("outside 4:00-20:00 ET — idle")
        return st

    # day roll
    day = sess["et"][:10]
    if st.day != day:
        st = EngineState(day=day, start_equity=get_equity(), equity=get_equity())
    st.equity = get_equity()
    if st.start_equity <= 0:
        st.start_equity = st.equity

    # daily loss halt
    if st.start_equity > 0 and (st.start_equity - st.equity) / st.start_equity >= DAILY_LOSS_HALT_FRAC:
        st.halted = True
        st.halt_reason = "daily_loss_halt"
        log.warning("HALTED daily loss rail")
        _save_state(st)
        return st
    if st.halted:
        log.warning("engine halted: %s", st.halt_reason)
        return st

    # manage opens first
    st = manage_open(st, ready)

    if len(st.open) >= MAX_OPEN_POSITIONS:
        log.info("max positions %s — manage only", MAX_OPEN_POSITIONS)
        st.last_scan_ts = time.time()
        _save_state(st)
        return st

    # dynamic universe
    uni = fetch_universe()
    symbols = uni.get("symbols") or []
    log.info("universe n=%s sources=%s", len(symbols), uni.get("sources_ok"))

    open_underlyings = {p.get("underlying") for p in st.open}
    scanned = 0
    for sym in symbols:
        if len(st.open) >= MAX_OPEN_POSITIONS:
            break
        if sym in open_underlyings:
            continue
        # prioritize RTH for new risk; allow premarket/AH scans as signals
        try:
            sig = evaluate_symbol(sym)
        except Exception as e:
            log.warning("eval %s err %s", sym, e)
            continue
        scanned += 1
        _append_signal({"type": "eval", **sig})
        if not sig.get("trade"):
            continue

        pick_d = sig["contract"]
        pick = ContractPick(**{k: pick_d[k] for k in ContractPick.__dataclass_fields__ if k in pick_d})
        qty = size_contracts(st.equity, pick.mid, full_size=bool(sig.get("full_size")))
        if qty <= 0:
            continue

        # Only arm new entries in RTH by default (pre/AH = signal log)
        if not sess["rth"] and os.environ.get("GAMMA_ALLOW_EXT_ENTRIES", "0") != "1":
            log.info("SIGNAL (ext hours) %s", sig.get("reason"))
            st.signals_today += 1
            continue

        resp = place_entry(
            pick, qty, ready,
            gex=sig.get("gex"),
            vpin=sig.get("vpin"),
            rvol=float(sig.get("rvol") or 0),
            reason=str(sig.get("reason") or ""),
        )
        log.info("ENTRY %s → %s", sig.get("reason"), resp.get("status"))
        st.signals_today += 1
        _append_signal({"type": "entry", "sig": sig, "resp": resp, "qty": qty, "ts": time.time()})

        ok_statuses = {
            "success", "queued_rh", "sent_rh", "queued_rh_awaiting_pc",
            "placed_rh_direct", "signal_only",
        }
        if resp.get("status") in ok_statuses:
            # Track RH-queued intents so we don't double-fire same underlying this session.
            # Real fill confirmation lives on the PC RH executor.
            if resp.get("status") != "signal_only" or EXEC_BROKER in ("robinhood", "rh", "both"):
                st.open.append(asdict(OpenPos(
                    occ=pick.symbol,
                    underlying=sym,
                    side=pick.side,
                    qty=qty,
                    entry=pick.nbbo_buy or pick.mid,
                    peak=pick.nbbo_buy or pick.mid,
                    entry_delta=abs(pick.delta),
                    order_id=str(resp.get("order_id") or resp.get("intent_id") or ""),
                )))
                open_underlyings.add(sym)

        # rate limit chain hammering
        time.sleep(float(os.environ.get("GAMMA_SYMBOL_SLEEP", "1.1")))
        if scanned >= int(os.environ.get("GAMMA_MAX_EVAL_PER_SCAN", "15")):
            break

    st.last_scan_ts = time.time()
    _save_state(st)
    return st


def run_loop(once: bool = False) -> None:
    _load_env_file()
    log.info("=== GAMMA RAMP LIVE ENGINE — continuous MM forced-move loop ===")
    log.info("edge: %s", json.dumps(edge_checklist())[:300])
    log.info(
        "rails: stop=%.0f%% scale=+%.0f%%/+%.0f%% bank=+%.0f%%/+%.0f%% giveback_arm=+%.0f%% giveback=%.0f%% Δexit=%.2f",
        HARD_STOP * 100, SCALE_TP * 100, SCALE2_TP * 100,
        BANK_RUNNER_AT * 100, BANK_FULL_AT * 100,
        GIVEBACK_LOCK_ARM * 100, GIVEBACK_FRAC * 100, DELTA_EXIT,
    )
    ready = tradier_ready()
    log.info("tradier: %s LIVE=%s EXEC_BROKER=%s rh=%s", ready, LIVE, EXEC_BROKER, route_status())
    st = _load_state()
    last_full_scan = 0.0
    while True:
        try:
            # ALWAYS manage open positions first on a tight cadence so we
            # bank 50–500% and sell before giveback — never wait for full universe.
            ready = tradier_ready()
            st = manage_open(st, ready)
            _save_state(st)

            now = time.time()
            do_full = once or (now - last_full_scan >= SCAN_INTERVAL_SEC)
            if do_full:
                st = scan_once(st)
                last_full_scan = time.time()
            else:
                # tight manage tick
                log.info(
                    "manage-tick open=%s pnl_today=%.2f halted=%s",
                    len(st.open), st.pnl_today, st.halted,
                )
        except Exception as e:
            log.exception("loop crash: %s", e)
        if once:
            break
        time.sleep(MANAGE_ONLY_INTERVAL)


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(argv or sys.argv[1:])
    once = "--once" in argv or os.environ.get("GAMMA_ONCE") == "1"
    if "--checklist" in argv:
        print(json.dumps(edge_checklist(), indent=2))
        return 0
    if "--status" in argv:
        _load_env_file()
        print(json.dumps({
            "session": session_window(),
            "tradier": tradier_ready(),
            "exec_broker": EXEC_BROKER,
            "rh_route": route_status(),
            "live_flag": LIVE,
            "state": asdict(_load_state()) if STATE_PATH.is_file() else {},
            "modules": ["gex_engine", "vpin_intraday", "contract_selector", "edge_stack", "universe", "rh_route"],
        }, indent=2))
        return 0
    run_loop(once=once)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
