"""
/api/v1/index/price/historical — Index OHLCV (yfinance).
Expected: GET ?symbol=^GSPC&interval=1d&start_date=2024-01-01
"""
from http.server import BaseHTTPRequestHandler
import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), *[".."] * 5))
from _base import parse_query, send_json, send_cors_preflight

# Map Bloomberg-style index symbols to yfinance format
_ALIAS = {
    "SPX": "^GSPC", "NDX": "^NDX", "RUT": "^RUT",
    "DJI": "^DJI", "VIX": "^VIX",
}


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        send_cors_preflight(self)

    def do_GET(self):
        import yfinance as yf
        try:
            q = parse_query(self)
            sym = q.get("symbol", "^GSPC").upper()
            sym = _ALIAS.get(sym, sym)
            interval = q.get("interval", "1d")
            start = q.get("start_date")
            t = yf.Ticker(sym)
            hist = t.history(start=start, interval=interval, auto_adjust=True) if start \
                else t.history(period="1mo", interval=interval, auto_adjust=True)
            results = [
                {
                    "date": str(dt.date()),
                    "open": round(float(row["Open"]), 4),
                    "high": round(float(row["High"]), 4),
                    "low": round(float(row["Low"]), 4),
                    "close": round(float(row["Close"]), 4),
                    "volume": int(row["Volume"]),
                }
                for dt, row in hist.iterrows()
            ]
            send_json(self, {"results": results})
        except Exception as exc:
            send_json(self, {"results": [], "error": str(exc)}, 500)

    def log_message(self, *args):
        pass
