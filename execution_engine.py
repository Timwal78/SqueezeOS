"""
SQUEEZE OS v5.0 — Tradier-First Execution Engine
═════════════════════════════════════════════════
Live execution via Tradier (primary) → Alpaca (fallback).
Auto-pilot attributes fully wired for server_v5.py workers.
PDT Shield, Shadow mode, GEX cache, and trade history included.
"""
import os
import json
import time
import logging
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Any
from threading import Lock

try:
    from delta_neutrality import DeltaNeutralityEngine
except ImportError:
    DeltaNeutralityEngine = None

from core.execution_lock import claim_entry

try:
    from BEAST.gex.sml_gex_engine import GEXEngine
    from BEAST.hedger.autonomous_hedger import AutonomousHedger, HedgerConfig
except ImportError:
    GEXEngine = None
    AutonomousHedger = None
    class HedgerConfig:
        def __init__(self, **kw): pass

logger = logging.getLogger(__name__)


class ExecutionEngine:
    def __init__(self, schwab_api, rmre_bridge, performance_tracker=None, discord_alerts=None):
        # `schwab_api` kept in the signature for back-compat with callers that pass it positionally.
        # Tradier-first stack passes None; actual broker is injected later via set_broker().
        self.rmre = rmre_bridge
        self.tracker = performance_tracker
        self.discord = discord_alerts
        self.lock = Lock()

        # ── LIVE MODE ──
        self.live_mode = os.environ.get('TRADIER_LIVE', 'false').lower() == 'true'
        self.max_order_value = float(os.environ.get('BEAST_MAX_PRICE', '25.0'))

        # ── BROKER REFERENCE (Tradier preferred) ──
        # Set after DataManager is available via set_broker()
        self.broker = None

        # ── PDT SHIELD ──
        self.pdt_limit = 3
        self.pdt_window_days = 5
        self.day_trades: List[float] = []

        # ── TRADE LOG ──
        self.trade_log_path = 'trade_log.json'
        self.active_trades: Dict[str, Dict] = {}
        self._trade_history: List[Dict] = []
        self.load_trades()

        # ── AUTO-PILOT STATE (required by server_v5.py worker_autopilot) ──
        self.autopilot_cooldown = 300        # 5-min cooldown between auto entries
        self.last_autopilot_entry = 0.0
        self.max_autopilot_trades = 2        # Max concurrent autopilot positions

        # ── RISK MANAGEMENT ──
        self.atr_multiplier = 1.5
        self.meme_atr_multiplier = 2.5

        # Delta engine — lazy init after broker is set
        self.delta_engine = None

        # ── GEX CACHE ──
        self.gex_cache: Dict[str, Dict] = {}
        self.last_gex_update = 0
        self.beast_hedger = None

        logger.info(f"[EXECUTION] Engine Ready | Live: {self.live_mode} | PDT: {len(self.day_trades)}/3")

    # ─────────────────────────────────────────────────────────────
    # BROKER WIRING
    # ─────────────────────────────────────────────────────────────

    def set_broker(self, data_manager):
        """Wire the preferred broker from DataManager (Tradier > Alpaca)."""
        if data_manager is None:
            return
        tradier = getattr(data_manager, 'tradier', None)
        alpaca = getattr(data_manager, 'alpaca', None)
        if tradier and getattr(tradier, 'available', False):
            self.broker = tradier
            logger.info("[EXECUTION] Broker → Tradier LIVE")
        elif alpaca and getattr(alpaca, 'available', False):
            self.broker = alpaca
            logger.info("[EXECUTION] Broker → Alpaca (fallback)")
        else:
            logger.warning("[EXECUTION] No live broker available — shadow-only mode")

        # Init delta engine now that we have a broker reference
        if DeltaNeutralityEngine:
            try:
                self.delta_engine = DeltaNeutralityEngine(self, self.rmre)
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────
    # PERSISTENCE
    # ─────────────────────────────────────────────────────────────

    def load_trades(self):
        if os.path.exists(self.trade_log_path):
            try:
                with open(self.trade_log_path, 'r') as f:
                    data = json.load(f)
                    self.active_trades = data.get('active', {})
                    self.day_trades = data.get('day_trades', [])
                    self._trade_history = data.get('history', [])
                    self._prune_pdt()
            except Exception as e:
                logger.error(f"[EXECUTION] Load error: {e}")
                self.active_trades = {}
                self.day_trades = []
                self._trade_history = []

    def save_trades(self):
        with self.lock:
            try:
                data = {
                    'active': self.active_trades,
                    'history': self._trade_history,  # 100% FETCH: Full session history preserved
                    'day_trades': self.day_trades,
                    'last_updated': time.time()
                }
                with open(self.trade_log_path, 'w') as f:
                    json.dump(data, f, indent=4)
            except Exception as e:
                logger.error(f"[EXECUTION] Save error: {e}")

    # ─────────────────────────────────────────────────────────────
    # PUBLIC ACCESSORS (required by server_v5.py)
    # ─────────────────────────────────────────────────────────────

    def get_active_trades(self) -> List[Dict]:
        with self.lock:
            return list(self.active_trades.values())

    def get_trade_history(self) -> List[Dict]:
        with self.lock:
            return list(self._trade_history)  # 100% FETCH: No arbitrary truncation

    # ─────────────────────────────────────────────────────────────
    # PDT SHIELD
    # ─────────────────────────────────────────────────────────────

    def _prune_pdt(self):
        now = time.time()
        five_days_ago = now - (self.pdt_window_days * 86400)
        self.day_trades = [t for t in self.day_trades if t > five_days_ago]

    def check_pdt_shield(self) -> bool:
        self._prune_pdt()
        if len(self.day_trades) >= self.pdt_limit:
            logger.warning(f"🛑 PDT SHIELD ACTIVE: {len(self.day_trades)}/3 trades used.")
            return False
        return True

    # ─────────────────────────────────────────────────────────────
    # REGIME VALIDATION
    # ─────────────────────────────────────────────────────────────

    def should_execute(self, symbol: str, side: str, is_live: bool = False) -> Dict[str, Any]:
        if not self.rmre:
            return {"allow": True, "reason": "RMRE Offline"}
        try:
            regime = self.rmre.compute_regime(symbol)
            hurst = regime.get('hurst_val', 0.5)
            label = regime.get('regime_label', 'UNKNOWN')
            threshold = 0.62 if is_live else 0.55
            if hurst > threshold and label in ('EXECUTION', 'CONFLICT'):
                return {"allow": True, "reason": f"VALIDATED: {label} | Hurst: {hurst:.2f}"}
            return {"allow": False, "reason": f"REJECTED: Hurst {hurst:.2f} < {threshold}"}
        except Exception as e:
            return {"allow": False, "reason": str(e)}

    # ─────────────────────────────────────────────────────────────
    # ATR
    # ─────────────────────────────────────────────────────────────

    def calculate_atr(self, symbol: str, period: int = 14) -> float:
        if not self.tracker or not self.tracker.data_manager:
            return 0.0
        dm = self.tracker.data_manager
        if not dm.polygon or not dm.polygon.available:
            return 0.0
        try:
            aggs = dm.polygon.get_aggregates(symbol, 1, 'minute', limit=period + 5)
            if not aggs or len(aggs) < period:
                return 0.0
            df = pd.DataFrame(aggs).sort_values('timestamp')
            df['prev_close'] = df['close'].shift(1)
            df['tr'] = np.maximum(
                df['high'] - df['low'],
                np.maximum(abs(df['high'] - df['prev_close']),
                           abs(df['low'] - df['prev_close']))
            )
            return float(df['tr'].tail(period).mean())
        except Exception:
            return 0.0

    # ─────────────────────────────────────────────────────────────
    # TRADE EXECUTION
    # ─────────────────────────────────────────────────────────────

    def execute_trade(self, symbol: str, side: str, quantity: int, price: float, reason: str = "Signal"):
        """Master entry point — routes to live or shadow based on TRADIER_LIVE env."""
        if self.live_mode:
            return self.execute_live_trade(symbol, side, quantity, price, reason)
        return self.execute_shadow_trade(symbol, side, quantity, price, reason)

    def _atr_stop_targets(self, symbol: str, side: str, price: float,
                           fallback_sl_pct: float = 0.04, fallback_tp_pct: float = 0.12) -> Dict[str, float]:
        """
        ATR-based stop-loss/take-profit anchored to `price`, using the
        already-wired atr_multiplier (meme_atr_multiplier for MANDATORY_TICKERS
        — GME/AMC/IWM) via calculate_atr(). These fields existed but were never
        used; SL/TP was hardcoded at fixed percentages regardless of a symbol's
        actual volatility. Falls back to the caller's fixed-percentage bands
        when ATR is unavailable (e.g. no Polygon key configured — calculate_atr
        returns 0.0), so behavior degrades gracefully instead of landing at a
        nonsensical distance.
        """
        try:
            from core.api.market_scanner import MANDATORY_TICKERS  # lazy: avoids a
            # module-load cycle (market_scanner -> core.legacy -> execution_engine)
            is_meme = symbol.upper() in MANDATORY_TICKERS
        except Exception:
            is_meme = False
        mult = self.meme_atr_multiplier if is_meme else self.atr_multiplier
        atr = self.calculate_atr(symbol)
        if atr and atr > 0:
            if side == 'BUY':
                return {"sl": round(price - atr * mult, 4), "tp": round(price + atr * mult * 2.5, 4)}
            return {"sl": round(price + atr * mult, 4), "tp": round(price - atr * mult * 2.5, 4)}
        if side == 'BUY':
            return {"sl": round(price * (1 - fallback_sl_pct), 4), "tp": round(price * (1 + fallback_tp_pct), 4)}
        return {"sl": round(price * (1 + fallback_sl_pct), 4), "tp": round(price * (1 - fallback_tp_pct), 4)}

    def execute_shadow_trade(self, symbol: str, side: str, quantity: int, price: float = 0.0, reason: str = "Signal"):
        validation = self.should_execute(symbol, side)
        if not validation['allow']:
            return {"status": "FILTERED", "reason": validation['reason']}

        trade_id = f"SHADOW_{symbol}_{int(time.time())}"
        levels = self._atr_stop_targets(symbol, side, price, fallback_sl_pct=0.05, fallback_tp_pct=0.15)
        trade = {
            'id': trade_id, 'symbol': symbol, 'side': side, 'qty': quantity,
            'entry_price': price, 'current_price': price,
            'sl': levels['sl'], 'tp': levels['tp'],
            'status': 'OPEN', 'opened_at': time.time(), 'mode': 'SHADOW', 'reason': reason
        }
        with self.lock:
            self.active_trades[trade_id] = trade
        self.save_trades()
        if self.discord:
            try:
                self.discord.fire_beast_trade_alert_full(trade, is_live=False)
            except Exception:
                pass
        return trade

    def execute_live_trade(self, symbol: str, side: str, quantity: int, price: float, reason: str = "Signal"):
        # ── Safety checks ──
        if quantity > 0 and price > 0 and (quantity * price) > self.max_order_value:
            return {"status": "REJECTED", "reason": f"Value ${quantity*price:.2f} exceeds safety limit ${self.max_order_value}"}

        if not self.check_pdt_shield():
            if self.discord:
                try:
                    self.discord.send_alert("⚠️ PDT BLOCK", "Trade rejected — 5-day window exhausted.")
                except Exception:
                    pass
            return {"status": "REJECTED", "reason": "PDT Shield Active"}

        validation = self.should_execute(symbol, side, is_live=True)
        if not validation['allow']:
            return {"status": "FILTERED", "reason": validation['reason']}

        if side == 'BUY':
            # Spread guard — entries only, never exits. A market/marketable buy
            # into a wide bid-ask spread on a thin name eats the whole spread as
            # instant slippage; checked before claim_entry() below so a
            # spread-rejected order doesn't waste the cross-engine claim on a
            # trade we're not actually going to place. Fails open (no check) if
            # a quote isn't available — this only ever blocks on data we
            # actually have, never on missing data.
            max_spread_pct = float(os.environ.get('TRADIER_MAX_SPREAD_PCT', '2.0'))
            if max_spread_pct > 0:
                try:
                    from tradier_api import get_spread_pct
                    spread_pct = get_spread_pct(symbol)
                except Exception:
                    spread_pct = None
                if spread_pct is not None and spread_pct > max_spread_pct:
                    logger.warning(f"[EXEC] {symbol} BUY skipped — spread {spread_pct:.2f}% > {max_spread_pct:.2f}% cap")
                    return {"status": "REJECTED", "reason": f"spread {spread_pct:.2f}% exceeds {max_spread_pct:.2f}% cap"}

            # Cross-engine claim — this Tradier account is also traded by
            # core/api/convergence_bp.py's GOD MODE execution and
            # iam_executor.py's IAM execution, each with their own independent
            # gate. A fresh buy has no natural cap, unlike a sell (checked
            # against the real held quantity right below), so only the entry
            # side needs coordination.
            if not claim_entry(symbol, "LONG_ENTRY", "ceo_trader"):
                logger.info(f"[EXEC] {symbol} LONG entry already claimed by another engine this window — skipping")
                return {"status": "SKIPPED", "reason": "claimed by another engine"}
        else:
            # Position-aware sell — this engine previously placed a bare SELL
            # for whatever quantity the caller computed, with no verification
            # that the account actually held that many shares. Unlike a BUY,
            # an unverified SELL isn't just "extra exposure" — it's a naked
            # short with uncapped downside if nothing (or fewer shares) were
            # actually held. Cap to the real position, same policy already
            # applied to convergence_bp.py and iam_executor.py.
            try:
                from tradier_api import get_position
                position = get_position(symbol)
            except Exception as e:
                logger.error(f"[EXEC] {symbol} position lookup failed: {e} — refusing to sell without verification")
                return {"status": "REJECTED", "reason": f"position lookup failed: {e}"}

            held = int(position["quantity"]) if position and position.get("quantity", 0) > 0 else 0
            if held <= 0:
                logger.info(f"[EXEC] {symbol} SELL signal — no existing long to close, skipping (no shorts)")
                return {"status": "SKIPPED", "reason": "no position to close"}
            if quantity > held:
                logger.warning(f"[EXEC] {symbol} SELL requested {quantity}x but only {held}x held — capping to {held}")
                quantity = held

        logger.info(f"🚀 LIVE ORDER: {side} {quantity} {symbol} @ {price:.2f} | {reason}")

        # ── Route to broker ──
        res = {"status": "error", "message": "No broker configured"}
        if self.broker and getattr(self.broker, 'available', False):
            res = self.broker.place_order(symbol, quantity, side)
        else:
            # Try DataManager providers via tracker
            dm = self.tracker.data_manager if self.tracker else None
            if dm:
                tradier = getattr(dm, 'tradier', None)
                alpaca = getattr(dm, 'alpaca', None)
                if tradier and getattr(tradier, 'available', False):
                    res = tradier.place_order(symbol, quantity, side)
                elif alpaca and getattr(alpaca, 'available', False):
                    res = alpaca.place_order(symbol, quantity, side)

        if res.get('status') == 'success':
            oid = res.get('order_id', str(int(time.time())))
            trade_id = f"LIVE_{symbol}_{oid}"

            # ── Fill verification ── the broker only confirmed the order was
            # ACCEPTED, not that it filled or at what price. Polling here closes
            # that gap: entry_price (and therefore SL/TP) is anchored to the
            # real average fill price when we can confirm one, instead of the
            # pre-trade signal price — which can drift from reality on the thin
            # $1-$50 names this system targets. fill_verified=False downstream
            # means "treat entry_price as an estimate, not a confirmed fill."
            fill_verified = False
            fill_price = price
            try:
                from tradier_api import poll_order_fill
                fill = poll_order_fill(oid)
                if fill.get("filled"):
                    fill_verified = True
                    if fill.get("avg_fill_price"):
                        fill_price = fill["avg_fill_price"]
                else:
                    logger.warning(
                        f"[EXEC] {symbol} order {oid} not confirmed filled after poll "
                        f"(status={fill.get('status')}) — entry_price is the pre-trade signal "
                        f"price, not a verified fill; check the account manually."
                    )
            except Exception as e:
                logger.warning(f"[EXEC] {symbol} fill poll failed: {e} — entry_price unverified")

            if side == 'BUY':
                levels = self._atr_stop_targets(symbol, side, fill_price, fallback_sl_pct=0.04, fallback_tp_pct=0.12)
                trade = {
                    'id': trade_id, 'symbol': symbol, 'side': side, 'qty': quantity,
                    'entry_price': fill_price, 'current_price': fill_price,
                    'signal_price': price, 'fill_verified': fill_verified,
                    'sl': levels['sl'], 'tp': levels['tp'],
                    'status': 'OPEN', 'opened_at': time.time(), 'mode': 'LIVE',
                    'order_id': oid, 'reason': reason
                }
                with self.lock:
                    self.active_trades[trade_id] = trade
                self.save_trades()
                if self.discord:
                    try:
                        self.discord.fire_beast_trade_alert_full(trade, is_live=True)
                    except Exception:
                        pass
                logger.info(f"✅ LIVE TRADE RECORDED: {trade_id}")
                return trade

            # ── Closing SELL ──────────────────────────────────────────────
            # This order reduced/closed an existing long — it never opened a
            # new short (naked shorts are refused above). Close the matching
            # tracked BUY entry/entries at the real fill price instead of
            # recording this as a brand-new "OPEN" position with a synthetic
            # SL/TP. The old behavior left a fictional short sitting in
            # active_trades with stop/target levels for a position the
            # account never actually held — it could later "close" on its
            # own and feed made-up P&L into performance_tracker, while the
            # real BUY entry's tracking was orphaned forever (both Engine 7's
            # liquidation lookup and this file's own bookkeeping depend on
            # active_trades reflecting real positions, not phantom ones).
            # Treats the sell as a full close of every tracked open BUY entry
            # for this symbol — consistent with this method's existing SELL
            # semantics above (cap to `held`, never a partial scale-out).
            closed_trades = []
            with self.lock:
                matching_ids = [
                    tid for tid, t in self.active_trades.items()
                    if t.get('symbol') == symbol and t.get('side') == 'BUY' and t.get('status') == 'OPEN'
                ]
                for tid in matching_ids:
                    self.active_trades[tid]['current_price'] = fill_price
                    closed = self._close_trade_unsafe(tid)
                    if closed:
                        closed_trades.append(closed)

            if not closed_trades:
                # No tracked BUY entry to close (position was opened outside
                # this engine's bookkeeping — e.g. manually, or by another
                # engine). Still record that a real sell happened, as a
                # standalone closed entry, so trade_log.json stays a true
                # record of every live order this engine placed.
                trade = {
                    'id': trade_id, 'symbol': symbol, 'side': side, 'qty': quantity,
                    'entry_price': fill_price, 'current_price': fill_price,
                    'signal_price': price, 'fill_verified': fill_verified,
                    'sl': None, 'tp': None, 'pnl': 0.0,
                    'status': 'CLOSED', 'opened_at': time.time(), 'closed_at': time.time(),
                    'mode': 'LIVE', 'order_id': oid, 'reason': reason,
                }
                with self.lock:
                    self._trade_history.insert(0, trade)
                self.save_trades()
                closed_trades = [trade]
                logger.info(f"[EXEC] {symbol} SELL {quantity}x @ ${fill_price:.2f} closed a position not tracked in active_trades — logged standalone record")
            else:
                self.save_trades()

            logger.info(f"✅ LIVE SELL RECORDED: {trade_id} — closed {len(closed_trades)} tracked position(s) @ ${fill_price:.2f}")
            return closed_trades[-1]

        logger.error(f"🛑 LIVE ORDER FAILED: {res}")
        return res

    # ─────────────────────────────────────────────────────────────
    # PRICE MANAGEMENT & EXIT
    # ─────────────────────────────────────────────────────────────

    def update_live_prices(self, quotes: Dict[str, Dict]):
        with self.lock:
            to_close = []
            for tid, trade in self.active_trades.items():
                sym = trade['symbol']
                if sym in quotes:
                    price = float(quotes[sym].get('price', trade['current_price']))
                    trade['current_price'] = price
                    if trade['side'] == 'BUY':
                        if price <= trade['sl'] or price >= trade['tp']:
                            to_close.append(tid)
                    else:
                        if price >= trade['sl'] or price <= trade['tp']:
                            to_close.append(tid)
            for tid in to_close:
                self._close_trade_unsafe(tid)
            if to_close:
                self.save_trades()

    def close_trade(self, trade_id: str):
        with self.lock:
            result = self._close_trade_unsafe(trade_id)
        self.save_trades()
        return result

    def _close_trade_unsafe(self, trade_id: str):
        """Must be called with self.lock held."""
        if trade_id not in self.active_trades:
            return None
        trade = self.active_trades.pop(trade_id)
        trade['status'] = 'CLOSED'
        trade['closed_at'] = time.time()

        # PDT tracking for live trades opened today
        if trade.get('mode') == 'LIVE':
            opened_day = datetime.fromtimestamp(trade['opened_at']).date()
            if opened_day == datetime.now().date():
                self.day_trades.append(time.time())
                logger.info(f"📊 PDT RECORDED: {len(self.day_trades)}/3")

        pnl = (trade['current_price'] - trade['entry_price']) * trade['qty']
        if trade['side'] == 'SELL':
            pnl *= -1
        trade['pnl'] = pnl

        # Feed CEOTrader's daily-loss circuit breaker (bolted onto this
        # instance via hasattr in core/ceo_trader.py's __init__, not native
        # to ExecutionEngine) — without this, daily_pnl never moves and
        # _check_circuit_breaker() can never trip no matter how much real
        # money is lost in a session.
        if hasattr(self, 'daily_pnl'):
            self.daily_pnl += pnl

        self._trade_history.insert(0, trade)
        # Institutional retention: cap at 10000 entries, no arbitrary truncation during session.
        if len(self._trade_history) > 10000:
            self._trade_history = self._trade_history[:10000]

        if self.discord:
            try:
                color = 0x00FF88 if pnl > 0 else 0xFF4444
                self.discord.send_alert(
                    f"💰 TRADE CLOSED: {trade['symbol']}",
                    f"PnL: **${pnl:+.2f}** | Exit: ${trade['current_price']:.2f}",
                    color=color
                )
            except Exception:
                pass

        if self.tracker:
            self.tracker.add_trade_result(trade['pnl'], is_hedge=trade.get('is_hedge', False))

        logger.info(f"[EXECUTION] Closed {trade_id} | PnL: ${trade['pnl']:.2f}")

        if self.discord:
            try:
                self.discord.fire_beast_exit_alert(trade, is_live=self.live_mode)
            except Exception as e:
                logger.warning(f"[EXECUTION] Exit alert failed: {e}")

        return trade

    # ─────────────────────────────────────────────────────────────
    # GEX / GAMMA WALLS (required by server_v5.py)
    # ─────────────────────────────────────────────────────────────

    def get_gamma_walls(self, symbol: str) -> Dict:
        """Returns GEX metrics for a symbol. Uses cached GEXEngine if available."""
        now = time.time()
        cached = self.gex_cache.get(symbol)
        if cached and (now - cached.get('ts', 0)) < 300:
            return cached

        result = {
            'symbol': symbol,
            'regime': 'NEUTRAL',
            'call_wall': 0.0,
            'put_wall': 0.0,
            'zero_gamma_line': 0.0,
            'max_oi_strike': 0.0,
            'total_gex': 0.0,
            'inventory_z': 0.0,
            'hjb_hedge_rate': 0.0,
            'ts': now
        }

        # Try live GEXEngine if available
        if GEXEngine:
            try:
                dm = self.tracker.data_manager if self.tracker else None
                if dm and dm.polygon.available:
                    gex_eng = GEXEngine(dm.polygon)
                    data = gex_eng.compute(symbol)
                    if data:
                        result.update(data)
                        result['ts'] = now
            except Exception as e:
                logger.debug(f"[GEX] {symbol}: {e}")

        self.gex_cache[symbol] = result
        return result
