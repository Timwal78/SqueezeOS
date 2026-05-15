"""
/api/v1/equity/fundamental/dividends — Dividend history via yfinance.
Expected: GET ?symbol=AAPL
"""
from http.server import BaseHTTPRequestHandler
import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), *[".."] * 5))
from _base import parse_query, send_json, send_cors_preflight


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        send_cors_preflight(self)

    def do_GET(self):
        import yfinance as yf
        try:
            q = parse_query(self)
            sym = q.get("symbol", "AAPL").upper()
            divs = yf.Ticker(sym).dividends
            results = [
                {"ex_dividend_date": str(dt.date()), "amount": round(float(amt), 4)}
                for dt, amt in divs.items()
            ]
            results.reverse()
            send_json(self, {"results": results[:20]})
        except Exception as exc:
            send_json(self, {"results": [], "error": str(exc)}, 500)

    def log_message(self, *args):
        pass
