"""
SML Vault Engine — CCXT Crypto Pyramid Builder (zero custody)
================================================================
Same 5-layer EMA pyramid strategy as avg_down_engine.py (ENTER on full-bull
ribbon, ADD on drawdown steps, EXIT at profit target, HARD_STOP / STOP on
anchor break), applied to crypto pairs via CCXT instead of equities via
Tradier.

ZERO CUSTODY: this engine only ever trades on the operator's own exchange
account, using the operator's own API key/secret. It does not hold, pool,
or manage funds on behalf of anyone else, and it does not deploy or call
any smart contract. MASTER_WALLET_ADDRESS is informational/display only —
no private key ever touches this file, no on-chain transaction is signed
here. If that's ever untrue, this module is being used wrong.

Config (matches the env var names already documented for the
sml-vault-executor Render service — read these, don't invent new names for
anything already named there):
  SML_EMA_PERIODS     — 5 comma-separated EMA periods, e.g. "55,89,144,233,365"
  SML_DRAWDOWN_STEP    — per-level dip that triggers an ADD (decimal, e.g. 0.04)
  SML_PROFIT_TARGET    — gain above avg cost that triggers EXIT (decimal, e.g. 0.07)
  CCXT_EXCHANGE        — CCXT exchange id, e.g. "coinbase", "kraken"
  MASTER_WALLET_ADDRESS — informational only, shown in status, never signs anything

New config (not yet documented anywhere — needed for this engine to do
anything beyond alert-only):
  SML_VAULT_ENABLED     — master switch; without it, ENTER/ADD/EXIT/STOP are
                          alert-only (Discord + signal log), no orders placed
  SML_VAULT_API_KEY / SML_VAULT_API_SECRET — CCXT credentials for the
                          operator's OWN exchange account. No default, ever.
  SML_VAULT_SYMBOLS     — comma-separated trading pairs, e.g. "BTC/USD,ETH/USD".
                          No default — Prime Directive #1 (no hardcoded ticker
                          lists). Required if the engine is to scan anything.
  SML_VAULT_MAX_LEVELS / SML_VAULT_INITIAL_SIZE / SML_VAULT_SCALE_FACTOR —
                          same shape as avg_down_engine's proven defaults
                          (3, 0.20, 0.55)
  SML_VAULT_MAX_LOSS_PCT — hard %-loss stop, checked before the anchor-break
                          stop, same fix just proven and applied to
                          avg_down_engine.py (default 0.15). Built in from
                          day one instead of re-discovering the same bug.
  SML_VAULT_SCAN_INTERVAL_S — default 300 (5 min)

Every dollar/credential value above with no default (SML_VAULT_API_KEY,
SML_VAULT_API_SECRET, SML_VAULT_SYMBOLS) must be explicitly set. Missing any
of them keeps the engine in alert-only mode — it will not silently guess a
trading pair or run without real credentials.
"""

from __future__ import annotations

import os
import time
import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger("SML-Vault")

# ─── CONFIG ─────────────────────────────────────────────────────────────────

def _env_float(key: str, default: float) -> float:
    try:    return float(os.environ.get(key, default))
    except: return default

def _env_int(key: str, default: int) -> int:
    try:    return int(os.environ.get(key, default))
    except: return default

def _load_layers() -> List[int]:
    raw = os.environ.get("SML_EMA_PERIODS", "").strip()
    if not raw:
        raise RuntimeError("SML_EMA_PERIODS not set — vault engine cannot start without it")
    periods = [int(x.strip()) for x in raw.split(",") if x.strip()]
    if len(periods) != 5:
        raise RuntimeError(f"SML_EMA_PERIODS must have exactly 5 values, got {len(periods)}")
    return sorted(periods)

