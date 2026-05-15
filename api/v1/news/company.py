"""
/api/v1/news/company — Company news (yfinance).
Expected: GET ?symbol=AAPL&limit=20
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
            limit = int(q.get("limit", 20))
            t = yf.Ticker(sym)
            raw_news = t.news or []
            results = []
            for item in raw_news[:limit]:
                content = item.get("content", {})
                results.append({
                    "id": str(item.get("id", "")),
                    "date": item.get("providerPublishTime", ""),
                    "title": content.get("title") or item.get("title", ""),
                    "url": content.get("canonicalUrl", {}).get("url") or item.get("link", ""),
                    "source": content.get("provider", {}).get("displayName") or item.get("publisher", ""),
                    "summary": content.get("summary") or "",
                    "symbol": sym,
                })
            send_json(self, {"results": results})
        except Exception as exc:
            send_json(self, {"results": [], "error": str(exc)}, 500)

    def log_message(self, *args):
        pass
