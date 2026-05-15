"""
/api/v1/equity/discovery/gainers — Top gainers via yfinance screener.
"""
from http.server import BaseHTTPRequestHandler
import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), *[".."] * 5))
from _base import send_json, send_cors_preflight

WATCHLIST = ["NVDA", "AMD", "TSLA", "META", "AAPL", "GME", "AMC", "MARA", "RIOT", "SOFI",
             "PLTR", "LCID", "RIVN", "NIO", "SPCE", "COIN", "HOOD", "RBLX", "SNAP", "UBER"]


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        send_cors_preflight(self)

    def do_GET(self):
        import yfinance as yf
        try:
            raw = yf.download(WATCHLIST, period="1d", progress=False, auto_adjust=True)
            close = raw["Close"] if "Close" in raw.columns else raw
            results = []
            for sym in WATCHLIST:
                try:
                    prices = close[sym].dropna() if sym in close.columns else close.dropna()
                    if len(prices) < 2:
                        continue
                    price = float(prices.iloc[-1])
                    prev = float(prices.iloc[0])
                    pct = round((price - prev) / prev * 100, 2) if prev > 0 else 0
                    if pct > 0:
                        results.append({"symbol": sym, "price": price, "change": round(price - prev, 2), "percent_change": pct, "volume": 0})
                except Exception:
                    pass
            results.sort(key=lambda x: x["percent_change"], reverse=True)
            send_json(self, {"results": results[:20]})
        except Exception as exc:
            send_json(self, {"results": [], "error": str(exc)}, 500)

    def log_message(self, *args):
        pass
