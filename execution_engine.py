"""
SQUEEZE OS v4.5 — Shadow Trading & BYOK Execution Engine
════════════════════════════════════════════════════════
High-precision order management tethered to user API keys.
Supports "Shadow" (simulated) and "Live" execution modes.
"""
import os
import json
import time
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from threading import Lock
from delta_neutrality import DeltaNeutralityEngine

logger = logging.getLogger(__name__)

class ExecutionEngine:
    def __init__(self, schwab_api, rmre_bridge, performance_tracker=None):
        self.schwab = schwab_api
        self.rmre = rmre_bridge
        self.tracker = performance_tracker
        self.lock = Lock()
        
        self.live_mode = False # Default to Shadow Mode for safety
        self.max_order_value = 500.0
        self.schwab_account_hash = None # Cached on-demand
        
        # --- AUTOPILOT GUARDRAILS ---
        self.max_autopilot_trades = 3
        self.autopilot_cooldown = 900 # 15 mins
        self.last_autopilot_entry = 0
        
        self.trade_log_path = 'trade_log.json'
        self.active_trades: Dict[str, Dict] = {}
        self.load_trades()
        
        # Phase 2: Risk Management
        self.delta_engine = DeltaNeutralityEngine(self, rmre_bridge)

    def load_trades(self):
        if os.path.exists(self.trade_log_path):
            try:
                with open(self.trade_log_path, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self.active_trades = data.get('active', {})
                    elif isinstance(data, list):
                        # Convert list format to dict format for v4.5+ consistency
                        self.active_trades = {t.get('id', f"tr_{i}"): t for i, t in enumerate(data)}
                    
                    # Cleanup: Ensure all loaded trades are dictionaries
                    self.active_trades = {k: v for k, v in self.active_trades.items() if isinstance(v, dict)}
                    logger.info(f"[EXECUTION] Loaded {len(self.active_trades)} active trades.")
            except Exception as e:
                logger.error(f"[EXECUTION] Load error: {e}")
                self.active_trades = {}

    def get_active_trades(self) -> List[Dict]:
        """Returns list of all open positions with guaranteed JSON serialization."""
        with self.lock:
            try:
                final = []
                for tid, t in self.active_trades.items():
                    # Create a clean copy of the trade to prevent serialization issues
                    # with potentially non-primitive objects (locks, class instances, etc.)
                    clean_trade = {
                        "id": str(t.get('id', tid)),
                        "symbol": str(t.get('symbol', 'UNKNOWN')),
                        "side": str(t.get('side', 'BUY')),
                        "qty": int(t.get('qty', 0)),
                        "entry_price": float(t.get('entry_price', 0.0)),
                        "current_price": float(t.get('current_price', 0.0)),
                        "sl": float(t.get('sl', 0.0)),
                        "tp": float(t.get('tp', 0.0)),
                        "status": str(t.get('status', 'OPEN')),
                        "opened_at": float(t.get('opened_at', time.time())),
                        "regime": str(t.get('regime', 'UNKNOWN')),
                        "net_pressure": float(t.get('net_pressure', 0.0)),
                        "hurst": float(t.get('hurst', 0.5)),
                        "validation_reason": str(t.get('validation_reason', '')),
                        "is_hedge": bool(t.get('is_hedge', False)),
                        "pnl": float(t.get('pnl', 0.0)),
                        "pnl_pct": float(t.get('pnl_pct', 0.0))
                    }
                    final.append(clean_trade)
                    
                # Sort by opened_at descending
                return sorted(final, key=lambda x: x.get('opened_at', 0.0), reverse=True)
            except Exception as e:
                logger.error(f"[EXECUTION] get_active_trades error: {e}")
                return []

    def save_trades(self):
        with self.lock:
            try:
                # Load existing log to maintain history
                history = []
                if os.path.exists(self.trade_log_path):
                    with open(self.trade_log_path, 'r') as f:
                        old_data = json.load(f)
                        history = old_data.get('history', [])
                
                data = {
                    'active': self.active_trades,
                    'history': history,
                    'last_updated': time.time()
                }
                with open(self.trade_log_path, 'w') as f:
                    json.dump(data, f, indent=4)
            except Exception as e:
                logger.error(f"[EXECUTION] Save error: {e}")

    def should_execute(self, symbol: str, side: str) -> Dict[str, Any]:
        """
        Institutional Filter: Hurst-Regime Validation.
        Enforces entry ONLY in trending regimes with high hurst conviction.
        """
        if not self.rmre:
            return {"allow": True, "reason": "RMRE Offline - Neutral Entry"}
            
        try:
            regime = self.rmre.compute_regime(symbol)
            hurst = regime.get('hurst_val', 0.5)
            label = regime.get('regime_label', 'UNKNOWN')
            
            # Law 1: Hurst Filtering
            # Hurst > 0.55 indicates institutional trending conviction
            is_trending = hurst > 0.55
            
            # Law 2: Regime Filtering
            # Entry allowed in EXECUTION (Trending) or CONFLICT (Early Squeeze Setup)
            allow_regime = label in ('EXECUTION', 'CONFLICT')
            
            if is_trending and allow_regime:
                return {"allow": True, "reason": f"VALIDATED: {label} Regime | Hurst: {hurst:.2f}"}
            
            # Rejection Logic
            if not is_trending:
                return {"allow": False, "reason": f"FILTERED: Lack of Hurst Conviction ({hurst:.2f})"}
            if not allow_regime:
                return {"allow": False, "reason": f"FILTERED: Invalid Regime State ({label})"}
                
            return {"allow": False, "reason": "FILTERED: Risk/Regime Mismatch"}
        except Exception as e:
            logger.error(f"[EXECUTION] Filtering Error: {e}")
            return {"allow": True, "reason": "Bypass Error - Safety Default"}

    def execute_shadow_trade(self, symbol: str, side: str, quantity: int, price: float):
        """
        Executes a 'Shadow' trade with realistic slippage and automated risk ranges.
        """
        if self.live_mode:
            return self.execute_live_trade(symbol, side, quantity, price)

        # 0. Apply Institutional Filtering
        validation = self.should_execute(symbol, side)
        if not validation['allow']:
            msg = f"[SHADOW] Trade Filtered: {symbol} - {validation['reason']}"
            logger.warning(msg)
            return {"status": "FILTERED", "reason": validation['reason']}

        logger.info(f"[SHADOW] Executing {side} {quantity} {symbol} @ {price} | {validation['reason']}")
        
        # 1. Apply Institutional Slippage (1-2 ticks)
        slippage = 0.01 if side == 'BUY' else -0.01
        entry_price = price + slippage
        
        # 2. Extract Risk Ranges from RMRE
        ranges = {}
        regime_label = 'UNKNOWN'
        net_pressure = 0
        hurst_val = 0.5
        
        if self.rmre and hasattr(self.rmre, 'compute_regime'):
            try:
                regime = self.rmre.compute_regime(symbol)
                ranges = regime.get('risk_ranges', {})
                regime_label = regime.get('regime_label', 'UNKNOWN')
                net_pressure = regime.get('net_pressure', 0)
                hurst_val = regime.get('hurst_val', 0.5)
            except Exception as e:
                logger.warning(f"[SHADOW] RMRE compute error: {e}")
        
        # Automated TP/SL Logic based on Swing (IT) Profile
        it_range = ranges.get('it', {})
        sl = float(it_range.get('low', entry_price * 0.95))
        tp = float(it_range.get('high', entry_price * 1.05))
        
        # 3. Regime-Aware Risk Tuning
        if regime_label == 'CONFLICT':
            dist = abs(entry_price - sl)
            sl = entry_price - (dist * 0.8) if side == 'BUY' else entry_price + (dist * 0.8)
        elif regime_label == 'EXECUTION':
            dist = abs(entry_price - tp)
            tp = entry_price + (dist * 1.15) if side == 'BUY' else entry_price - (dist * 1.15)

        trade_id = f"SHADOW_{symbol}_{int(time.time())}"
        
        trade = {
            'id': trade_id,
            'symbol': symbol,
            'side': side,
            'qty': quantity,
            'entry_price': entry_price,
            'current_price': entry_price,
            'sl': sl,
            'tp': tp,
            'status': 'OPEN',
            'opened_at': time.time(),
            'regime': regime_label,
            'net_pressure': net_pressure,
            'hurst': hurst_val,
            'validation_reason': validation['reason']
        }
        
        with self.lock:
            self.active_trades[trade_id] = trade
        
        self.save_trades()
        return trade

    def execute_live_trade(self, symbol: str, side: str, quantity: int, price: float):
        """
        Executes a REAL order on Schwab or Alpaca.
        """
        total_value = quantity * price
        if total_value > self.max_order_value:
            msg = f"🛑 RISK REJECTION: Order value ${total_value:.2f} exceeds limit ${self.max_order_value}"
            logger.error(msg)
            return {"status": "REJECTED", "reason": msg}

        validation = self.should_execute(symbol, side)
        if not validation['allow']:
            logger.warning(f"🛑 LIVE Filtered: {symbol} - {validation['reason']}")
            return {"status": "FILTERED", "reason": validation['reason']}

        logger.info(f"🚀 LIVE EXECUTION: {side} {quantity} {symbol} @ {price}")

        res = {"status": "error", "message": "No broker available"}
        
        if price < 50 and hasattr(self.tracker, 'data_manager') and self.tracker.data_manager.alpaca.available:
            res = self.tracker.data_manager.alpaca.place_order(symbol, quantity, side)
        elif self.schwab and self.schwab.access_token:
            if not self.schwab_account_hash:
                accounts = self.schwab.get_account_numbers()
                if accounts:
                    self.schwab_account_hash = accounts[0].get('hashValue')
            
            if self.schwab_account_hash:
                payload = {
                    "orderType": "MARKET",
                    "session": "NORMAL",
                    "duration": "DAY",
                    "orderStrategyType": "SINGLE",
                    "orderLegCollection": [{
                        "instruction": side.upper(),
                        "quantity": int(quantity),
                        "instrument": {"symbol": symbol, "assetType": "EQUITY"}
                    }]
                }
                # Check for place_order method on schwab_api instance
                if hasattr(self.schwab, 'place_order'):
                    res = self.schwab.place_order(self.schwab_account_hash, payload)

        if res.get('status') == 'success':
            trade_id = f"LIVE_{res.get('order_id') or symbol}_{int(time.time())}"
            trade = {
                'id': trade_id,
                'symbol': symbol,
                'side': side,
                'qty': quantity,
                'entry_price': price,
                'current_price': price,
                'sl': price * 0.95 if side == 'BUY' else price * 1.05,
                'tp': price * 1.15 if side == 'BUY' else price * 0.85,
                'status': 'OPEN',
                'opened_at': time.time(),
                'mode': 'LIVE',
                'order_id': res.get('order_id')
            }
            with self.lock:
                self.active_trades[trade_id] = trade
            self.save_trades()
            return trade
        
        return res

    def execute_hjb_hedge(self, quotes: Dict[str, Dict]):
        """
        Automated HJB Delta Neutralization.
        Synchronizes shadow SPY positions to offset portfolio-wide beta stress.
        """
        if not self.delta_engine:
            return
            
        instruction = self.delta_engine.get_hjb_hedge_instruction(quotes)
        if not instruction:
            # Check if we have an existing hedge that needs clearing
            # If net delta is now near zero, we should close existing SPY hedges
            # (Simplified for v1: only add/adjust)
            return

        # Find existing SPY hedge
        existing_hedge_id = None
        for tid, trade in self.active_trades.items():
            if trade['symbol'] == 'SPY' and trade.get('is_hedge'):
                existing_hedge_id = tid
                break
        
        # If instruction matches existing side/qty (approx), do nothing
        if existing_hedge_id:
            existing = self.active_trades[existing_hedge_id]
            if existing['side'] == instruction['side'] and abs(existing['qty'] - instruction['qty']) < 5:
                return # Already hedged sufficiently
            
            # If side changed or qty differs significantly, close and flip
            logger.info(f"[HEDGE] Adjusting Delta Offset. Closing {existing_hedge_id}")
            self.close_trade(existing_hedge_id)

        # Execute new hedge
        spy_quote = quotes.get('SPY', {})
        price = spy_quote.get('price')
        if price is None:
            logger.warning(f"[HEDGE] SPY price unavailable in quotes, cannot execute hedge")
            return
        logger.info(f"[HEDGE] {instruction['reason']} | Order: {instruction['side']} {instruction['qty']} SPY @ {price}")

        # Bypass normal filtering for hedges
        trade_id = f"HEDGE_SPY_{int(time.time())}"
        trade = {
            'id': trade_id,
            'symbol': 'SPY',
            'side': instruction['side'],
            'qty': instruction['qty'],
            'entry_price': price,
            'current_price': price,
            'sl': 0.0, # Hedges don't have standard SL/TP
            'tp': 0.0,
            'status': 'OPEN',
            'opened_at': time.time(),
            'is_hedge': True,
            'reason': instruction['reason']
        }

        with self.lock:
            self.active_trades[trade_id] = trade
        self.save_trades()

    def update_live_prices(self, quotes: Dict[str, Dict]):
        """Updates active trades with latest market data and checks for exits."""
        with self.lock:
            changed = False
            to_close = []
            
            # Periodically check HJB Delta Neutrality (approx every price loop)
            self.execute_hjb_hedge(quotes)
            
            # Update Delta Stress History for Performance Analytics
            if self.tracker and self.delta_engine:
                delta_data = self.delta_engine.calculate_basket_delta(quotes)
                self.tracker.update_delta_stress(delta_data.get('total_delta_stress', 0.0))
            
            for tid, trade in self.active_trades.items():
                sym = trade['symbol']
                if sym in quotes:
                    price = float(quotes[sym].get('price', trade['current_price']))
                    trade['current_price'] = price
                    
                    # 4. Trailing SL Logic (Only in EXECUTION regime)
                    if trade.get('regime') == 'EXECUTION':
                        if trade['side'] == 'BUY':
                            # Trail by 1.5 ATR approx (using 2% as proxy)
                            new_sl = price * 0.98
                            if new_sl > trade['sl']:
                                trade['sl'] = new_sl
                        else:
                            new_sl = price * 1.02
                            if new_sl < trade['sl']:
                                trade['sl'] = new_sl

                    # Check SL
                    if trade['side'] == 'BUY' and price <= trade['sl']:
                        trade['exit_reason'] = 'STOP_LOSS'
                        to_close.append(tid)
                    elif trade['side'] == 'SELL' and price >= trade['sl']:
                        trade['exit_reason'] = 'STOP_LOSS'
                        to_close.append(tid)
                    
                    # Check TP
                    elif trade['side'] == 'BUY' and price >= trade['tp']:
                        trade['exit_reason'] = 'TAKE_PROFIT'
                        to_close.append(tid)
                    elif trade['side'] == 'SELL' and price <= trade['tp']:
                        trade['exit_reason'] = 'TAKE_PROFIT'
                        to_close.append(tid)
                    
                    changed = True
            
            for tid in to_close:
                self.close_trade(tid)
                
            if changed:
                self.save_trades()

    def get_trade_history(self) -> List[Dict]:
        """Returns last 100 closed trades."""
        if os.path.exists(self.trade_log_path):
            try:
                with open(self.trade_log_path, 'r') as f:
                    data = json.load(f)
                    return data.get('history', [])
            except Exception as e:
                logger.warning(f"[EXECUTION] Failed to read trade history: {e}")
                return []
        return []

    def close_trade(self, trade_id: str):
        if trade_id not in self.active_trades:
            return None
        
        trade = self.active_trades.pop(trade_id)
        trade['status'] = 'CLOSED'
        trade['closed_at'] = time.time()
        trade['pnl'] = (trade['current_price'] - trade['entry_price']) * trade['qty']
        if trade['side'] == 'SELL':
            trade['pnl'] *= -1
            
        # Add to history
        try:
            history = []
            if os.path.exists(self.trade_log_path):
                with open(self.trade_log_path, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        history = data.get('history', [])
                    elif isinstance(data, list):
                        history = data
            
            history.insert(0, trade)
            data_to_save = {
                'active': self.active_trades,
                'history': history[:100],
                'last_updated': time.time()
            }
            with open(self.trade_log_path, 'w') as f:
                json.dump(data_to_save, f, indent=4)
        except Exception as e:
            logger.error(f"[EXECUTION] Close log error: {e}")
        
        # Add to performance tracker
        if self.tracker:
            self.tracker.add_trade_result(trade['pnl'], is_hedge=trade.get('is_hedge', False))
            
        logger.info(f"[EXECUTION] Closed {trade_id} | PnL: ${trade['pnl']:.2f}")
        return trade

class SignalEmitter:
    """Standardized BYOK Signal Emitter for Monetization/API consumption."""
    def __init__(self, engine, analyzer):
        self.engine = engine
        self.analyzer = analyzer

    def emit_package(self, symbol, squeeze_score=0.0, regime_data=None):
        """
        Final data fusion: Squeeze + Gamma + Regime.
        """
        profile = self.engine.get_ticker_profile(symbol) or {}
        
        # Institutional grading logic
        status = "BULLISH EMISSION" if squeeze_score > 60 else "MONITORING"
        
        # Hurst-Regime Filtering (Roadmap Phase 1)
        hurst_val = regime_data.get('hurst_val', 0.5) if regime_data else 0.5
        regime_label = regime_data.get('regime_label', 'UNKNOWN') if regime_data else 'UNKNOWN'
        
        # Determine Convergence & Conviction
        conviction = "HIGH"
        if hurst_val > 0.58:
            status = f"TRENDING {status}"
            conviction = "INSTITUTIONAL"
        elif hurst_val < 0.42:
            status = f"SCALP {status}"
            conviction = "MEAN-REVERTING"
            
        return {
            "symbol": symbol,
            "ts": time.time(),
            "institutional_intel": {
                "inventory_z": profile.get('inventory_z', 0),
                "hjb_rate": profile.get('hjb_hedge_rate', 0),
                "regime": profile.get('profile_shape', 'neutral'),
                "hurst_val": hurst_val,
                "regime_label": regime_label
            },
            "convergence": {
                "beast_score": round(squeeze_score, 1),
                "status": status,
                "conviction": conviction
            },
            "moass_watch": profile.get('inventory_z', 0) > 2.5,
            "verified": squeeze_score > 75 and hurst_val > 0.55
        }
