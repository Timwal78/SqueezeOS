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

import logging
import time

from flask import Blueprint, jsonify, request

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
