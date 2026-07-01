"""
passport_bp.py — Agent Passport: one unified profile per wallet address.

Aggregates every wallet-keyed reputation/history source already live across
SqueezeOS into a single response. Adds no new data stores and no new scoring
logic of its own -- it is strictly a read-through aggregator over the real
in-memory stores and live 402Proof credit bureau that already exist.

Route: GET /api/passport/<wallet>

Design for easy extension: SECTIONS is a list of (name, fetch_fn) pairs.
fetch_fn takes the wallet string and returns a JSON-serializable dict, or
raises. Each section runs independently and failures are isolated -- one
broken source never takes down the rest of the passport, and a failed
section is reported as {"status": "unavailable"}, never fabricated data
(Sovereign Data Policy Section 4: no fallback to invented values).

To add a new section later: write a fetch_fn, append it to SECTIONS below.
Nothing else in this file needs to change.
"""

import html as _html
import logging
import time

from flask import Blueprint, Response, jsonify

from core.legacy import clean_data
from proof402_integration import fetch_credit_bureau_score

logger = logging.getLogger("PassportBP")
passport_bp = Blueprint("passport", __name__)


def _section_trust(wallet: str) -> dict:
    from core.api.ccs_bp import _get_wallet_trust, _composite_trust
    ledger = _get_wallet_trust(wallet)
    bureau_score = fetch_credit_bureau_score(wallet)
    return {
        "ccs_score": ledger["ccs_score"],
        "reputation_tier": ledger["reputation_tier"],
        "validations_submitted": ledger["validations_submitted"],
        "content_blocked": ledger["content_blocked"],
        "content_passed": ledger["content_passed"],
        "agent_credit_bureau_score": bureau_score,
        "composite_trust": _composite_trust(ledger["ccs_score"], bureau_score),
        "first_seen": ledger["first_seen"],
        "last_seen": ledger["last_seen"],
    }


def _section_marketplace(wallet: str) -> dict:
    from core.api.marketplace_bp import _seller_stats, SELLER_SHARE
    st = _seller_stats.get(wallet)
    if not st:
        return {"balance_rlusd": 0.0, "sale_count": 0, "message": "No sales recorded for this wallet yet."}
    return {
        "balance_rlusd": st["balance_rlusd"],
        "paid_out_rlusd": st["paid_out_rlusd"],
        "revenue_rlusd": st["revenue_rlusd"],
        "sale_count": st["sale_count"],
        "seller_share": f"{int(SELLER_SHARE * 100)}%",
    }


def _section_futures(wallet: str) -> dict:
    from core.api.futures_bp import _futures, _leaderboard, _lock
    with _lock:
        results = [f for f in _futures.values()
                   if f["creator_wallet"] == wallet or f["taker_wallet"] == wallet]
    return {
        "count": len(results),
        "stats": _leaderboard.get(wallet, {}),
    }


def _section_settlement(wallet: str) -> dict:
    from core.api.settlement_bp import _contracts, _lock
    with _lock:
        results = [c for c in _contracts.values()
                   if c["creator_wallet"] == wallet or c["counterparty"] == wallet]
    return {"count": len(results)}


def _section_hiring(wallet: str) -> dict:
    from core.api.hiring_bp import _jobs, _rep
    posted = [j for j in _jobs.values() if j['poster'] == wallet]
    executed = [j for j in _jobs.values() if j.get('executor') == wallet]
    return {
        "reputation": _rep(wallet),
        "posted": {
            "count": len(posted),
            "filled": sum(1 for j in posted if j['status'] == 'CONFIRMED'),
        },
        "executed": {
            "count": len(executed),
            "completed": sum(1 for j in executed if j['status'] == 'CONFIRMED'),
            "disputed": sum(1 for j in executed if j['status'] == 'DISPUTED'),
        },
    }


# Registry of passport sections. Append here to extend -- nothing else
# in this file needs to change to add a new data source.
SECTIONS = [
    ("trust", _section_trust),
    ("marketplace", _section_marketplace),
    ("futures", _section_futures),
    ("settlement", _section_settlement),
    ("hiring", _section_hiring),
]


def _gather_sections(wallet: str) -> dict:
    sections = {}
    for name, fetch_fn in SECTIONS:
        try:
            sections[name] = fetch_fn(wallet)
        except Exception as e:
            logger.warning("[PASSPORT] section '%s' failed for %s: %s", name, wallet, e)
            sections[name] = {"status": "unavailable"}
    return sections


@passport_bp.route("/<wallet>", methods=["GET"])
def passport(wallet: str):
    wallet = wallet.strip()
    if not wallet:
        return jsonify({"error": "WALLET_REQUIRED"}), 400

    sections = _gather_sections(wallet)

    return jsonify(clean_data({
        "wallet": wallet,
        **sections,
        "source_note": (
            "Every section above is a live read-through of an existing SqueezeOS store "
            "or the 402Proof credit bureau -- nothing here is estimated or fabricated. "
            "A section reading {'status': 'unavailable'} means that source could not be "
            "reached, not that the wallet has no activity."
        ),
        "ts": time.time(),
    }))


@passport_bp.route("/info", methods=["GET"])
def info():
    return jsonify({
        "endpoint": "/api/passport/<wallet>",
        "description": "Unified agent profile: trust score, marketplace earnings, futures/settlement/hiring history.",
        "sections": [name for name, _ in SECTIONS],
        "free": True,
    })


# ── HTML view ─────────────────────────────────────────────────────────────────

