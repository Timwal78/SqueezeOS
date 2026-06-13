"""
FTD Data Oracle — x402-gated regulatory FTD + Reg SHO data feed.

Sells processed, normalized SEC Fails-To-Deliver and Reg SHO Threshold List
data per call. Pure descriptive data product — NOT trade signals, NOT
front-running guidance, NOT predictions of forced buying.

Free:    GET  /api/ftd/info                — discovery + tier description
Premium: GET  /api/ftd/threshold-list      — current Reg SHO threshold list     (0.02 RLUSD)
Premium: GET  /api/ftd/series/<symbol>     — 180-day FTD time series             (0.02 RLUSD)
Premium: GET  /api/ftd/ratio/<symbol>      — latest record + percentile rank    (0.03 RLUSD)
Premium: GET  /api/ftd/etf-basket/<etf>    — ETF constituents by FTD concentration (0.05 RLUSD)
Premium: GET  /api/ftd/cycle/<symbol>      — settlement-cycle descriptive bundle (0.05 RLUSD)

Compliance posture:
  * All endpoints return descriptive public-regulatory data only.
  * No endpoint emits a "buy", "sell", "squeeze imminent" signal.
  * T+21 / T+35 calendar markers are anchored to public FTD settlement dates
    and accompanied by notes explaining Reg SHO 204 close-out mechanics
    (including bona-fide market-maker exemptions).
  * The blueprint deliberately avoids front-running language and refuses to
    publish trade timing recommendations. Per the operator's directive, the
    framing is "research feed", not "alpha signal".

Discovery: /info is the only free endpoint. It exists so MCP / agents.json /
catalog crawlers can find the product without paying. The /info response
also describes the rate-limit and refresh cadence so agents can plan their
budgets.
"""

from __future__ import annotations

import hmac
import html as _html
import logging
import os
import time
from datetime import date, datetime, timedelta

from flask import Blueprint, Response, jsonify, request

from core.ftd_data import (
    ETF_BASKETS,
    WINDOW_DAYS,
    cycle_summary_for,
    get_store,
)
from proof402_integration import (
    PROOF402_SERVER,
    _issue_invoice,
    _verify_token_local,
)

logger = logging.getLogger("SqueezeOS-FTD-API")
ftd_bp = Blueprint("ftd", __name__)

# Endpoint IDs registered with 402Proof. These are deterministic UUIDs so the
# 402Proof dashboard can refer to them across deployments. Keep them stable.
FTD_READ_ENDPOINT_ID = "a4b5c6d7-e001-4f3e-aa24-d52e3bc12b5a"   # 0.02 RLUSD
FTD_RATIO_ENDPOINT_ID = "a4b5c6d7-e002-4f3e-aa24-d52e3bc12b5a"  # 0.03 RLUSD
FTD_DEEP_ENDPOINT_ID = "a4b5c6d7-e003-4f3e-aa24-d52e3bc12b5a"   # 0.05 RLUSD


# ── Payment gate (mirrors oracle_data_bp pattern) ───────────────────────────


def _gate(endpoint_id: str, price_rlusd: str):
    """Return (wallet, None) on success, or (None, flask_response) on 402/401."""
    token = request.headers.get("X-Payment-Token", "")
    if token:
        res = _verify_token_local(token)
        if res["valid"]:
            if res.get("endpoint_id") != endpoint_id:
                return None, (jsonify({
                    "error": "ERR_ENDPOINT_MISMATCH",
                    "message": "Token was issued for a different endpoint.",
                    "remedy": f"Obtain a new invoice at {PROOF402_SERVER}/v1/invoice",
                }), 401)
            return res.get("wallet", ""), None
        return None, (jsonify({
            "error": res.get("reason", "ERR_TOKEN_INVALID"),
            "remedy": f"{PROOF402_SERVER}/v1/invoice",
        }), 401)

    try:
        inv = _issue_invoice(endpoint_id)
    except Exception as e:
        logger.warning("[FTD] 402Proof unreachable (%s) — failing open", e)
        return "FALLTHROUGH", None

    return None, (jsonify({
        "error": "ERR_PAYMENT_REQUIRED",
        "message": (
            f"This FTD endpoint costs {price_rlusd} RLUSD per call. "
            "Pay on XRPL to continue."
        ),
        "invoice": inv,
        "remedy": {
            "step1": f"Send {inv.get('amount')} {inv.get('asset','RLUSD')} on XRPL to {inv.get('pay_to')}",
            "step2": f"Include MemoData: {inv.get('memo_hex')} in your XRPL payment",
            "step3": f"POST {PROOF402_SERVER}/v1/verify with invoice_id, tx_hash, agent_wallet",
            "step4": "Retry with header: X-Payment-Token: <token>",
        },
        "free_alternatives": {
            "tier_info": "/api/ftd/info",
        },
    }), 402)