SML_VAULT_ENABLED = os.environ.get("SML_VAULT_ENABLED", "false").lower() == "true"
CCXT_EXCHANGE     = os.environ.get("CCXT_EXCHANGE", "").strip()
API_KEY           = os.environ.get("SML_VAULT_API_KEY", "").strip()
API_SECRET        = os.environ.get("SML_VAULT_API_SECRET", "").strip()
MASTER_WALLET     = os.environ.get("MASTER_WALLET_ADDRESS", "").strip()  # display only

ADD_PCT      = _env_float("SML_DRAWDOWN_STEP", 0.04)
EXIT_GAIN    = _env_float("SML_PROFIT_TARGET", 0.07)
MAX_LEVELS   = _env_int("SML_VAULT_MAX_LEVELS", 3)
INITIAL_SIZE = _env_float("SML_VAULT_INITIAL_SIZE", 0.20)
SCALE_FACTOR = _env_float("SML_VAULT_SCALE_FACTOR", 0.55)
MAX_LOSS_PCT = _env_float("SML_VAULT_MAX_LOSS_PCT", 0.15)   # same fix as avg_down_engine
SCAN_INTERVAL_S = _env_int("SML_VAULT_SCAN_INTERVAL_S", 300)
BARS_NEEDED  = 400

# ─── IN-MEMORY STATE (resets on restart — same convention as avg_down_engine) ──

_positions: Dict[str, dict] = {}
_signals: deque = deque(maxlen=200)
_state_lock = threading.Lock()
_exchange = None  # lazily initialized ccxt exchange instance

# ─── EMA MATH (same formulas as avg_down_engine.py, kept independent so each
# engine can be configured/deployed separately without coupling) ────────────

def _ema(values: List[float], period: int) -> List[float]:
    k = 2.0 / (period + 1)
    out, e = [], None
    for v in values:
        e = v if e is None else v * k + e * (1 - k)
        out.append(e)
    return out


def _compute_layers(closes: List[float]) -> Optional[Dict[str, float]]:
    layers = _load_layers()
    if len(closes) < layers[-1]:
        return None
    result = {}
    for i, period in enumerate(layers, start=1):
        series = _ema(closes, period)
        result[f"L{i}"] = series[-1]
    return result


def _ribbon_state(lv: Dict[str, float], close: float) -> dict:
    vals = [lv["L1"], lv["L2"], lv["L3"], lv["L4"], lv["L5"]]
    full_bull  = all(vals[i] > vals[i+1] for i in range(4))
    loose_bull = vals[0] > vals[1] > vals[2]
    above_anchor = close > vals[4]
    align_score = sum(1 for i in range(4) if vals[i] > vals[i+1])
    return {"full_bull": full_bull, "loose_bull": loose_bull,
            "above_anchor": above_anchor, "align_score": align_score}


# ─── CCXT EXCHANGE ACCESS ───────────────────────────────────────────────────

def _get_exchange():
    """Lazily construct the ccxt exchange instance for the operator's OWN
    account. Returns None (never raises) if ccxt isn't installed, no
    CCXT_EXCHANGE is configured, or construction fails -- callers must
    treat None as 'unavailable', matching the 'no mock data, 503 not fake
    data' convention used elsewhere in this codebase."""
    global _exchange
    if _exchange is not None:
        return _exchange
    if not CCXT_EXCHANGE:
        return None
    try:
        import ccxt
        klass = getattr(ccxt, CCXT_EXCHANGE, None)
        if klass is None:
            logger.error(f"[VAULT] Unknown CCXT_EXCHANGE '{CCXT_EXCHANGE}'")
            return None
        kwargs = {"enableRateLimit": True}
        if API_KEY and API_SECRET:
            kwargs.update({"apiKey": API_KEY, "secret": API_SECRET})
        _exchange = klass(kwargs)
        return _exchange
    except ImportError:
        logger.error("[VAULT] ccxt not installed — engine cannot fetch data or trade")
        return None
    except Exception as e:
        logger.error(f"[VAULT] CCXT exchange init failed: {e}")
        return None


