"""
/api/v1/crypto/price/historical — Crypto OHLCV (yfinance).
Expected: GET ?symbol=BTC-USD&interval=1d&start_date=2024-01-01
"""
from http.server import BaseHTTPRequestHandler
import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), *[".."] * 5))
from _base import parse_query, send_json, send_cors_preflight


def _yf_sym(sym: str) -> str:
    sym = sym.upper()
    if "-USD" not in sym and "-" not in sym:
        sym = sym + "-USD"
    return sym


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        send_cors_preflight(self)

    def do_GET(self):
        import yfinance as yf
        try:
            q = parse_query(self)
            sym = _yf_sym(q.get("symbol", "BTC-USD"))
            interval = q.get("interval", "1d")
            start = q.get("start_date")
            t = yf.Ticker(sym)
            hist = t.history(start=start, interval=interval, auto_adjust=True) if start \
                else t.history(period="1mo", interval=interval, auto_adjust=True)
            results = [
                {"date": str(dt.date()), "open": round(float(row["Open"]), 2),
                 "high": round(float(row["High"]), 2), "low": round(float(row["Low"]), 2),
                 "close": round(float(row["Close"]), 2), "volume": int(row.get("Volume", 0))}
                for dt, row in hist.iterrows()
            ]
            send_json(self, {"results": results})
        except Exception as exc:
            send_json(self, {"results": [], "error": str(exc)}, 500)

    def log_message(self, *args):
        pass
