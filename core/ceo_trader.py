"""
SML SQUEEZE OS — CEO TRADER v7.0 (SOVEREIGN AUTOPILOT)
═══════════════════════════════════════════════════════

Council → Kelly → Tradier. No hardcoded values. No simulation.
Every parameter driven by env vars or live API calls.

FLOW:
  1. Market hours gate (9:30–15:45 ET, Mon–Fri)
  2. Oracle.analyze(symbol) → confidence + directive + regime
  3. Confidence filter  (AUTOPILOT_MIN_CONFIDENCE, default 82)
  4. Regime filter      (block SHIELD / MACRO_COLLAPSE)
  5. Duplicate check    (one position per symbol)
  6. Live account equity from Tradier
  7. Kelly Criterion sizing (fractional, capped by AUTOPILOT_MAX_POSITION_PCT)
  8. ExecutionEngine.execute_trade() → Tradier API → real order
  9. Discord alert + SSE broadcast

ENV VARS (all optional — sensible defaults apply):
  TRADIER_LIVE=true                   Master live-trading kill switch
  AUTOPILOT_SYMBOLS                   Comma-separated watchlist (default: GME,AMC,IWM,SPY,QQQ,MSTR,NVDA,TSLA,PLTR)
  AUTOPILOT_MIN_CONFIDENCE=82         Minimum Oracle confidence to fire (0–100)
  AUTOPILOT_KELLY_FRACTION=0.25       Fraction of full Kelly to use (0.0–1.0)
  AUTOPILOT_MAX_POSITION_PCT=0.05     Max position size as % of account equity
  AUTOPILOT_MAX_ORDER_VALUE=500       Hard $ cap per order (overrides Kelly if lower)
  AUTOPILOT_MAX_CONCURRENT=3          Max concurrent open positions
  AUTOPILOT_COOLDOWN_SECONDS=300      Min seconds between any new entries
  AUTOPILOT_SCAN_INTERVAL=30          Seconds between watchlist sweeps
  AUTOPILOT_REGIME_WHITELIST          Allowed regimes (default: ALPHA_EXPANSION,NEUTRAL)
"""

import os
import time
import threading
import logging
import zoneinfo
from datetime import datetime, time as dtime
from typing import Dict, List, Optional

from core.state import state

logger = logging.getLogger("CEO-Trader")

# ── Market hours (Eastern Time) ───────────────────────────────────────────────
_ET = zoneinfo.ZoneInfo("America/New_York")
_MARKET_OPEN  = dtime(9, 30)
_MARKET_CLOSE = dtime(15, 45)  # cut off 15 min before close — no MOC risk


def _market_open() -> bool:
    """Returns True only during regular market hours Mon–Fri ET."""
    now_et = datetime.now(tz=_ET)
    if now_et.weekday() >= 5:          # Saturday=5, Sunday=6
        return False
    t = now_et.time()
    return _MARKET_OPEN <= t <= _MARKET_CLOSE


# ── Config from env (resolved once per run) ──────────────────────────────────

def _symbols() -> List[str]:
    raw = os.environ.get(
        "AUTOPILOT_SYMBOLS",
        "GME,AMC,IWM,SPY,QQQ,MSTR,NVDA,TSLA,PLTR"
    )
    return [s.strip().upper() for s in raw.split(",") if s.strip()]

def _min_confidence() -> float:
    return float(os.environ.get("AUTOPILOT_MIN_CONFIDENCE", "82"))

def _kelly_fraction() -> float:
    return float(os.environ.get("AUTOPILOT_KELLY_FRACTION", "0.25"))

def _max_position_pct() -> float:
    return float(os.environ.get("AUTOPILOT_MAX_POSITION_PCT", "0.05"))

def _max_order_value() -> float:
    return float(os.environ.get("AUTOPILOT_MAX_ORDER_VALUE", "500"))

def _max_concurrent() -> int:
    return int(os.environ.get("AUTOPILOT_MAX_CONCURRENT", "3"))

