import os
import time
import math
import logging
import requests
from datetime import datetime, timedelta

logger = logging.getLogger("IWM-0DTE")

class IwmOdteEngine:
    """
    Specialized IWM 0DTE Institutional Scanner.
    Ports logic from the Node.js upgrade package to Python.
    """

    def __init__(self, data_manager):
        self.dm = data_manager
        self.underlying = "IWM"
        self.max_dte = 10
        self.min_delta = 0.25
        self.max_delta = 0.45
        self.max_spread_pct = 0.18
        self.max_contracts = 180

    def get_realized_vol(self, bars):
        """Calculates 30-day realized volatility."""
        if not bars or len(bars) < 8:
            return None
        
        returns = []
        for i in range(1, len(bars)):
            try:
                c1 = bars[i-1].get('c')
                c2 = bars[i].get('c')
                if c1 and c2:
                    returns.append(math.log(c2 / c1))
            except Exception:
                continue
        
        if len(returns) < 7:
            return None
            
        mean = sum(returns) / len(returns)
        variance = sum([(r - mean)**2 for r in returns]) / max(1, len(returns) - 1)
        return math.sqrt(variance) * math.sqrt(252)

    def score_contract(self, contract, snapshot, underlying_price, rv):
        """Institutional scoring logic for a single option contract."""
        side = contract.get('side', '').lower()
        strike = float(contract.get('strike_price', 0))
        sym = contract.get('symbol', '')
        
        # Pull snapshot data
        quote = snapshot.get('latest_quote', snapshot.get('quote', {}))
        trade = snapshot.get('latest_trade', snapshot.get('trade', {}))
        greeks = snapshot.get('greeks', {})
        iv = float(snapshot.get('implied_volatility', snapshot.get('iv', 0)))
        
        bid = float(quote.get('bp', quote.get('bid_price', 0)))
        ask = float(quote.get('ap', quote.get('ask_price', 0)))
        
        # Calculate mid price
        price = None
        if bid > 0 and ask > 0:
            price = (bid + ask) / 2
        else:
            price = float(trade.get('p', trade.get('price', 0)))
            
        if not price or price <= 0:
            return None

        # Spread logic
        spread_pct = 999
        if bid > 0 and ask > 0:
            spread_pct = (ask - bid) / ((ask + bid) / 2)

        delta = float(greeks.get('delta', 0))
        gamma = float(greeks.get('gamma', 0))
        theta = float(greeks.get('theta', 0))
        vega = float(greeks.get('vega', 0))
        
        abs_delta = abs(delta)
        
        # DTE calculation
        exp_str = contract.get('expiration_date', '')
        try:
            exp_dt = datetime.strptime(exp_str, '%Y-%m-%d')
            today = datetime.now()
            days = (exp_dt - today).days + 1
        except Exception:
            days = 999

        iv_rv_ratio = (iv / rv) if rv and iv else None

        score = 0
        notes = []
        
        # Delta sweet spot
        if self.min_delta <= abs_delta <= self.max_delta:
            score += 25
            notes.append('delta sweet spot')
        elif 0.18 <= abs_delta <= 0.55:
            score += 10
            
        # DTE acceleration
        if days <= 1:
            score += 18
            notes.append('0-1DTE acceleration')
        elif days <= 5:
            score += 12
        else:
            score += 7
            
        # Spread liquidity
        if spread_pct <= self.max_spread_pct:
            score += 18
            notes.append('tradable spread')
        elif spread_pct <= 0.30:
            score += 6
            
        # Gamma weighting
        if gamma > 0:
            score += min(18, gamma * 150)
            
        # IV/RV balance
        if iv_rv_ratio:
            if 0.85 <= iv_rv_ratio <= 1.65:
                score += 12
                notes.append('IV/RV balanced')
            elif iv_rv_ratio > 1.65:
                score += 4
                notes.append('IV rich / debit caution')
            else:
                score += 5
                notes.append('IV cheap / move must arrive')

        # Near money bonus
        if underlying_price > 0:
            moneyness = (underlying_price - strike) / underlying_price if side == 'call' else (strike - underlying_price) / underlying_price
            if abs(moneyness) < 0.012:
                score += 10
                notes.append('near money')
            
        # Cheap premium bonus
        if price <= 5.00:
            score += 6
            notes.append('cheap premium')

        return {
            "symbol": sym,
            "side": side,
            "expiration": exp_str,
            "dte": days,
            "strike": strike,
            "bid": bid,
            "ask": ask,
            "mid": price,
            "spread_pct": spread_pct,
            "delta": delta,
            "gamma": gamma,
            "theta": theta,
            "vega": vega,
            "iv": iv,
            "iv_rv_ratio": iv_rv_ratio,
            "underlying_price": underlying_price,
            "score": round(score),
            "notes": notes
        }

    def get_parity_watch(self, scored):
        """Monitors put-call parity gaps."""
        by_key = {}
        for x in scored:
            key = f"{x['expiration']}|{x['strike']}"
            if key not in by_key:
                by_key[key] = {}
            by_key[key][x['side']] = x
            
        rows = []
        for key, pair in by_key.items():
            if 'call' in pair and 'put' in pair:
                c = pair['call']
                p = pair['put']
                if c['mid'] and p['mid']:
                    try:
                        exp, strike_str = key.split('|')
                        strike = float(strike_str)
                        synthetic = c['mid'] - p['mid'] + strike
                        gap = synthetic - c['underlying_price']
                        rows.append({
                            "expiration": exp,
                            "strike": strike,
                            "synthetic": synthetic,
                            "actual": c['underlying_price'],
                            "gap": gap,
                            "abs_gap": abs(gap)
                        })
                    except Exception:
                        continue
        
        rows.sort(key=lambda x: -x['abs_gap'])
        return rows[:8]

    def run_scan(self):
        """Executes full IWM 0DTE institutional scan."""
        try:
            # 1. Get latest stock price
            stock_data = self.dm.get_quotes([self.underlying])
            if not stock_data or self.underlying not in stock_data:
                return {"error": "Failed to fetch underlying price"}
            
            price = stock_data[self.underlying].get('price', 0)
            
            # 2. Get daily bars for RV
            bars = self.dm.get_historical_bars(self.underlying, timeframe='1Day', limit=40)
            rv = self.get_realized_vol(bars)
            
            # 3. Get options contracts
            # Ensure DataManager has this method or use alpaca directly if possible
            contracts = []
            try:
                # Assuming DataManager wraps this or we can access alpaca
                if hasattr(self.dm, 'get_option_contracts'):
                    contracts = self.dm.get_option_contracts(self.underlying, max_dte=self.max_dte)
                elif hasattr(self.dm, 'alpaca'):
                    contracts = self.dm.alpaca.get_option_contracts(self.underlying, max_dte=self.max_dte)
            except Exception as e:
                logger.error(f"Failed to fetch contracts: {e}")
                return {"error": f"Contract fetch failed: {e}"}
            
            if not contracts:
                return {"error": "No option contracts found"}
                
            # Filter and sort by ATM distance
            candidates = sorted(
                contracts,
                key=lambda c: abs(float(c.get('strike_price', 0)) - price)
            )[:self.max_contracts]
            
            # 4. Get snapshots
            symbols = [c['symbol'] for c in candidates]
            snaps = {}
            try:
                if hasattr(self.dm, 'get_option_snapshots'):
                    snaps = self.dm.get_option_snapshots(symbols)
                elif hasattr(self.dm, 'alpaca'):
                    snaps = self.dm.alpaca.get_option_snapshots(symbols)
            except Exception as e:
                logger.error(f"Failed to fetch snapshots: {e}")
            
            # 5. Score
            scored = []
            for c in candidates:
                snap = snaps.get(c['symbol'])
                if snap:
                    s = self.score_contract(c, snap, price, rv)
                    if s and s['mid'] and abs(s['delta']) > 0:
                        scored.append(s)
            
            scored.sort(key=lambda x: -x['score'])
            
            calls = [x for x in scored if x['side'] == 'call'][:12]
            puts = [x for x in scored if x['side'] == 'put'][:12]
            
            # Bias Detection
            c_score = sum([x['score'] for x in calls[:5]])
            p_score = sum([x['score'] for x in puts[:5]])
            bias = "TWO-WAY / WAIT"
            if c_score > p_score * 1.12: bias = "CALL BIAS"
            elif p_score > c_score * 1.12: bias = "PUT BIAS"
            
            return {
                "generated_at": datetime.now().isoformat(),
                "underlying": {"symbol": self.underlying, "price": price},
                "rv_30d": rv,
                "bias": bias,
                "best": scored[0] if scored else None,
                "top": scored[:20],
                "calls": calls,
                "puts": puts,
                "parity_watch": self.get_parity_watch(scored)
            }
            
        except Exception as e:
            logger.error(f"IWM Scan failed: {e}", exc_info=True)
            return {"error": str(e)}