# ── Routes ───────────────────────────────────────────────────────────────────


@ftd_bp.route("/info", methods=["GET"])
def info():
    """Free discovery: tier description, refresh cadence, available baskets."""
    store_status = get_store().status()
    return jsonify({
        "tier": "FTD_DATA_ORACLE",
        "purpose": (
            "Machine-readable regulatory FTD and Reg SHO threshold list data. "
            "Pure descriptive feed — not trade signals, not predictions of forced "
            "buying. Reg SHO 204 includes market-maker exemptions and rolling "
            "close-out windows that no third party can predict deterministically."
        ),
        "data_sources": [
            {
                "name": "SEC Reg SHO Fails-To-Deliver",
                "publisher": "U.S. Securities and Exchange Commission",
                "url": "https://www.sec.gov/data/foiadocsfailsdatahtm",
                "license": "Public domain (17 U.S.C. § 105)",
                "publication_cadence": "biweekly",
            },
            {
                "name": "SEC Reg SHO Threshold Securities List",
                "publisher": "U.S. Securities and Exchange Commission",
                "url": "https://www.sec.gov/divisions/marketreg/regsho-threshold-securities.shtml",
                "license": "Public domain",
                "publication_cadence": "daily",
            },
        ],
        "endpoints": {
            "GET /api/ftd/alerts": {"price_rlusd": "0.00", "endpoint_id": None, "note": "ShortSqueeze Swarm public alert feed (free teaser)"},
            "GET /api/ftd/threshold-list": {"price_rlusd": "0.02", "endpoint_id": FTD_READ_ENDPOINT_ID},
            "GET /api/ftd/series/{symbol}": {"price_rlusd": "0.02", "endpoint_id": FTD_READ_ENDPOINT_ID},
            "GET /api/ftd/ratio/{symbol}": {"price_rlusd": "0.03", "endpoint_id": FTD_RATIO_ENDPOINT_ID},
            "GET /api/ftd/etf-basket/{etf}": {"price_rlusd": "0.05", "endpoint_id": FTD_DEEP_ENDPOINT_ID},
            "GET /api/ftd/cycle/{symbol}": {"price_rlusd": "0.05", "endpoint_id": FTD_DEEP_ENDPOINT_ID},
        },
        "etf_baskets_supported": sorted(ETF_BASKETS.keys()),
        "window_days": WINDOW_DAYS,
        "refresh_cadence": {
            "ftd_data": "24h (SEC publishes biweekly)",
            "threshold_list": "6h (SEC publishes daily)",
        },
        "store": store_status,
        "compliance_note": (
            "This product surfaces public SEC regulatory data. It does not "
            "constitute investment advice, a recommendation, or a prediction "
            "of price action. T+21 and T+35 markers are calendar arithmetic on "
            "published FTD settlement dates — not deterministic predictions of "
            "forced buying."
        ),
        "free": True,
        "ts": time.time(),
    })


