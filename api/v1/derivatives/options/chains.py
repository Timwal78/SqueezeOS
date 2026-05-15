"""
/api/v1/derivatives/options/chains — Options chain via yfinance.
Expected: GET ?symbol=AAPL
"""
from http.server import BaseHTTPRequestHandler
import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), *[".."] * 6))
from _base import parse_query, send_json, send_cors_preflight
from datetime import date


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        send_cors_preflight(self)

    def do_GET(self):
        import yfinance as yf
        try:
            q = parse_query(self)
            sym = q.get("symbol", "SPY").upper()
            t = yf.Ticker(sym)
            expirations = t.options[:4]  # next 4 expirations
            today = date.today()
            results = []
            for exp in expirations:
                try:
                    chain = t.option_chain(exp)
                    exp_date = date.fromisoformat(exp)
                    dte = (exp_date - today).days
                    for _, row in chain.calls.iterrows():
                        results.append(_row(row, sym, exp, dte, "call", t.fast_info.last_price))
                    for _, row in chain.puts.iterrows():
                        results.append(_row(row, sym, exp, dte, "put", t.fast_info.last_price))
                except Exception:
                    pass
            send_json(self, {"results": results})
        except Exception as exc:
            send_json(self, {"results": [], "error": str(exc)}, 500)

    def log_message(self, *args):
        pass


def _safe_float(v):
    try:
        f = float(v)
        return None if (f != f) else f  # NaN check
    except Exception:
        return None


def _row(row, sym, exp, dte, opt_type, underlying):
    return {
        "underlying_symbol": sym,
        "underlying_price": _safe_float(underlying),
        "contract_symbol": row.get("contractSymbol", ""),
        "expiration": exp,
        "dte": dte,
        "strike": _safe_float(row.get("strike")),
        "option_type": opt_type,
        "open_interest": _safe_float(row.get("openInterest")),
        "volume": _safe_float(row.get("volume")),
        "last_trade_price": _safe_float(row.get("lastPrice")),
        "bid": _safe_float(row.get("bid")),
        "ask": _safe_float(row.get("ask")),
        "change": _safe_float(row.get("change")),
        "change_percent": _safe_float(row.get("percentChange")),
        "implied_volatility": _safe_float(row.get("impliedVolatility")),
        "in_the_money": bool(row.get("inTheMoney", False)),
    }
