"""
/api/v1/equity/price/quote — Stock quote (yfinance).
Expected: GET ?symbol=AAPL&provider=yfinance
"""
from http.server import BaseHTTPRequestHandler
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
from _base import parse_query, send_json, send_cors_preflight


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        send_cors_preflight(self)

    def do_GET(self):
        import yfinance as yf
        try:
            q = parse_query(self)
            sym = q.get("symbol", "SPY").upper()
            t = yf.Ticker(sym)
            info = t.fast_info
            hist = t.history(period="2d")
            prev_close = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else None
            last = float(info.last_price or 0)
            send_json(self, {
                "results": [{
                    "symbol": sym,
                    "last_price": last,
                    "open": float(info.open or 0),
                    "high": float(info.day_high or 0),
                    "low": float(info.day_low or 0),
                    "prev_close": prev_close,
                    "volume": int(info.last_volume or 0),
                    "year_high": float(info.year_high or 0),
                    "year_low": float(info.year_low or 0),
                    "market_cap": float(info.market_cap or 0),
                    "currency": "USD",
                }]
            })
        except Exception as exc:
            send_json(self, {"results": [], "error": str(exc)}, 500)

    def log_message(self, *args):
        pass