@ftd_bp.route("/alerts", methods=["GET"])
def alerts():
    """
    FREE — ShortSqueeze Swarm public alert feed.

    Recent FTD anomalies (new Reg SHO threshold-list entries, FTD spikes
    >= 2x rolling avg at >= 95th percentile). Each alert is a teaser:
    symbol + anomaly type + spike ratio, no thesis or T+21/T+35 markers.

    Full descriptive detail: GET /api/ftd/cycle/<symbol> (0.05 RLUSD).
    """
    from ftd_anomaly_engine import get_feed, SCAN_INTERVAL_S, SPIKE_THRESHOLD

    limit = max(1, min(int(request.args.get("limit", 25)), 100))
    items = get_feed(limit)
    return jsonify({
        "tier": "SHORTSQUEEZE_SWARM",
        "count": len(items),
        "alerts": items,
        "scan_interval_seconds": SCAN_INTERVAL_S,
        "spike_threshold": SPIKE_THRESHOLD,
        "unlock_detail": "/api/ftd/cycle/{symbol} — 0.05 RLUSD",
        "source": "SEC Reg SHO Fails-To-Deliver + Threshold Securities List",
        "compliance_note": (
            "Descriptive anomaly feed only. Not a trade signal, not a "
            "prediction of forced buying."
        ),
        "free": True,
        "ts": time.time(),
    })


@ftd_bp.route("/threshold-list", methods=["GET"])
def threshold_list():
    """0.02 RLUSD — Current Reg SHO Threshold Securities List."""
    wallet, err = _gate(FTD_READ_ENDPOINT_ID, "0.02")
    if err:
        return err

    store = get_store()
    entries = store.threshold_list()
    return jsonify({
        "as_of_ts": store.status()["last_threshold_refresh_ts"],
        "count": len(entries),
        "entries": entries,
        "source": "SEC Reg SHO Threshold Securities List",
        "agent_wallet": wallet or "",
        "ts": time.time(),
    })


@ftd_bp.route("/series/<symbol>", methods=["GET"])
def series(symbol: str):
    """0.02 RLUSD — Historical FTD time series for a symbol (default 90 days)."""
    wallet, err = _gate(FTD_READ_ENDPOINT_ID, "0.02")
    if err:
        return err

    limit = max(1, min(int(request.args.get("limit", 90)), WINDOW_DAYS))
    store = get_store()
    recs = store.series_for(symbol, limit=limit)

    if not recs:
        return jsonify({
            "symbol": symbol.upper().strip(),
            "status": "AWAITING_DATA",
            "message": (
                "No FTD records in the rolling window for this symbol. The "
                "feed may still be warming up, the symbol may have no recent "
                "FTDs, or the symbol may not be on the SEC FTD reports."
            ),
            "agent_wallet": wallet or "",
            "ts": time.time(),
        })

    return jsonify({
        "symbol": symbol.upper().strip(),
        "count": len(recs),
        "records": [r.as_dict() for r in recs],
        "source": "SEC Reg SHO Fails-To-Deliver",
        "window_days_max": WINDOW_DAYS,
        "agent_wallet": wallet or "",
        "ts": time.time(),
    })


@ftd_bp.route("/ratio/<symbol>", methods=["GET"])
def ratio(symbol: str):
    """0.03 RLUSD — Latest FTD record + percentile rank within rolling window."""
    wallet, err = _gate(FTD_RATIO_ENDPOINT_ID, "0.03")
    if err:
        return err

    store = get_store()
    payload = store.latest_ratio(symbol)
    if not payload:
        return jsonify({
            "symbol": symbol.upper().strip(),
            "status": "AWAITING_DATA",
            "message": "No FTD records in the rolling window for this symbol.",
            "agent_wallet": wallet or "",
            "ts": time.time(),
        })

    payload["on_threshold_list"] = store.is_on_threshold_list(symbol)
    payload["agent_wallet"] = wallet or ""
    payload["ts"] = time.time()
    payload["source"] = "SEC Reg SHO FTD + Threshold Securities List"
    return jsonify(payload)


@ftd_bp.route("/etf-basket/<etf>", methods=["GET"])
def etf_basket(etf: str):
    """0.05 RLUSD — ETF constituents ranked by current FTD notional."""
    wallet, err = _gate(FTD_DEEP_ENDPOINT_ID, "0.05")
    if err:
        return err

    store = get_store()
    payload = store.basket_breakdown(etf)
    if not payload:
        return jsonify({
            "etf": etf.upper().strip(),
            "status": "UNKNOWN_ETF",
            "supported_etfs": sorted(ETF_BASKETS.keys()),
            "message": (
                "Basket lookup is supported only for the retail-meme ETF "
                "universe (XRT, IWM, IJR, KRE). Request additional baskets "
                "via the operator: https://www.scriptmasterlabs.com"
            ),
            "agent_wallet": wallet or "",
            "ts": time.time(),
        }), 404

    payload["agent_wallet"] = wallet or ""
    payload["ts"] = time.time()
    payload["source"] = "SEC FTD + curated ETF constituent map"
    return jsonify(payload)