def _cooldown() -> float:
    return float(os.environ.get("AUTOPILOT_COOLDOWN_SECONDS", "300"))

def _scan_interval() -> float:
    return float(os.environ.get("AUTOPILOT_SCAN_INTERVAL", "30"))

def _regime_whitelist() -> set:
    raw = os.environ.get("AUTOPILOT_REGIME_WHITELIST", "ALPHA_EXPANSION,NEUTRAL")
    return {r.strip().upper() for r in raw.split(",") if r.strip()}


# ── Kelly Criterion position sizing ──────────────────────────────────────────

def _kelly_qty(confidence: float, tp_pct: float, stop_pct: float,
               equity: float, price: float) -> int:
    """
    Returns integer share quantity using fractional Kelly Criterion.

    f* = (p * b - q) / b
        p = probability of win  (confidence / 100)
        q = 1 - p
        b = win/loss ratio      (tp_pct / stop_pct)

    Position $ = min(f* * kelly_fraction * equity, max_position_pct * equity, max_order_value)
    """
    if price <= 0 or equity <= 0 or stop_pct <= 0 or tp_pct <= 0:
        return 0

    p = confidence / 100.0
    q = 1.0 - p
    b = tp_pct / stop_pct           # win/loss ratio

    kelly_f = (p * b - q) / b
    if kelly_f <= 0:
        return 0                    # negative edge — do not trade

    # Apply fraction + equity cap
    position_value = kelly_f * _kelly_fraction() * equity
    position_value = min(position_value, _max_position_pct() * equity)
    position_value = min(position_value, _max_order_value())

    qty = int(position_value / price)
    return max(qty, 0)


# ── Live account equity fetch ─────────────────────────────────────────────────

