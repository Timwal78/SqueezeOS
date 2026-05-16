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
        self.schwab = schwab_api
        self.rmre = rmre_bridge
        self.tracker = performance_tracker
        self.discord = discord_alerts
        self.lock = Lock()

        # ── LIVE MODE ──
        self.live_mode = os.environ.get('TRADIER_LIVE', 'false').lower() == 'true'
        self.max_order_value = float(os.environ.get('BEAST_MAX_PRICE', '25.0'))
        self.schwab_account_hash = None

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

    def execute_shadow_trade(self, symbol: str, side: str, quantity: int, price: float = 0.0, reason: str = "Signal"):
        validation = self.should_execute(symbol, side)
        if not validation['allow']:
            return {"status": "FILTERED", "reason": validation['reason']}

        trade_id = f"SHADOW_{symbol}_{int(time.time())}"
        trade = {
            'id': trade_id, 'symbol': symbol, 'side': side, 'qty': quantity,
            'entry_price': price, 'current_price': price,
            'sl': price * 0.95 if side == 'BUY' else price * 1.05,
            'tp': price * 1.15 if side == 'BUY' else price * 0.85,
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
            trade = {
                'id': trade_id, 'symbol': symbol, 'side': side, 'qty': quantity,
                'entry_price': price, 'current_price': price,
                'sl': price * 0.96, 'tp': price * 1.12,
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
            try:
                self.tracker.add_trade_result(pnl)
            except Exception:
                pass

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
