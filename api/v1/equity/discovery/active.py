"""
/api/v1/equity/discovery/active — Most active by volume via yfinance.
"""
from http.server import BaseHTTPRequestHandler
import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), *[".."] * 5))
from _base import send_json, send_cors_preflight

WATCHLIST = ["SPY", "QQQ", "IWM", "NVDA", "AMD", "TSLA", "AAPL", "GME", "AMC", "MARA",
             "RIOT", "SOFI", "PLTR", "COIN", "HOOD", "RBLX", "SNAP", "META", "AMZN", "MSFT"]


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        send_cors_preflight(self)

    def do_GET(self):
        import yfinance as yf
        try:
            raw = yf.download(WATCHLIST, period="1d", progress=False, auto_adjust=True)
            close = raw.get("Close", raw)
            volume = raw.get("Volume")
            results = []
            for sym in WATCHLIST:
                try:
                    prices = close[sym].dropna() if sym in close.columns else close.dropna()
                    vols = volume[sym].dropna() if volume is not None and sym in volume.columns else None
                    price = float(prices.iloc[-1])
                    prev = float(prices.iloc[0])
                    pct = round((price - prev) / prev * 100, 2) if prev > 0 else 0
                    vol = int(vols.sum()) if vols is not None else 0
                    results.append({"symbol": sym, "price": price, "change": round(price - prev, 2), "percent_change": pct, "volume": vol})
                except Exception:
                    pass
            results.sort(key=lambda x: x["volume"], reverse=True)
            send_json(self, {"results": results[:20]})
        except Exception as exc:
            send_json(self, {"results": [], "error": str(exc)}, 500)

    def log_message(self, *args):
        pass