def _get_equity(exec_eng) -> float:
    """
    Pulls total equity from the live Tradier account.
    Falls back to AUTOPILOT_MAX_ORDER_VALUE if account call fails.
    """
    try:
        dm = None
        if exec_eng.broker and hasattr(exec_eng.broker, 'tradier'):
            dm = exec_eng.broker
        elif exec_eng.tracker and hasattr(exec_eng.tracker, 'data_manager'):
            dm = exec_eng.tracker.data_manager

        if dm is None:
            # DataManager IS the broker set via set_broker()
            dm = exec_eng.broker

        tradier = getattr(dm, 'tradier', None)
        if tradier and getattr(tradier, 'available', False):
            account_id = tradier.account_id
            if account_id:
                import requests
                url = f"{tradier.base_url}/accounts/{account_id}/balances"
                r = requests.get(url, headers=tradier._headers(), timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    balances = data.get("balances", {})
                    # Tradier returns total_equity under balances.total_equity
                    equity = float(
                        balances.get("total_equity")
                        or balances.get("equity")
                        or balances.get("account_value")
                        or 0
                    )
                    if equity > 0:
                        logger.info(f"[CEO] Live equity: ${equity:,.2f}")
                        return equity
    except Exception as e:
        logger.warning(f"[CEO] Equity fetch failed: {e}")

    # Fallback: use max_order_value as a conservative proxy
    fallback = _max_order_value()
    logger.warning(f"[CEO] Equity unavailable — using fallback ${fallback}")
    return fallback


# ═══════════════════════════════════════════════════════════════════════════════
# CEO TRADER
# ═══════════════════════════════════════════════════════════════════════════════

class CEOTrader:
    """
    Sovereign autopilot. Connects OracleEngine verdicts to live Tradier execution.
    Completely env-var-driven. Zero hardcoded values. Zero simulation data.
    """

    def __init__(self, execution_engine, oracle_engine):
        self.exec   = execution_engine
        self.oracle = oracle_engine
        self.active = False
        self._thread: Optional[threading.Thread] = None
        self.lock = threading.Lock()
        self.last_entry = 0.0          # timestamp of last executed trade
        self._scan_count = 0
        self._fire_count = 0

        logger.info(
            f"[CEO] Sovereign Autopilot Initialized | "
            f"Live={self.exec.live_mode} | "
            f"Symbols={_symbols()} | "
            f"MinConf={_min_confidence()} | "
            f"Kelly={_kelly_fraction()} | "
            f"MaxConcurrent={_max_concurrent()}"
        )

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self):
        with self.lock:
            if not self.active:
                self.active = True
                self._thread = threading.Thread(
                    target=self._run_loop, name="ceo-autopilot", daemon=True
                )
                self._thread.start()
                msg = (
                    f"CEO TRADER ONLINE | Live={self.exec.live_mode} | "
                    f"Watching {len(_symbols())} symbols | "
                    f"Min confidence: {_min_confidence()}"
                )
                state.push_terminal("SYSTEM", msg)
                logger.info(f"[CEO] {msg}")

    def stop(self):
        with self.lock:
            self.active = False
        state.push_terminal("SYSTEM", "CEO TRADER OFFLINE — Manual control only")
        logger.info("[CEO] Autopilot stopped")

    @property
    def status(self) -> dict:
        active_trades = self.exec.get_active_trades()
        return {
            "active":          self.active,
            "live_mode":       self.exec.live_mode,
            "symbols":         _symbols(),
            "min_confidence":  _min_confidence(),
            "kelly_fraction":  _kelly_fraction(),
            "max_position_pct":_max_position_pct(),
            "max_order_value": _max_order_value(),
            "max_concurrent":  _max_concurrent(),
            "cooldown_seconds":_cooldown(),
            "scan_interval":   _scan_interval(),
            "regime_whitelist":list(_regime_whitelist()),
            "market_open":     _market_open(),
            "last_entry":      self.last_entry,
            "cooldown_remaining": max(0, _cooldown() - (time.time() - self.last_entry)),
            "active_positions":len(active_trades),
            "active_symbols":  [t["symbol"] for t in active_trades.values()],
            "scan_count":      self._scan_count,
            "fire_count":      self._fire_count,
        }

    # ── Main Loop ─────────────────────────────────────────────────────────────

    def _run_loop(self):
        """Sovereign execution loop. Runs until self.active = False."""
        logger.info("[CEO] Loop thread started")

        while self.active:
            try:
                state.heartbeats["ceo_trader"] = time.time()

                # ── Gate 1: Market hours ──────────────────────────────────────
                if not _market_open():
                    time.sleep(60)
                    continue

                # ── Gate 2: Global cooldown ───────────────────────────────────
                if (time.time() - self.last_entry) < _cooldown():
                    time.sleep(10)
                    continue

                # ── Gate 3: Max concurrent positions ─────────────────────────
                active_trades = self.exec.get_active_trades()
                if len(active_trades) >= _max_concurrent():
                    time.sleep(30)
                    continue

                # ── Scan watchlist ────────────────────────────────────────────
                self._scan_count += 1
                self._scan_watchlist(active_trades)

                time.sleep(_scan_interval())

            except Exception as e:
                logger.error(f"[CEO] Loop error: {e}", exc_info=True)
                time.sleep(60)

        logger.info("[CEO] Loop thread exited")

    def _scan_watchlist(self, active_trades: dict):
        """Runs Oracle on every symbol. Fires on first qualifying signal."""
        occupied_symbols = {t["symbol"] for t in active_trades.values()}

        for symbol in _symbols():
            if not self.active:
                break

            # Skip symbols already held
            if symbol in occupied_symbols:
                continue

            try:
                verdict = self.oracle.analyze(symbol)
            except Exception as e:
                logger.warning(f"[CEO] Oracle error for {symbol}: {e}")
                continue

            if not verdict:
                continue

            fired = self._evaluate_verdict(symbol, verdict)
            if fired:
                # Only one entry per scan cycle — respect cooldown
                self.last_entry = time.time()
                self.exec.last_autopilot_entry = self.last_entry
                self._fire_count += 1
                break

    # ── Signal Evaluation ─────────────────────────────────────────────────────

    def _evaluate_verdict(self, symbol: str, verdict: dict) -> bool:
        """
        Returns True if a trade was fired.

        Filters (in order):
          1. Directive must be BUY or SELL  (not HOLD / SHIELD)
          2. Confidence >= AUTOPILOT_MIN_CONFIDENCE
          3. Regime in AUTOPILOT_REGIME_WHITELIST
          4. Price > 0
          5. Kelly qty > 0
        """
        directive  = verdict.get("directive", "HOLD")
        confidence = float(verdict.get("confidence", 0))
        regime     = verdict.get("regime", "NEUTRAL")
        price      = float(verdict.get("price", 0))

        # ── Filter 1: Actionable directive only ──────────────────────────────
        if directive not in ("BUY", "SELL"):
            return False

        # ── Filter 2: Confidence threshold ───────────────────────────────────
        if confidence < _min_confidence():
            logger.debug(
                f"[CEO] {symbol} skipped — confidence {confidence:.0f} < {_min_confidence()}"
            )
            return False

        # ── Filter 3: Regime whitelist ────────────────────────────────────────
        if regime not in _regime_whitelist():
            logger.info(f"[CEO] {symbol} blocked — regime {regime} not in whitelist")
            state.push_terminal(
                "AUTOPILOT",
                f"REGIME BLOCK: {symbol} | {regime} not in whitelist | confidence={confidence:.0f}",
                symbol=symbol, score=confidence
            )
            return False

        # ── Filter 4: Price sanity ────────────────────────────────────────────
        if price <= 0:
            return False

        # ── Compute Kelly sizing ──────────────────────────────────────────────
        tp1     = verdict.get("tp1")
        stop    = verdict.get("stop")
        tp_pct  = abs((tp1 - price) / price)  if (tp1  and price) else 0.07
        sl_pct  = abs((stop - price) / price)  if (stop and price) else 0.04

        equity = _get_equity(self.exec)
        qty    = _kelly_qty(confidence, tp_pct, sl_pct, equity, price)

        if qty <= 0:
            logger.info(
                f"[CEO] {symbol} skipped — Kelly returned 0 qty "
                f"(conf={confidence:.0f}, equity=${equity:,.0f}, price=${price:.2f})"
            )
            return False

        # ── All gates cleared — dispatch ──────────────────────────────────────
        reason = (
            f"ORACLE {directive} | confidence={confidence:.0f} | "
            f"regime={regime} | kelly_qty={qty} | {verdict.get('reason','')}"
        )

        logger.info(
            f"[CEO] FIRING: {directive} {qty} {symbol} @ ${price:.2f} | "
            f"conf={confidence:.0f} | regime={regime} | "
            f"TP=${tp1} | SL=${stop} | equity=${equity:,.0f}"
        )

        state.push_terminal(
            "AUTOPILOT",
            f"SIGNAL FIRED: {directive} {qty}x {symbol} @ ${price:.2f} | "
            f"conf={confidence:.0f} | {regime}",
            symbol=symbol, score=confidence,
            extra={
                "directive": directive,
                "qty": qty,
                "price": price,
                "tp1": tp1,
                "stop": stop,
                "confidence": confidence,
                "regime": regime,
                "reason": verdict.get("reason", ""),
            }
        )

        result = self.exec.execute_trade(symbol, directive, qty, price, reason=reason)

        if isinstance(result, dict) and result.get("status") == "OPEN":
            logger.info(f"[CEO] Trade confirmed: {result.get('id')} | mode={result.get('mode')}")
            state.push_terminal(
                "AUTOPILOT",
                f"ORDER CONFIRMED: {result.get('id')} | "
                f"{'LIVE TRADIER' if self.exec.live_mode else 'SHADOW'} | "
                f"{directive} {qty}x {symbol}",
                symbol=symbol, score=confidence,
                extra=result
            )
            return True

        logger.warning(f"[CEO] Trade rejected/filtered: {result}")
        return False