_PAGE_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0a0e1a">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Agent Passport">
<title>Agent Passport — SqueezeOS</title>
<link rel="apple-touch-icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 180 180'%3E%3Crect width='180' height='180' fill='%230a0e1a'/%3E%3Ctext x='90' y='115' font-family='monospace' font-size='58' font-weight='900' fill='%236090f0' text-anchor='middle'%3EAP%3C/text%3E%3C/svg%3E">
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font:14px/1.4 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0a0e1a;color:#e6e8ed;padding:env(safe-area-inset-top) 0 env(safe-area-inset-bottom)}
  main{max-width:900px;margin:0 auto;padding:12px}
  header{display:flex;justify-content:space-between;align-items:baseline;padding:8px 12px;border-bottom:1px solid #1a2030;margin-bottom:16px;flex-wrap:wrap;gap:8px}
  header h1{font-size:20px;font-weight:800;letter-spacing:-.5px}
  header .wallet{font-size:12px;color:#7f8aa3;font-family:monospace;word-break:break-all}
  section{margin-bottom:24px}
  h2{font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:1.2px;color:#9aa3bd;margin-bottom:10px;padding-left:4px}
  .grid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}
  @media(min-width:600px){.grid{grid-template-columns:repeat(4,1fr)}}
  .card{background:#10172a;border:1px solid #1a2030;border-radius:10px;padding:14px 12px;text-align:center}
  .card .num{font-size:22px;font-weight:800;color:#fff;font-family:monospace}
  .card .lbl{font-size:10px;color:#7f8aa3;text-transform:uppercase;letter-spacing:.5px;margin-top:4px}
  .unavailable{background:#1a1a30;border:1px solid #2a2050;border-radius:10px;padding:16px;color:#b8a8d8;font-size:13px}
  .footer{font-size:11px;color:#7f8aa3;padding:16px 12px;border-top:1px solid #1a2030;line-height:1.6}
  .footer a{color:#6090f0;text-decoration:none}
</style>
</head>
<body>
<main>
"""

_PAGE_TAIL = """
</main>
</body>
</html>
"""


def _card(num, lbl) -> str:
    return f'<div class="card"><div class="num">{_html.escape(str(num))}</div><div class="lbl">{_html.escape(str(lbl))}</div></div>'


def _render_html(wallet: str, sections: dict) -> str:
    parts = [_PAGE_HEAD]
    parts.append(f'<header><h1>Agent Passport</h1><div class="wallet">{_html.escape(wallet)}</div></header>')

    trust = sections.get("trust", {})
    if trust.get("status") == "unavailable":
        parts.append('<section><h2>Trust</h2><div class="unavailable">Trust data unavailable.</div></section>')
    else:
        composite = trust.get("composite_trust", {})
        parts.append('<section><h2>Trust</h2><div class="grid">')
        parts.append(_card(trust.get("ccs_score", "—"), "CCS Score"))
        parts.append(_card(trust.get("agent_credit_bureau_score") if trust.get("agent_credit_bureau_score") is not None else "—", "Credit Bureau"))
        parts.append(_card(composite.get("score", "—"), "Composite Trust"))
        parts.append(_card(trust.get("reputation_tier", "—"), "Reputation Tier"))
        parts.append('</div></section>')

    marketplace = sections.get("marketplace", {})
    parts.append('<section><h2>Marketplace</h2><div class="grid">')
    if marketplace.get("status") == "unavailable":
        parts.append('</div><div class="unavailable">Marketplace data unavailable.</div></section>')
    else:
        parts.append(_card(marketplace.get("sale_count", 0), "Sales"))
        parts.append(_card(f"{marketplace.get('balance_rlusd', 0):.2f}", "Balance RLUSD"))
        parts.append(_card(f"{marketplace.get('revenue_rlusd', 0):.2f}", "Revenue RLUSD"))
        parts.append('</div></section>')

    futures = sections.get("futures", {})
    settlement = sections.get("settlement", {})
    hiring = sections.get("hiring", {})
    parts.append('<section><h2>Activity</h2><div class="grid">')
    parts.append(_card(futures.get("count", "—") if futures.get("status") != "unavailable" else "—", "Futures"))
    parts.append(_card(settlement.get("count", "—") if settlement.get("status") != "unavailable" else "—", "Settlements"))
    if hiring.get("status") == "unavailable":
        parts.append(_card("—", "Jobs Posted"))
        parts.append(_card("—", "Jobs Executed"))
    else:
        parts.append(_card(hiring.get("posted", {}).get("count", 0), "Jobs Posted"))
        parts.append(_card(hiring.get("executed", {}).get("count", 0), "Jobs Executed"))
    parts.append('</div></section>')

    parts.append(
        '<div class="footer"><p>Every section is a live read-through of an existing SqueezeOS store or the '
        '402Proof credit bureau — nothing here is estimated or fabricated. A card reading "—" means that source '
        'was unavailable, not that the wallet has no activity.</p>'
        f'<p>JSON: <a href="/api/passport/{_html.escape(wallet)}">/api/passport/{_html.escape(wallet)}</a></p></div>'
    )
    parts.append(_PAGE_TAIL)
    return ''.join(parts)


@passport_bp.route("/<wallet>/view", methods=["GET"])
def passport_view(wallet: str):
    wallet = wallet.strip()
    if not wallet:
        return jsonify({"error": "WALLET_REQUIRED"}), 400
    sections = _gather_sections(wallet)
    return Response(_render_html(wallet, sections), mimetype="text/html")