def _fetch_closes(symbol: str) -> List[float]:
    ex = _get_exchange()
    if ex is None:
        return []
    try:
        ohlcv = ex.fetch_ohlcv(symbol, timeframe="1d", limit=BARS_NEEDED + 20)
        return [bar[4] for bar in ohlcv if bar[4] is not None]  # close is index 4
    except Exception as e:
        logger.debug(f"[VAULT] fetch_ohlcv failed {symbol}: {e}")
        return []


def _get_symbols() -> List[str]:
    raw = os.environ.get("SML_VAULT_SYMBOLS", "").strip()
    if not raw:
        return []
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def _can_trade_live() -> bool:
    return SML_VAULT_ENABLED and bool(API_KEY) and bool(API_SECRET) and _get_exchange() is not None


# ─── DISCORD ────────────────────────────────────────────────────────────────

def _fire_discord(signal: dict):
    url = os.environ.get("DISCORD_WEBHOOK_VAULT", "") or os.environ.get("DISCORD_WEBHOOK_ALL", "")
    if not url:
        return
    try:
        from discord_alerts import DiscordAlerts
        da = DiscordAlerts()
        action = signal["action"]
        symbol = signal["symbol"]
        colors = {"ENTER": 0x00FF88, "ADD": 0x00BFFF, "EXIT": 0xFFD700,
                  "STOP": 0xFF4444, "HARD_STOP": 0x8B0000}
        emojis = {"ENTER": "🟢", "ADD": "📥", "EXIT": "💰", "STOP": "🛑", "HARD_STOP": "⛔"}
        mode = "🔴 LIVE" if _can_trade_live() else "📋 ALERT-ONLY"
        fields = [
            {"name": "Pair",        "value": f"**{symbol}**",           "inline": True},
            {"name": "Action",      "value": f"**{action}**",           "inline": True},
            {"name": "Price",       "value": f"${signal['price']:.4f}", "inline": True},
            {"name": "Mode",        "value": mode,                      "inline": True},
            {"name": "Add Level",   "value": str(signal["level"]),      "inline": True},
            {"name": "Align Score", "value": f"{signal['align_score']}/4", "inline": True},
        ]
        if signal.get("pnl_pct") is not None:
            fields.append({"name": "PnL", "value": f"{signal['pnl_pct']:+.2f}%", "inline": True})
        payload = {"embeds": [{
            "title": f"{emojis.get(action,'🔔')} SML VAULT — {symbol} {action}",
            "description": "Zero-custody — operator's own exchange account only.",
            "color": colors.get(action, 0xAAAAAA),
            "fields": fields,
            "footer": {"text": f"SML Vault Engine | {datetime.now().strftime('%I:%M %p ET')}"},
            "timestamp": datetime.utcnow().isoformat(),
        }]}
        da._post(url, payload)
    except Exception as e:
        logger.warning(f"[VAULT] Discord post failed: {e}")


# ─── EXECUTION (operator's own account only — no custody) ──────────────────

def _place_order(symbol: str, side: str, notional_fraction: float, price: float) -> dict:
    """Places a real spot market order on the operator's own exchange account
    if live trading is configured; otherwise returns an alert-only result.
    Long-only, spot-only -- no shorting, no leverage, mirrors the equities
    engine's guardrails."""
    if not _can_trade_live():
        return {"alert_only": True}
    ex = _get_exchange()
    try:
        balance = ex.fetch_balance()
        quote_ccy = symbol.split("/")[-1]
        available = float((balance.get(quote_ccy) or {}).get("free", 0) or 0)
        spend = available * notional_fraction
        if spend <= 0:
            return {"error": f"no available {quote_ccy} balance"}
        amount = spend / price
        if side == "buy":
            order = ex.create_market_buy_order(symbol, amount)
        else:
            order = ex.create_market_sell_order(symbol, amount)
        return {"placed": True, "order": order}
    except Exception as e:
        logger.error(f"[VAULT] order error {symbol} {side}: {e}")
        return {"error": str(e)}


