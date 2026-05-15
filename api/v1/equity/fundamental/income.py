"""
/api/v1/equity/fundamental/income — Income statement via yfinance.
Expected: GET ?symbol=AAPL&period=annual&limit=5
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
            limit = int(q.get("limit", 5))
            t = yf.Ticker(sym)
            inc = t.financials  # annual income statement
            results = []
            for col in list(inc.columns)[:limit]:
                row = inc[col]
                results.append({
                    "period_ending": str(col.date()),
                    "total_revenue": _safe(row, "Total Revenue"),
                    "cost_of_revenue": _safe(row, "Cost Of Revenue"),
                    "gross_profit": _safe(row, "Gross Profit"),
                    "operating_income": _safe(row, "Operating Income"),
                    "total_pre_tax_income": _safe(row, "Pretax Income"),
                    "net_income": _safe(row, "Net Income"),
                    "basic_earnings_per_share": _safe(row, "Basic EPS"),
                    "diluted_earnings_per_share": _safe(row, "Diluted EPS"),
                    "research_and_development_expense": _safe(row, "Research And Development"),
                    "selling_general_and_admin_expense": _safe(row, "Selling General And Administration"),
                })
            send_json(self, {"results": results})
        except Exception as exc:
            send_json(self, {"results": [], "error": str(exc)}, 500)

    def log_message(self, *args):
        pass


def _safe(row, key):
    try:
        v = row.get(key)
        return float(v) if v is not None else None
    except Exception:
        return None
