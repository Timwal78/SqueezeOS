"""
/api/v1/equity/fundamental/metrics — Key ratios via yfinance.
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
            send_json(self, {
                "results": [{
                    "symbol": sym,
                    "market_cap": info.get("marketCap"),
                    "pe_ratio": info.get("trailingPE"),
                    "forward_pe": info.get("forwardPE"),
                    "peg_ratio": info.get("pegRatio"),
                    "enterprise_to_ebitda": info.get("enterpriseToEbitda"),
                    "revenue_growth": info.get("revenueGrowth"),
                    "earnings_growth": info.get("earningsGrowth"),
                    "quick_ratio": info.get("quickRatio"),
                    "current_ratio": info.get("currentRatio"),
                    "debt_to_equity": info.get("debtToEquity"),
                    "gross_margin": info.get("grossMargins"),
                    "operating_margin": info.get("operatingMargins"),
                    "profit_margin": info.get("profitMargins"),
                    "return_on_assets": info.get("returnOnAssets"),
                    "return_on_equity": info.get("returnOnEquity"),
                    "dividend_yield": info.get("dividendYield"),
                    "payout_ratio": info.get("payoutRatio"),
                    "book_value": info.get("bookValue"),
                    "price_to_book": info.get("priceToBook"),
                    "enterprise_value": info.get("enterpriseValue"),
                }]
            })
        except Exception as exc:
            send_json(self, {"results": [], "error": str(exc)}, 500)

    def log_message(self, *args):
        pass