# ─── POSITION MANAGEMENT (same math as avg_down_engine.py) ─────────────────

def _open_position(symbol: str, price: float, ts: str):
    with _state_lock:
        _positions[symbol] = {"in_position": True, "avg_price": price, "level": 0,
                               "entry_price": price, "entry_ts": ts, "size": INITIAL_SIZE}
    logger.info(f"[VAULT] ENTER {symbol} @ {price:.4f}")


def _add_to_position(symbol: str, price: float, new_level: int):
    with _state_lock:
        pos = _positions.get(symbol, {})
        old_avg  = float(pos.get("avg_price", price))
        old_size = float(pos.get("size", INITIAL_SIZE))
        add_size = INITIAL_SIZE * (SCALE_FACTOR ** new_level)
        new_avg  = (old_avg * old_size + price * add_size) / (old_size + add_size)
        pos.update({"avg_price": new_avg, "level": new_level, "size": old_size + add_size})
        _positions[symbol] = pos
    logger.info(f"[VAULT] ADD L{new_level} {symbol} @ {price:.4f} new_avg={new_avg:.4f}")


def _close_position(symbol: str, price: float, reason: str, pnl: float, ts: str):
    with _state_lock:
        _positions.pop(symbol, None)
    logger.info(f"[VAULT] {reason} {symbol} @ {price:.4f} pnl={pnl*100:.1f}%")


def _make_signal(symbol, action, price, level, lv, ribbon, pnl, ts) -> dict:
    return {
        "symbol": symbol, "action": action, "price": round(price, 6), "level": level,
        "pnl_pct": round(pnl * 100, 2) if pnl else None,
        "align_score": ribbon["align_score"], "above_anchor": ribbon["above_anchor"],
        "L1": round(lv["L1"], 6), "L2": round(lv["L2"], 6), "L3": round(lv["L3"], 6),
        "L4": round(lv["L4"], 6), "L5": round(lv["L5"], 6), "ts": ts,
    }


# ─── SIGNAL EVALUATION (identical shape to avg_down_engine._evaluate, with
# the hard-stop fix included from day one) ──────────────────────────────────

def _evaluate(symbol: str, closes: List[float], now_iso: str) -> Optional[dict]:
    lv = _compute_layers(closes)
    if not lv:
        return None
    close = closes[-1]
    ribbon = _ribbon_state(lv, close)

    with _state_lock:
        pos = _positions.get(symbol, {})
        in_pos = bool(pos.get("in_position"))
        avg_price = float(pos.get("avg_price", 0.0))
        level = int(pos.get("level", 0))

    if in_pos:
        pnl = (close - avg_price) / avg_price if avg_price > 0 else 0.0

        # Hard %-loss stop, checked BEFORE the anchor-break stop -- same fix
        # just proven and applied to avg_down_engine.py. The anchor (L5) is
        # too slow on its own during a real decline.
        if pnl < -MAX_LOSS_PCT:
            _place_order(symbol, "sell", 1.0, close)
            _close_position(symbol, close, "HARD_STOP", pnl, now_iso)
            return _make_signal(symbol, "HARD_STOP", close, level, lv, ribbon, pnl, now_iso)

        if not ribbon["above_anchor"]:
            _place_order(symbol, "sell", 1.0, close)
            _close_position(symbol, close, "STOP", pnl, now_iso)
            return _make_signal(symbol, "STOP", close, level, lv, ribbon, pnl, now_iso)

        if pnl >= EXIT_GAIN or (pnl > 0.005 and ribbon["full_bull"] and ribbon["above_anchor"]):
            _place_order(symbol, "sell", 1.0, close)
            _close_position(symbol, close, "EXIT", pnl, now_iso)
            return _make_signal(symbol, "EXIT", close, level, lv, ribbon, pnl, now_iso)

        threshold = -ADD_PCT * (level + 1)
        if pnl < threshold and level < MAX_LEVELS and ribbon["loose_bull"]:
            add_size_fraction = SCALE_FACTOR ** (level + 1)
            _place_order(symbol, "buy", add_size_fraction, close)
            _add_to_position(symbol, close, level + 1)
            return _make_signal(symbol, "ADD", close, level + 1, lv, ribbon, pnl, now_iso)

        return None

    if ribbon["full_bull"] and ribbon["above_anchor"] and close > lv["L1"]:
        _place_order(symbol, "buy", INITIAL_SIZE, close)
        _open_position(symbol, close, now_iso)
        return _make_signal(symbol, "ENTER", close, 0, lv, ribbon, 0.0, now_iso)

    return None


