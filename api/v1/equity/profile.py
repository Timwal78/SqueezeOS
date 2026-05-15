"""
/api/v1/equity/profile — Company profile via yfinance.
Expected: GET ?symbol=AAPL
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
            sym = q.get("symbol", "AAPL").upper()
            info = yf.Ticker(sym).info
            send_json(self, {
                "results": [{
                    "symbol": sym,
                    "name": info.get("longName") or info.get("shortName"),
                    "stock_exchange": info.get("exchange"),
                    "long_description": info.get("longBusinessSummary"),
                    "company_url": info.get("website"),
                    "business_phone_no": info.get("phone"),
                    "hq_address1": info.get("address1"),
                    "hq_address_city": info.get("city"),
                    "hq_state": info.get("state"),
                    "hq_country": info.get("country"),
                    "hq_address_postal_code": info.get("zip"),
                    "employees": info.get("fullTimeEmployees"),
                    "sector": info.get("sector"),
                    "industry_category": info.get("industry"),
                    "issue_type": info.get("quoteType"),
                    "currency": info.get("currency", "USD"),
                    "market_cap": info.get("marketCap"),
                    "shares_outstanding": info.get("sharesOutstanding"),
                    "shares_float": info.get("floatShares"),
                    "dividend_yield": info.get("dividendYield"),
                    "beta": info.get("beta"),
                }]
            })
        except Exception as exc:
            send_json(self, {"results": [], "error": str(exc)}, 500)

    def log_message(self, *args):
        pass
