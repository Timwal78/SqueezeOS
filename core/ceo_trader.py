"""
SQUEEZE OS v6.6 — CEO Trader (Autonomous Execution)
═══════════════════════════════════════════════════
Master autopilot logic for high-conviction institutional execution.
Orchestrates signal ingestion from Oracle and MMLE into ExecutionEngine.
"""

import time
import threading
import logging
import random
from typing import Dict, List, Optional
from core.state import state

logger = logging.getLogger("CEO-Trader")

class CEOTrader:
    def __init__(self, execution_engine, oracle_engine):
        self.exec = execution_engine
        self.oracle = oracle_engine
        self.active = False
        self._thread = None
        self.lock = threading.Lock()
        
        # Configuration (Inherited from Exec Engine or defaults)
        self.cooldown = getattr(self.exec, 'autopilot_cooldown', 300)
        self.max_trades = getattr(self.exec, 'max_autopilot_trades', 3)
        
        logger.info("[CEO] Trader Initialized | Ready for Sovereign Execution")

    def start(self):
        with self.lock:
            if not self.active:
                self.active = True
                self._thread = threading.Thread(target=self._run_loop, daemon=True)
                self._thread.start()
                state.push_terminal('SYSTEM', "🚀 CEO TRADER ACTIVATED: Sovereign Autopilot Online")
                logger.info("[CEO] Loop Started")

    def stop(self):
        with self.lock:
            self.active = False
            state.push_terminal('SYSTEM', "🛑 CEO TRADER DEACTIVATED: Manual Control Only")
            logger.info("[CEO] Loop Stopped")

    def _run_loop(self):
        """Autonomous execution loop."""
        while self.active:
            try:
                # 1. Heartbeat
                state.heartbeats["ceo_trader"] = time.time()
                
                # 2. Check Cooldown & Limits
                now = time.time()
                last_entry = getattr(self.exec, 'last_autopilot_entry', 0.0)
                if (now - last_entry) < self.cooldown:
                    time.sleep(10)
                    continue
                
                active_trades = self.exec.get_active_trades()
                if len(active_trades) >= self.max_trades:
                    # Monitor exits (ExecutionEngine handles this via update_live_prices in scanner, 
                    # but we can do a safety check here)
                    time.sleep(30)
                    continue

                # 3. Identify High-Conviction Triggers
                trigger = self._find_trigger()
                
                if trigger:
                    self._execute_trigger(trigger)
                
                # Jittered polling
                time.sleep(random.uniform(15, 30))
                
            except Exception as e:
                logger.error(f"[CEO] Loop Error: {e}")
                time.sleep(60)

    def _find_trigger(self) -> Optional[Dict]:
        """
        Polls global state for mission-critical triggers.
        Priority:
        1. Discovery Reversion (90%+)
        2. Beast Squeeze (85%+)
        3. Oracle Master Signal (STRONG)
        """
        with state.lock:
            # A. Discovery Reversion
            reversion_hits = [d for d in state.discovery_results if d.get('triggered', False) and d.get('confidence', 0) >= 90]
            if reversion_hits:
                hit = reversion_hits[0]
                symbol = hit['symbol']
                if not any(t['symbol'] == symbol for t in self.exec.get_active_trades()):
                    side = 'BUY' if 'OVERSOLD' in hit['status'] else 'SELL'
                    return {'symbol': symbol, 'side': side, 'price': hit['price'], 'reason': f"REVERSION {hit['confidence']}%"}

            # B. Beast Squeeze
            squeeze_hits = [s for s in state.scan_results if s.get('squeeze_score', 0) >= 85]
            if squeeze_hits:
                hit = squeeze_hits[0]
                symbol = hit['symbol']
                if not any(t['symbol'] == symbol for t in self.exec.get_active_trades()):
                    side = 'BUY' if hit.get('direction') == 'BULLISH' else 'SELL'
                    return {'symbol': symbol, 'side': side, 'price': hit.get('price', 0), 'reason': f"BEAST SQZ {hit['squeeze_score']}"}

        return None

    def _execute_trigger(self, trigger: Dict):
        symbol = trigger['symbol']
        side = trigger['side']
        price = trigger['price']
        reason = trigger['reason']
        
        # Calculate Qty ($500 risk unit)
        if price > 0:
            qty = max(1, int(500 / price))
        else:
            return

        msg = f"🤖 [CEO] Triggering {side} {qty} {symbol} @ ${price:.2f} | {reason}"
        state.push_terminal('SYSTEM', msg, symbol=symbol)
        logger.info(msg)
        
        # Dispatch to ExecutionEngine
        res = self.exec.execute_trade(symbol, side, qty, price, reason=reason)
        
        if isinstance(res, dict) and res.get('status') == 'OPEN':
            self.exec.last_autopilot_entry = time.time()
            logger.info(f"[CEO] Trade Executed: {res.get('id')}")
        else:
            logger.warning(f"[CEO] Execution Filtered/Failed: {res}")
