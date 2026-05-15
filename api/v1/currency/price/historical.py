"""
/api/v1/currency/price/historical — FX pair history (yfinance).
Expected: GET ?symbol=EURUSD&interval=1d&start_date=2024-01-01
"""
from http.server import BaseHTTPRequestHandler
import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), *[".."] * 5))
from _base import parse_query, send_json, send_cors_preflight


def _yf_pair(sym: str) -> str:
    sym = sym.upper().replace("-", "").replace("/", "").replace("=X", "")
    if not sym.endswith("=X"):
        sym = sym + "=X"
    return sym


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        send_cors_preflight(self)

    def do_GET(self):
        import yfinance as yf
        try:
            q = parse_query(self)
            sym = _yf_pair(q.get("symbol", "EURUSD"))
            interval = q.get("interval", "1d")
            start = q.get("start_date")
            t = yf.Ticker(sym)
            hist = t.history(start=start, interval=interval, auto_adjust=True) if start \
                else t.history(period="1mo", interval=interval, auto_adjust=True)
            results = [
                {"date": str(dt.date()), "open": round(float(row["Open"]), 6),
                 "high": round(float(row["High"]), 6), "low": round(float(row["Low"]), 6),
                 "close": round(float(row["Close"]), 6), "volume": int(row.get("Volume", 0))}
                for dt, row in hist.iterrows()
            ]
            send_json(self, {"results": results})
        except Exception as exc:
            send_json(self, {"results": [], "error": str(exc)}, 500)

    def log_message(self, *args):
        pass
