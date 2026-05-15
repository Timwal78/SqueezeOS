"""
/api/v1/equity/estimates/consensus — Analyst price targets via yfinance.
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
            info = yf.Ticker(sym).info
            fi = yf.Ticker(sym).fast_info
            send_json(self, {
                "results": [{
                    "symbol": sym,
                    "target_high": info.get("targetHighPrice"),
                    "target_low": info.get("targetLowPrice"),
                    "target_consensus": info.get("targetMeanPrice"),
                    "target_median": info.get("targetMedianPrice"),
                    "recommendation": info.get("recommendationKey"),
                    "recommendation_mean": info.get("recommendationMean"),
                    "number_of_analysts": info.get("numberOfAnalystOpinions"),
                    "current_price": float(fi.last_price or 0),
                    "currency": info.get("currency", "USD"),
                }]
            })
        except Exception as exc:
            send_json(self, {"results": [], "error": str(exc)}, 500)

    def log_message(self, *args):
        pass
