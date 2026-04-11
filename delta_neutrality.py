"""
SQUEEZE OS v4.5 — Delta Neutrality Engine
══════════════════════════════════════════
Calculates beta-adjusted market exposure across all active positions.
Standardizes risk against SPY/QQQ benchmarks.
"""
import logging
from typing import Dict, List, Any, Optional
import numpy as np
from scipy import stats

logger = logging.getLogger(__name__)

# Fallback Beta Estimates (used only when live calculation unavailable)
FALLBACK_BETAS = {
    "AMC": 2.45, "GME": 2.15, "XRT": 1.45, "IWM": 1.15, "QQQ": 1.25,
    "SPY": 1.00, "XRP": 1.80, "NVDA": 1.65, "TSLA": 1.75, "AAPL": 0.95,
    "TLT": -0.45, "GLD": 0.15, "DXY": -0.65, "KRE": 1.55, "HYG": 0.85,
    "IJR": 1.10 # Small-cap proxy
}

class DeltaNeutralityEngine:
    def __init__(self, execution_engine, rmre_bridge=None):
        self.execution = execution_engine
        self.rmre = rmre_bridge

    def calculate_live_beta(
        self,
        symbol: str,
        history_data: List[float],
        benchmark_history: List[float]
    ) -> Optional[float]:
        """
        Calculate beta using linear regression of asset returns vs benchmark returns.

        Args:
            symbol: Asset symbol (for logging)
            history_data: Historical price data for the asset
            benchmark_history: Historical price data for benchmark (SPY)

        Returns:
            Beta coefficient, or None if calculation fails
        """
        try:
            if not history_data or not benchmark_history:
                logger.warning(f"Insufficient history data for {symbol} - cannot calculate live beta")
                return None

            if len(history_data) < 2 or len(benchmark_history) < 2:
                logger.warning(f"History too short for {symbol} - cannot calculate live beta")
                return None

            if len(history_data) != len(benchmark_history):
                logger.warning(f"Mismatched history lengths for {symbol} - cannot calculate live beta")
                return None

            # Calculate returns
            asset_returns = np.diff(history_data) / np.array(history_data[:-1])
            benchmark_returns = np.diff(benchmark_history) / np.array(benchmark_history[:-1])

            # Handle NaN or inf values
            valid_mask = np.isfinite(asset_returns) & np.isfinite(benchmark_returns)
            if not np.any(valid_mask):
                logger.warning(f"No valid return data for {symbol} - cannot calculate live beta")
                return None

            asset_returns = asset_returns[valid_mask]
            benchmark_returns = benchmark_returns[valid_mask]

            if len(asset_returns) < 2:
                logger.warning(f"Insufficient valid data for {symbol} after filtering - cannot calculate live beta")
                return None

            # Linear regression: asset_returns = alpha + beta * benchmark_returns
            slope, intercept, r_value, p_value, std_err = stats.linregress(
                benchmark_returns,
                asset_returns
            )

            logger.info(
                f"Live beta calculated for {symbol}: {slope:.4f} "
                f"(R²={r_value**2:.4f}, p={p_value:.4f})"
            )
            return slope

        except Exception as e:
            logger.error(f"Error calculating live beta for {symbol}: {str(e)}")
            return None

    def _get_dynamic_beta(self, symbol: str) -> float:
        """
        Regime-Aware Beta Adjustment.
        Attempts to compute live beta from historical data.
        Falls back to hardcoded estimates with warning if data unavailable.
        In VOLATILE or CONFLICT regimes, we stress-test by increasing beta by 20%.
        """
        base_beta = None

        # Try to get historical data for live calculation
        if self.execution and hasattr(self.execution, 'get_price_history'):
            try:
                history = self.execution.get_price_history(symbol)
                benchmark_history = self.execution.get_price_history('SPY')

                if history and benchmark_history:
                    base_beta = self.calculate_live_beta(symbol, history, benchmark_history)
            except Exception as e:
                logger.debug(f"Could not fetch history for live beta calculation on {symbol}: {str(e)}")

        # Fall back to hardcoded values if live calculation failed or unavailable
        if base_beta is None:
            base_beta = FALLBACK_BETAS.get(symbol, 1.0)
            logger.warning(
                f"Using estimated beta for {symbol} - live calculation unavailable (beta={base_beta})"
            )

        # Apply regime-aware stress adjustment
        if self.rmre:
            try:
                regime = self.rmre.compute_regime(symbol)
                label = regime.get('regime_label', 'UNKNOWN')

                if label in ('CONFLICT', 'VOLATILE'):
                    return base_beta * 1.2
                elif label == 'EXECUTION': # Trending
                    return base_beta * 0.9 # High conviction leads to slightly lower risk stress
            except Exception as e:
                logger.error(f"Error computing regime for {symbol}: {str(e)}")

        return base_beta

    def calculate_basket_delta(self, quotes: Dict[str, Dict]) -> Dict[str, Any]:
        """
        Calculates Net Delta Exposure (Beta-Adjusted).
        Delta Stress = Position Value * Beta
        """
        active_trades: Dict[str, Any] = self.execution.active_trades if self.execution else {}
        
        total_delta_stress = 0.0
        details = []
        
        for tid, trade in active_trades.items():
            sym = trade['symbol']
            qty = trade['qty']
            side = trade['side']
            
            # Get current price
            price = trade.get('current_price', trade['entry_price'])
            if sym in quotes:
                price = quotes[sym].get('price', price)
            
            # Position Value
            value = qty * price
            if side == 'SELL':
                value *= -1
            
            # Beta Adjustment
            beta = self._get_dynamic_beta(sym)
            delta_stress = value * beta
            
            total_delta_stress += delta_stress
            details.append({
                "symbol": sym,
                "qty": qty,
                "side": side,
                "value": round(value, 2),
                "beta": round(beta, 2),
                "delta_stress": round(delta_stress, 2)
            })
            
        # HJB Optimal Hedge Recommendation
        from hjb_hedging import hjb_engine
        hjb_result = hjb_engine.calculate_optimal_hedge_rate(total_delta_stress)

        # Contextualize: How many SPY shares to hedge?
        spy_price = None
        if "SPY" in quotes:
            spy_price = quotes["SPY"].get('price')

        if spy_price is None:
            spy_price = 500.0  # Default fallback only if unavailable
            logger.warning(
                f"SPY price not available in quotes - using estimated fallback price: ${spy_price}"
            )
            
        hedge_shares = hjb_result['suggested_immediate_hedge'] / spy_price
        
        # Status determined by stress intensity
        rec_status = hjb_result['intensity']
        
        return {
            "total_delta_stress": float(round(total_delta_stress, 2)),
            "hedge_shares_spy": float(round(hedge_shares, 1)),
            "status": "NEUTRAL" if abs(total_delta_stress) < 5000 else "STRESSED" if abs(total_delta_stress) > 50000 else "EXPOSED",
            "rec_status": rec_status,
            "spy_price": spy_price,
            "hjb_metrics": hjb_result,
            "positions": details
        }

    def get_hjb_hedge_instruction(self, quotes: Dict[str, Dict]) -> Optional[Dict[str, Any]]:
        """
        Determines if a shadow hedge trade should be executed.
        """
        delta_data = self.calculate_basket_delta(quotes)
        shares = delta_data['hedge_shares_spy']
        
        # Threshold: Only hedge if > 10 shares of SPY needed (~$5k exposure)
        if abs(shares) < 10:
            return None
            
        side = "BUY" if shares > 0 else "SELL"
        return {
            "symbol": "SPY",
            "side": side,
            "qty": abs(int(shares)),
            "reason": f"HJB Delta Neutralization | Stress: ${delta_data['total_delta_stress']}"
        }