@ftd_bp.route("/cycle/<symbol>", methods=["GET"])
def cycle(symbol: str):
    """
    0.05 RLUSD — Settlement-cycle descriptive bundle for one symbol.

    Returns: latest FTD record + rolling stats + threshold list status +
    T+21/T+35 calendar markers + Reg SHO 204 13-day marker. Every field is
    descriptive. The response includes explicit notes that the markers are
    not predictions of forced buying.
    """
    wallet, err = _gate(FTD_DEEP_ENDPOINT_ID, "0.05")
    if err:
        return err

    payload = cycle_summary_for(symbol)
    payload["source"] = (
        "SEC Reg SHO Fails-To-Deliver + Threshold Securities List "
        "(processed and indexed by SqueezeOS)"
    )
    payload["agent_wallet"] = wallet or ""
    payload["ts"] = time.time()
    return jsonify(payload)


# ── Operator dashboard (mobile-first, save-to-homescreen) ────────────────────


def _dashboard_authorized() -> bool:
    """Failure-closed check: returns True only if OPERATOR_API_KEY env var is
    set AND the request supplies a matching value via header or ?key= param.

    No env var → False (dashboard refuses to render). This mirrors the BB7
    dashboard pattern (DASHBOARD_AUTH_TOKEN failure-closed)."""
    expected = os.environ.get("OPERATOR_API_KEY", "").strip()
    if not expected:
        return False
    provided = (
        request.headers.get("X-Operator-Key", "")
        or request.args.get("key", "")
    ).strip()
    if not provided:
        return False
    return hmac.compare_digest(provided, expected)


def _fmt_int(n) -> str:
    if n is None:
        return "—"
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


def _fmt_money(n) -> str:
    if n is None:
        return "—"
    try:
        v = float(n)
    except (TypeError, ValueError):
        return str(n)
    if v >= 1e9:
        return f"${v/1e9:.2f}B"
    if v >= 1e6:
        return f"${v/1e6:.2f}M"
    if v >= 1e3:
        return f"${v/1e3:.1f}K"
    return f"${v:.0f}"


def _fmt_ts(ts) -> str:
    if not ts:
        return "—"
    try:
        return datetime.utcfromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError):
        return "—"


def _days_color(days) -> str:
    """Color class for T+N countdown badges."""
    if days is None:
        return "muted"
    if days < 0:
        return "elapsed"   # window has passed
    if days <= 3:
        return "imminent"
    if days <= 14:
        return "near"
    return "distant"


