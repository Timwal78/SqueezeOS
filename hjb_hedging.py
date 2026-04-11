"""
SQUEEZE OS v4.5 — HJB Optimal Control Engine
════════════════════════════════════════════
Calculates the dynamic hedge rate using a Hamilton-Jacobi-Bellman (HJB) 
Optimal Control framework. 

Model: 
Min J = E[ integral( risk_penalty * variance + trading_cost * hedge_speed^2 ) ]
Result: Linear Feedback Regulator for optimal inventory liquidation/hedging.
"""
import math
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class HJBOptimalControl:
    def __init__(self, risk_aversion: float = 0.5, liquidity_penalty: float = 0.1):
        self.gamma = risk_aversion # Risk Aversion (lambda)
        self.k = liquidity_penalty # Cost of impact (gamma)
        
    def calculate_optimal_hedge_rate(self, 
                                   current_delta_stress: float, 
                                   volatility: float = 0.02, 
                                   time_horizon: float = 1.0) -> Dict[str, Any]:
        """
        Calculates the optimal hedge rate (percentage of stress to offset).
        
        Args:
            current_delta_stress: Net beta-adjusted exposure in dollars.
            volatility: Expected daily volatility (sigma).
            time_horizon: Control period (T).
            
        Returns:
            Dict containing the optimal hedge amount and rate metrics.
        """
        if abs(current_delta_stress) < 100: # Negligible
            return {
                "optimal_target_exposure": 0.0, 
                "adjustment_speed": 0.0, 
                "suggested_immediate_hedge": 0.0,
                "intensity": "LOW"
            }
            
        # Variance = (Stress * Sigma)^2
        # For HJB, the gain factor 'phi' depends on the ratio of risk to cost.
        phi = math.sqrt(self.gamma * (volatility**2) / self.k) if self.k > 0 else 1.0
        
        # Optimal Hedge Amount (H*)
        # The control u* = -phi * (I - H)
        # In a shadow environment, we output the target hedge displacement.
        target_hedge = -current_delta_stress 
        
        # 'intensity' reflects how aggressively we should move toward the target.
        # High volatility or high risk aversion increases intensity.
        intensity = "MODERATE"
        if phi > 0.8: intensity = "AGGRESSIVE"
        elif phi < 0.2: intensity = "PASSIVE"
        
        return {
            "optimal_target_exposure": float(round(target_hedge, 2)),
            "adjustment_speed": float(round(phi, 3)),
            "suggested_immediate_hedge": float(round(target_hedge * phi, 2)),
            "intensity": intensity,
            "metrics": {
                "risk_aversion": self.gamma,
                "vol_scaled_risk": round(self.gamma * (volatility**2), 6)
            }
        }

# Singleton instance for the engine
hjb_engine = HJBOptimalControl()
