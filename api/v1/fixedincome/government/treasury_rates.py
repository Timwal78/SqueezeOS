"""
/api/v1/fixedincome/government/treasury_rates — US Treasury yields via yfinance.
Expected: GET ?start_date=2024-01-01
"""
from http.server import BaseHTTPRequestHandler
import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), *[".."] * 5))
from _base import parse_query, send_json, send_cors_preflight

# yfinance tickers for treasury yields
_TENORS = {
    "^IRX": "month_3",   # 13-week (≈3m)
    "^FVX": "year_5",
    "^TNX": "year_10",
    "^TYX": "year_30",
}


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        send_cors_preflight(self)

    def do_GET(self):
        import yfinance as yf
        try:
            q = parse_query(self)
            start = q.get("start_date")
            frames = {}
            for tick, col in _TENORS.items():
                try:
                    t = yf.Ticker(tick)
                    hist = t.history(start=start, interval="1d") if start \
                        else t.history(period="1mo", interval="1d")
                    for dt, row in hist.iterrows():
                        d = str(dt.date())
                        frames.setdefault(d, {})[col] = round(float(row["Close"]) / 100, 5)
                except Exception:
                    pass
            results = [{"date": d, **vals} for d, vals in sorted(frames.items())]
            send_json(self, {"results": results})
        except Exception as exc:
            send_json(self, {"results": [], "error": str(exc)}, 500)

    def log_message(self, *args):
        pass
