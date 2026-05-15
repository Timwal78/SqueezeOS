"""
/api/v1/equity/price/historical — OHLCV history (yfinance).
Expected: GET ?symbol=AAPL&interval=1d&start_date=2024-01-01
"""
from http.server import BaseHTTPRequestHandler
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))))
from _base import parse_query, send_json, send_cors_preflight


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        send_cors_preflight(self)

    def do_GET(self):
        import yfinance as yf
        try:
            q = parse_query(self)
            sym = q.get("symbol", "SPY").upper()
            interval = q.get("interval", "1d")
            start = q.get("start_date")
            period = "1y" if not start else None
            t = yf.Ticker(sym)
            if start:
                hist = t.history(start=start, interval=interval, auto_adjust=True)
            else:
                hist = t.history(period=period, interval=interval, auto_adjust=True)
            results = []
            for dt, row in hist.iterrows():
                results.append({
                    "date": str(dt.date()),
                    "open": round(float(row["Open"]), 4),
                    "high": round(float(row["High"]), 4),
                    "low": round(float(row["Low"]), 4),
                    "close": round(float(row["Close"]), 4),
                    "volume": int(row["Volume"]),
                })
            send_json(self, {"results": results})
        except Exception as exc:
            send_json(self, {"results": [], "error": str(exc)}, 500)

    def log_message(self, *args):
        pass
