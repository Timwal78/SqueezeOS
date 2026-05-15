"""
/api/v1/equity/search — Ticker search via yfinance.
Expected: GET ?query=apple&limit=8
"""
from http.server import BaseHTTPRequestHandler
import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), *[".."] * 4))
from _base import parse_query, send_json, send_cors_preflight


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        send_cors_preflight(self)

    def do_GET(self):
        import yfinance as yf
        try:
            q = parse_query(self)
            query = q.get("query", "").strip()
            limit = int(q.get("limit", 8))
            results = []
            if query:
                search = yf.Search(query, max_results=limit)
                for r in (search.quotes or [])[:limit]:
                    results.append({
                        "symbol": r.get("symbol", ""),
                        "name": r.get("longname") or r.get("shortname", ""),
                        "cik": None,
                    })
            send_json(self, {"results": results})
        except Exception as exc:
            send_json(self, {"results": [], "error": str(exc)}, 500)

    def log_message(self, *args):
        pass
