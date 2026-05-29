"""
SQUEEZE OS v4.5 — Performance Analytics Engine
══════════════════════════════════════════════
Calculates institutional-grade metrics for verified track records.
"""
import os
import json
import time
import math
import logging
from typing import Dict, List, Optional, Any
from threading import Lock

logger = logging.getLogger(__name__)

class PerformanceTracker:
    def __init__(self, log_path='performance_log.json'):
        self.log_path = log_path
        self.lock = Lock()
        
        # Default stats with explicit types
        self.stats: Dict[str, Any] = {
            'total_trades': 0,
            'wins': 0,
            'losses': 0,
            'total_pnl': 0.0,
            'max_drawdown': 0.0,
            'profit_factor': 0.0,
            'win_rate': 0.0,
            'sharpe_ratio': 0.0,
            'equity_curve': [], # List of {'ts': float, 'pnl': float}
            'hedged_pnl': 0.0, # New field for hedging PnL
            'delta_stress_history': [] # New field for delta stress
        }
        self.load_stats()

    def load_stats(self):
        if os.path.exists(self.log_path):
            try:
                with open(self.log_path, 'r') as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        # Defensive merge to preserve types
                        self.stats['total_trades'] = int(loaded.get('total_trades', 0))
                        self.stats['wins'] = int(loaded.get('wins', 0))
                        self.stats['losses'] = int(loaded.get('losses', 0))
                        self.stats['total_pnl'] = float(loaded.get('total_pnl', 0.0))
                        self.stats['max_drawdown'] = float(loaded.get('max_drawdown', 0.0))
                        self.stats['profit_factor'] = float(loaded.get('profit_factor', 0.0))
                        self.stats['win_rate'] = float(loaded.get('win_rate', 0.0))
                        self.stats['sharpe_ratio'] = float(loaded.get('sharpe_ratio', 0.0))
                        self.stats['hedged_pnl'] = float(loaded.get('hedged_pnl', 0.0)) # Load new field
                        self.stats['delta_stress_history'] = loaded.get('delta_stress_history', []) # Load new field
                        
                        curve = loaded.get('equity_curve', [])
                        if isinstance(curve, list):
                            self.stats['equity_curve'] = curve
            except Exception as e:
                logger.error(f"[PERFORMANCE] Load error: {e}")

    def save_stats(self):
        with self.lock:
            try:
                tmp_path = self.log_path + '.tmp'
                with open(tmp_path, 'w') as f:
                    json.dump(self.stats, f, indent=4)
                os.replace(tmp_path, self.log_path)
            except Exception as e:
                logger.error(f"[PERFORMANCE] Save error: {e}")

    def add_trade_result(self, pnl: float, is_hedge: bool = False):
        """Updates performance metrics with a new trade result."""
        with self.lock:
            pnl_val = float(pnl)
            if is_hedge:
                self.stats['hedged_pnl'] = float(self.stats.get('hedged_pnl', 0.0)) + pnl_val
            
            self.stats['total_pnl'] = float(self.stats['total_pnl']) + pnl_val
            self.stats['total_trades'] = int(self.stats['total_trades']) + 1
            
            if pnl_val > 0:
                self.stats['wins'] = int(self.stats['wins']) + 1
            else:
                self.stats['losses'] = int(self.stats['losses']) + 1
            
            # Update Equity Curve
            curve: List[Dict] = self.stats['equity_curve']
            curve.append({
                'ts': float(time.time()),
                'pnl': float(self.stats['total_pnl'])
            })
            if len(curve) > 1000:
                curve = curve[-1000:]
            self.stats['equity_curve'] = curve
            
            # Recalculate Win Rate
            total = int(self.stats['total_trades'])
            if total > 0:
                self.stats['win_rate'] = float((int(self.stats['wins']) / total) * 100)
            
            self.recalculate_complex_metrics()
            
        self.save_stats()

    def update_delta_stress(self, delta_stress: float):
        """Records the current portfolio-wide delta stress for risk analytics."""
        with self.lock:
            history = self.stats.get('delta_stress_history', [])
            history.append({
                'ts': float(time.time()),
                'stress': float(delta_stress)
            })
            if len(history) > 1000:
                history = history[-1000:]
            self.stats['delta_stress_history'] = history
        self.save_stats()

    def recalculate_complex_metrics(self):
        """Recalculates Sharpe, Drawdown, and Profit Factor from the equity curve."""
        curve: List[Dict] = self.stats.get('equity_curve', [])
        if not curve or len(curve) < 2:
            return

        try:
            pnls: List[float] = []
            for i in range(1, len(curve)):
                c1 = curve[i]
                c0 = curve[i-1]
                diff = float(c1.get('pnl', 0.0)) - float(c0.get('pnl', 0.0))
                pnls.append(diff)
            
            if not pnls: return

            # 1. Profit Factor
            gross_profits = sum(p for p in pnls if p > 0)
            gross_losses = abs(sum(p for p in pnls if p < 0))
            self.stats['profit_factor'] = float(gross_profits / gross_losses) if gross_losses > 0 else float(gross_profits if gross_profits > 0 else 0.0)
            
            # 2. Max Drawdown
            peak = -1e12
            max_dd = 0.0
            for entry in curve:
                p = float(entry.get('pnl', 0.0))
                if p > peak:
                    peak = p
                dd = peak - p
                if dd > max_dd:
                    max_dd = dd
            self.stats['max_drawdown'] = float(max_dd)
            
            # 3. Sharpe Ratio (Institutional Scaling)
            # Use trade-level volatility scaled to an estimated 252-session year
            if len(pnls) >= 3:
                avg_ret = sum(pnls) / len(pnls)
                variance = sum((p - avg_ret) ** 2 for p in pnls) / len(pnls)
                std_dev = math.sqrt(variance)
                
                if std_dev > 0:
                    # Scaling factor: assumes ~10-20 trades/day for a high-freq desk
                    # but we'll use 252 for standard daily equivalence
                    self.stats['sharpe_ratio'] = float((avg_ret / std_dev) * math.sqrt(252))
                else:
                    self.stats['sharpe_ratio'] = 0.0
        except Exception as e:
            logger.error(f"[PERFORMANCE] Recalc error: {e}")

    def get_summary(self) -> Dict:
        with self.lock:
            return self.stats