@ftd_bp.route("/dashboard", methods=["GET"])
@ftd_bp.route("/dashboard/", methods=["GET"])
def dashboard():
    """
    Mobile-first operator dashboard for the FTD Data Oracle.

    Renders a self-contained HTML page (inline CSS, no external deps) that
    shows the current Reg SHO threshold list, top FTD positions by notional,
    and the T+35 calendar markers for symbols on the threshold list.

    Auth: requires OPERATOR_API_KEY env var to be set. Pass the key via:
      * ?key=<token> query string (mobile-friendly — save with key in URL)
      * X-Operator-Key: <token> header (curl-friendly)

    Failure-closed: returns 503 if OPERATOR_API_KEY is not configured.

    Save-to-homescreen: page includes <meta name="theme-color">,
    apple-touch-icon, and PWA-friendly viewport so iOS / Android can add
    it as a homescreen app with native chrome.
    """
    if not os.environ.get("OPERATOR_API_KEY", "").strip():
        return (
            "<h1>503 Dashboard disabled</h1>"
            "<p>OPERATOR_API_KEY environment variable is not configured on this server. "
            "The dashboard refuses to render without operator auth — failure-closed. "
            "Set OPERATOR_API_KEY in the Render dashboard and reload.</p>",
            503,
            {"Content-Type": "text/html; charset=utf-8"},
        )
    if not _dashboard_authorized():
        return (
            "<h1>401 Unauthorized</h1>"
            "<p>Pass <code>?key=&lt;OPERATOR_API_KEY&gt;</code> in the URL or set the "
            "<code>X-Operator-Key</code> header.</p>",
            401,
            {"Content-Type": "text/html; charset=utf-8"},
        )

    store = get_store()
    status = store.status()

    # Build threshold list rows enriched with cycle info
    threshold_entries = store.threshold_list()
    threshold_rows = []
    today = date.today()
    for entry in threshold_entries:
        symbol = entry["symbol"]
        cyc = cycle_summary_for(symbol)
        threshold_rows.append({
            "symbol":            symbol,
            "company":           entry.get("company", ""),
            "entry_date":        entry.get("entry_date", ""),
            "days_on_list":      (today - date.fromisoformat(entry["entry_date"])).days
                                 if entry.get("entry_date") else None,
            "reg204_marker":     cyc.get("reg_sho_204_close_out_marker"),
            "latest_fails":      cyc.get("latest_fail_shares"),
            "latest_notional":   cyc.get("latest_notional_usd"),
            "spike_ratio":       cyc.get("window_spike_ratio"),
            "t21_marker":        cyc.get("t21_calendar_marker"),
            "t35_marker":        cyc.get("t35_calendar_marker"),
            "days_to_t21":       cyc.get("days_to_t21_from_today"),
            "days_to_t35":       cyc.get("days_to_t35_from_today"),
            "settlement_date":   cyc.get("latest_settlement_date"),
        })
    # Sort by latest notional descending
    threshold_rows.sort(key=lambda r: r.get("latest_notional") or 0, reverse=True)

    # Build top-spikes ranking across ALL tracked symbols (not just threshold)
    spikes = []
    with store._lock:
        for sym, series in store._by_symbol.items():
            if not series:
                continue
            latest = series[-1]
            fails = [r.fail_shares for r in series]
            if not fails:
                continue
            avg = sum(fails) / len(fails)
            spike = latest.fail_shares / avg if avg > 0 else 0
            if spike < 2.0:
                continue
            spikes.append({
                "symbol":         sym,
                "spike_ratio":    round(spike, 2),
                "latest_fails":   latest.fail_shares,
                "latest_notional": round(latest.fail_shares * latest.price, 2),
                "settlement":     latest.settlement_date.isoformat(),
                "on_threshold":   store.is_on_threshold_list(sym),
            })
    spikes.sort(key=lambda r: r["spike_ratio"], reverse=True)
    spikes = spikes[:25]

    # Render HTML
    parts = []
    parts.append(_DASHBOARD_HTML_HEAD)

    # Status banner
    last_ftd_age = ""
    last_thresh_age = ""
    now = time.time()
    if status["last_ftd_refresh_ts"]:
        last_ftd_age = f"{int((now - status['last_ftd_refresh_ts']) / 60)} min ago"
    if status["last_threshold_refresh_ts"]:
        last_thresh_age = f"{int((now - status['last_threshold_refresh_ts']) / 60)} min ago"

    parts.append(
        f"""
<header>
  <h1>FTD Oracle</h1>
  <div class="ts">{_fmt_ts(now)} • SqueezeOS</div>
</header>

<section class="status-grid">
  <div class="card"><div class="num">{_fmt_int(status['symbols_tracked'])}</div><div class="lbl">symbols tracked</div></div>
  <div class="card"><div class="num">{_fmt_int(status['threshold_entries'])}</div><div class="lbl">on threshold list</div></div>
  <div class="card"><div class="num">{_fmt_int(status['loaded_ftd_files'])}</div><div class="lbl">SEC FTD files loaded</div></div>
  <div class="card"><div class="num">{status['window_days']}</div><div class="lbl">day rolling window</div></div>
</section>

<section class="refresh">
  <div>FTD refresh: <strong>{last_ftd_age or 'pending'}</strong> (24h cadence)</div>
  <div>Threshold list: <strong>{last_thresh_age or 'pending'}</strong> (6h cadence)</div>
</section>
"""
    )

    if not status["available"]:
        parts.append(
            """
<section class="empty">
  <h2>Pollers still warming up</h2>
  <p>The FTD store is empty. Background pollers fire on app boot and complete the first SEC FTD ingestion within ~24h, and the Reg SHO threshold list within ~6h.</p>
  <p>Reload after the next refresh window. The endpoints return <code>AWAITING_DATA</code> until then — no fabricated values per AGENT_LAW §1.</p>
</section>
"""
        )

    # Threshold list section
    parts.append("<section><h2>Reg SHO Threshold List</h2>")
    if not threshold_rows:
        parts.append('<p class="muted">No symbols currently on the SEC Reg SHO Threshold Securities List.</p>')
    else:
        parts.append('<div class="scroll"><table>'
                     '<thead><tr>'
                     '<th>Sym</th><th>Days on list</th><th>Latest FTD</th><th>Notional</th>'
                     '<th>Spike</th><th>Reg SHO 204</th><th>T+21</th><th>T+35</th>'
                     '</tr></thead><tbody>')
        for r in threshold_rows:
            t21 = r.get("days_to_t21")
            t35 = r.get("days_to_t35")
            spike = r.get("spike_ratio")
            spike_class = "elevated" if (spike is not None and spike >= 2.0) else ""
            parts.append(
                f"<tr>"
                f"<td><strong>{_html.escape(r['symbol'])}</strong>"
                f"<div class='sub'>{_html.escape(r.get('company','') or '')[:24]}</div></td>"
                f"<td>{_fmt_int(r.get('days_on_list'))}</td>"
                f"<td>{_fmt_int(r.get('latest_fails'))}<div class='sub'>{_html.escape(r.get('settlement_date') or '')}</div></td>"
                f"<td>{_fmt_money(r.get('latest_notional'))}</td>"
                f"<td class='{spike_class}'>{(f'{spike:.2f}×' if spike is not None else '—')}</td>"
                f"<td>{_html.escape(r.get('reg204_marker') or '—')}</td>"
                f"<td><span class='badge {_days_color(t21)}'>{_html.escape(r.get('t21_marker') or '—')}<div class='sub'>{('elapsed' if t21 is None or t21<0 else f'{t21}d')}</div></span></td>"
                f"<td><span class='badge {_days_color(t35)}'>{_html.escape(r.get('t35_marker') or '—')}<div class='sub'>{('elapsed' if t35 is None or t35<0 else f'{t35}d')}</div></span></td>"
                f"</tr>"
            )
        parts.append("</tbody></table></div>")
    parts.append("</section>")

    # Top FTD spikes section (across the universe, not just threshold list)
    parts.append("<section><h2>Top FTD Spikes (full universe)</h2>")
    if not spikes:
        parts.append('<p class="muted">No symbols with spike ratio ≥ 2.0× in the rolling window.</p>')
    else:
        parts.append('<div class="scroll"><table>'
                     '<thead><tr>'
                     '<th>Sym</th><th>Spike</th><th>Latest FTD</th><th>Notional</th>'
                     '<th>Settlement</th><th>On list?</th>'
                     '</tr></thead><tbody>')
        for r in spikes:
            on = "✓" if r["on_threshold"] else ""
            parts.append(
                f"<tr>"
                f"<td><strong>{_html.escape(r['symbol'])}</strong></td>"
                f"<td class='elevated'>{r['spike_ratio']:.2f}×</td>"
                f"<td>{_fmt_int(r['latest_fails'])}</td>"
                f"<td>{_fmt_money(r['latest_notional'])}</td>"
                f"<td>{_html.escape(r['settlement'])}</td>"
                f"<td class='center'>{on}</td>"
                f"</tr>"
            )
        parts.append("</tbody></table></div>")
    parts.append("</section>")

    # Compliance footer
    parts.append("""
<section class="footer">
  <p><strong>Descriptive data only.</strong> Every value on this page is public SEC data — Reg SHO Fails-To-Deliver and Threshold Securities List — normalized into JSON and rendered as a research feed.</p>
  <p>T+21 and T+35 are calendar arithmetic on the latest published FTD settlement date. Reg SHO 204 provides bona-fide market-maker exemptions and rolling close-out mechanics that can extend or short-circuit these windows. No content on this page predicts price action or forced buying.</p>
  <p class="muted">Sources: <a href="https://www.sec.gov/data/foiadocsfailsdatahtm" target="_blank">SEC FTD</a> · <a href="https://www.sec.gov/divisions/marketreg/regsho-threshold-securities.shtml" target="_blank">SEC Reg SHO Threshold List</a></p>
</section>

</main>
</body></html>
""")

    return Response("".join(parts), mimetype="text/html; charset=utf-8")