# ─── SCAN LOOP ──────────────────────────────────────────────────────────────

def _scan_once():
    symbols = _get_symbols()
    if not symbols:
        logger.debug("[VAULT] SML_VAULT_SYMBOLS not set — nothing to scan")
        return
    now_iso = datetime.now(timezone.utc).isoformat()
    fired = 0
    for sym in symbols:
        closes = _fetch_closes(sym)
        if len(closes) < 80:
            continue
        try:
            sig = _evaluate(sym, closes, now_iso)
        except Exception as e:
            logger.warning(f"[VAULT] eval error {sym}: {e}")
            continue
        if sig:
            with _state_lock:
                _signals.appendleft(sig)
            _fire_discord(sig)
            fired += 1
    active = sum(1 for p in _positions.values() if p.get("in_position"))
    logger.info(f"[VAULT] scan complete | {len(symbols)} pairs | {fired} signals | {active} open positions")


# ─── PUBLIC API ─────────────────────────────────────────────────────────────

def get_positions() -> List[dict]:
    with _state_lock:
        return [{"symbol": sym, **pos} for sym, pos in _positions.items() if pos.get("in_position")]


def get_signals(limit: int = 50) -> List[dict]:
    with _state_lock:
        return list(_signals)[:limit]


def get_status() -> dict:
    return {
        "engine": "sml_vault", "running": bool(_thread and _thread.is_alive()),
        "custody_model": "zero-custody: operator's own exchange account only",
        "live_trading": _can_trade_live(),
        "exchange": CCXT_EXCHANGE or None,
        "master_wallet_display": MASTER_WALLET or None,
        "scan_interval_s": SCAN_INTERVAL_S, "max_levels": MAX_LEVELS,
        "add_pct": ADD_PCT, "exit_gain": EXIT_GAIN, "max_loss_pct": MAX_LOSS_PCT,
        "symbols": _get_symbols(), "open_positions": len(get_positions()),
        "signal_count": len(_signals),
    }


# ─── THREAD START ───────────────────────────────────────────────────────────

_thread: Optional[threading.Thread] = None


def start_vault_engine():
    """Start the vault background daemon. Idempotent. No-ops (logs why) if
    SML_EMA_PERIODS or SML_VAULT_SYMBOLS aren't configured -- never guesses
    a EMA config or a trading pair."""
    global _thread
    if _thread and _thread.is_alive():
        return
    try:
        _load_layers()
    except Exception as e:
        logger.warning(f"[VAULT] not starting: {e}")
        return
    if not _get_symbols():
        logger.warning("[VAULT] not starting: SML_VAULT_SYMBOLS not set")
        return

    def _loop():
        logger.info(f"[VAULT] SML Vault Engine started | live_trading={_can_trade_live()}")
        time.sleep(45)
        while True:
            try:
                _scan_once()
            except Exception as e:
                logger.error(f"[VAULT] loop error: {e}")
            time.sleep(SCAN_INTERVAL_S)

    _thread = threading.Thread(target=_loop, daemon=True, name="SML-Vault")
    _thread.start()