_DASHBOARD_HTML_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0a0e1a">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="FTD Oracle">
<meta http-equiv="refresh" content="60">
<title>FTD Oracle — SqueezeOS</title>
<link rel="apple-touch-icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 180 180'%3E%3Crect width='180' height='180' fill='%230a0e1a'/%3E%3Ctext x='90' y='115' font-family='monospace' font-size='62' font-weight='900' fill='%23ff5a5a' text-anchor='middle'%3EFTD%3C/text%3E%3C/svg%3E">
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font:14px/1.4 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0a0e1a;color:#e6e8ed;padding:env(safe-area-inset-top) 0 env(safe-area-inset-bottom)}
  main{max-width:900px;margin:0 auto;padding:12px}
  header{display:flex;justify-content:space-between;align-items:baseline;padding:8px 12px;border-bottom:1px solid #1a2030;margin-bottom:16px}
  header h1{font-size:20px;font-weight:800;letter-spacing:-.5px}
  header .ts{font-size:11px;color:#7f8aa3;font-family:monospace}
  section{margin-bottom:24px}
  h2{font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:1.2px;color:#9aa3bd;margin-bottom:10px;padding-left:4px}
  .status-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-bottom:8px}
  @media(min-width:600px){.status-grid{grid-template-columns:repeat(4,1fr)}}
  .card{background:#10172a;border:1px solid #1a2030;border-radius:10px;padding:14px 12px;text-align:center}
  .card .num{font-size:24px;font-weight:800;color:#fff;font-family:monospace}
  .card .lbl{font-size:10px;color:#7f8aa3;text-transform:uppercase;letter-spacing:.5px;margin-top:4px}
  .refresh{display:flex;gap:16px;flex-wrap:wrap;font-size:11px;color:#9aa3bd;padding:8px 12px;background:#10172a;border-radius:8px}
  .refresh strong{color:#e6e8ed;font-family:monospace}
  .empty{background:#1a1a30;border:1px solid #2a2050;border-radius:10px;padding:16px;color:#b8a8d8}
  .empty h2{color:#b8a8d8;margin-bottom:8px;text-transform:none;letter-spacing:0;font-size:15px;padding:0}
  .scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;background:#10172a;border-radius:10px;border:1px solid #1a2030}
  table{width:100%;border-collapse:collapse;min-width:600px}
  th{font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:#7f8aa3;font-weight:700;padding:10px 8px;text-align:left;border-bottom:1px solid #1a2030;background:#0a0e1a;position:sticky;top:0}
  td{padding:10px 8px;border-bottom:1px solid #161e30;vertical-align:top;font-family:monospace}
  td .sub{font-size:10px;color:#7f8aa3;font-family:monospace;margin-top:2px}
  td.center{text-align:center}
  tr:hover{background:#0d1424}
  tr:last-child td{border-bottom:none}
  .elevated{color:#ff8b6b;font-weight:700}
  .muted{color:#7f8aa3}
  .badge{display:inline-block;padding:3px 8px;border-radius:6px;font-size:11px;font-weight:600;line-height:1}
  .badge.imminent{background:#3a1818;color:#ff7070;border:1px solid #6a2828}
  .badge.near{background:#3a3018;color:#ffce70;border:1px solid #6a5828}
  .badge.distant{background:#18301a;color:#70d070;border:1px solid #285a30}
  .badge.elapsed{background:#181818;color:#7f8aa3;border:1px solid #2a2a2a}
  .badge.muted{background:#181818;color:#7f8aa3;border:1px solid #2a2a2a}
  .footer{font-size:11px;color:#7f8aa3;padding:16px 12px;border-top:1px solid #1a2030;line-height:1.6}
  .footer p{margin-bottom:8px}
  .footer strong{color:#e6e8ed}
  .footer a{color:#6090f0;text-decoration:none}
</style>
</head>
<body>
<main>
"""
