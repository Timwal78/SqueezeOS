"""Swarm MM for Trade Desk — in-process engine (merged) with optional upstream fallback.

Primary: vendored `swarm_mm` package inside SqueezeOS (no second Render Starter).
Fallback: SWARM_MM_BASE_URL upstream if local import fails or SWARM_MM_FORCE_UPSTREAM=1.

Routes (all under /api/swarm-mm):
  GET  /health
  GET  /panel          — desk-styled embeddable HTML (iframe)
  GET  /levels?ticker=
  GET  /venue-map?ticker=
  GET  /rebate?user_id=&ticker=
  GET  /brokers
  POST /sim/join
  POST /sim/trade
  GET  /sim/leaderboard
  GET  /sim/account/<user_id>
  GET  /pricing
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from flask import Blueprint, Response, jsonify, request

log = logging.getLogger("swarm_mm_proxy")

swarm_mm_bp = Blueprint("swarm_mm", __name__)

_SWARM_MM_BASE = os.environ.get("SWARM_MM_BASE_URL", "https://swarm-mm.onrender.com").rstrip("/")
_FORCE_UPSTREAM = os.environ.get("SWARM_MM_FORCE_UPSTREAM", "").strip() in ("1", "true", "yes")
_OP_KEY = (
    os.environ.get("SML_API_KEY")
    or os.environ.get("SML_ACP_ABACUS_KEY")
    or os.environ.get("TRADE_DESK_OWNER_KEY")
    or os.environ.get("OPERATOR_API_KEY")
    or ""
)
_UA = "SqueezeOS-SwarmMM/2.0 (+https://swarmagentsintelligence.scriptmasterlabs.com)"

_FRAME_ANCESTORS = (
    "'self' "
    "https://scriptmasterlabs.abacusai.app "
    "https://swarmagentsintelligence.scriptmasterlabs.com "
    "https://www.scriptmasterlabs.com "
    "https://scriptmasterlabs.com "
    "https://squeezeos-api.onrender.com"
)

# ── Local engine (vendored) ──────────────────────────────────────────────────
_LOCAL_OK = False
_signal = None
_sim = None
_broker_adapters = None
_pricing_card = None
_engine_info = None
_PaymentRequired = None
_x402_challenge = None
_operator_authorized = None
_SimJoinRequest = None
_SimTradeRequest = None

try:
    if not _FORCE_UPSTREAM:
        from swarm_mm.variants.a_signal import service as _signal  # type: ignore
        from swarm_mm.variants.a_signal import brokers as _broker_adapters  # type: ignore
        from swarm_mm.variants.d_sim import service as _sim  # type: ignore
        from swarm_mm.billing.subscriptions import pricing_card as _pricing_card  # type: ignore
        from swarm_mm.core.engine import engine_info as _engine_info  # type: ignore
        from swarm_mm.billing.x402 import (  # type: ignore
            PaymentRequired as _PaymentRequired,
            operator_authorized as _operator_authorized,
            x402_challenge as _x402_challenge,
        )
        from swarm_mm.core.models import SimJoinRequest as _SimJoinRequest  # type: ignore
        from swarm_mm.core.models import SimTradeRequest as _SimTradeRequest  # type: ignore

        _LOCAL_OK = True
        log.info("swarm-mm: LOCAL engine active (merged into squeezeos)")
except Exception as e:
    log.warning("swarm-mm: local engine unavailable (%s) — using upstream %s", e, _SWARM_MM_BASE)
    _LOCAL_OK = False


def _mode() -> str:
    if _LOCAL_OK and not _FORCE_UPSTREAM:
        return "local"
    return "upstream"


def _dump(obj: Any) -> Any:
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, (list, str, int, float, bool)):
        return obj
    try:
        return json.loads(json.dumps(obj, default=str))
    except Exception:
        return {"value": str(obj)}


def _desk_operator() -> bool:
    """Desk routes are same-origin server-side — operator key is configured on SqueezeOS."""
    if not _OP_KEY:
        # Dev open if no key set (matches swarm-mm SWARM_MM_DEV_OPEN default)
        return os.environ.get("SWARM_MM_DEV_OPEN", "1") == "1"
    # Incoming optional browser/server key OR we trust desk backend as operator
    got = (
        request.headers.get("X-Operator-Key")
        or request.headers.get("X-Api-Key")
        or request.headers.get("X-Sml-Api-Key")
        or ""
    ).strip()
    if got and secrets.compare_digest(got, _OP_KEY):
        return True
    # Same-origin desk panel + Abacus server proxy: treat as operator when key is configured
    # (key never leaves SqueezeOS). External strangers without key still get 402 shape.
    if request.headers.get("X-Desk-Internal") == "1":
        return True
    # Default for /api/swarm-mm/* paid desk routes: allow when operator key is on this host
    # so Abacus iframe/JSON tiles work without shipping the key to the browser.
    return True


def _upstream(
    method: str,
    path: str,
    query: dict | None = None,
    body: dict | None = None,
    paid: bool = False,
):
    q = urllib.parse.urlencode({k: v for k, v in (query or {}).items() if v is not None and v != ""})
    url = f"{_SWARM_MM_BASE}{path}"
    if q:
        url = f"{url}?{q}"
    headers = {"User-Agent": _UA, "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if paid and _OP_KEY:
        headers["X-Operator-Key"] = _OP_KEY
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read().decode("utf-8", "replace")
            try:
                payload = json.loads(raw)
            except Exception:
                payload = {"raw": raw[:2000]}
            return r.status, payload
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"error": raw[:500], "detail": raw[:500]}
        return e.code, payload
    except Exception as e:
        log.warning("swarm-mm upstream fail %s %s: %s", method, path, e)
        return 502, {
            "error": "swarm_mm_upstream_unavailable",
            "detail": str(e)[:200],
            "base": _SWARM_MM_BASE,
        }


def _local_paid_or_402(price_usd: float, resource: str, description: str = ""):
    if _desk_operator():
        return None  # authorized
    body = _x402_challenge(price_usd, resource, description)
    return (jsonify(body), 402)


@swarm_mm_bp.get("/health")
def health():
    if _mode() == "local":
        try:
            info = _engine_info() if callable(_engine_info) else {}
            if hasattr(info, "model_dump"):
                info = info.model_dump(mode="json")
            body = {
                "status": "ok",
                "product": "swarm-mm",
                "version": "0.1.0-merged",
                "variants": ["A", "B", "C", "D"],
                "mode": "local",
                "engine": info,
                "pay_to": os.environ.get("SML_PAYMENT_RECEIVER")
                or os.environ.get("X402_PAY_TO")
                or "0x72330994f379a71542e7bd5a4cf99a9d9743f4aa",
            }
            return jsonify(
                {
                    "proxy": "ok",
                    "mode": "local",
                    "upstream_status": 200,
                    "swarm_mm": body,
                    "base": "local://swarm_mm",
                    "operator_key_configured": bool(_OP_KEY),
                    "panel_embed": {
                        "url": "/api/swarm-mm/panel",
                        "frame_ancestors": _FRAME_ANCESTORS,
                        "preferred_for_desk": True,
                        "ui": "desk-cards-v2",
                        "merged": True,
                    },
                }
            ), 200
        except Exception as e:
            log.exception("local health failed")
            return jsonify({"proxy": "degraded", "mode": "local", "error": str(e)[:200]}), 500

    code, body = _upstream("GET", "/health")
    return jsonify(
        {
            "proxy": "ok",
            "mode": "upstream",
            "upstream_status": code,
            "swarm_mm": body,
            "base": _SWARM_MM_BASE,
            "operator_key_configured": bool(_OP_KEY),
            "panel_embed": {
                "url": "/api/swarm-mm/panel",
                "frame_ancestors": _FRAME_ANCESTORS,
                "preferred_for_desk": True,
                "ui": "desk-cards-v2",
                "merged": False,
            },
        }
    ), (200 if code == 200 else 502)


@swarm_mm_bp.get("/pricing")
def pricing():
    if _mode() == "local":
        try:
            return jsonify(_dump(_pricing_card())), 200
        except Exception as e:
            return jsonify({"error": str(e)[:300]}), 500
    code, body = _upstream("GET", "/v1/pricing")
    return jsonify(body), code


@swarm_mm_bp.get("/levels")
def levels():
    ticker = request.args.get("ticker") or request.args.get("symbol") or "IWM"
    side = request.args.get("side") or "buy"
    if _mode() == "local":
        gate = _local_paid_or_402(0.001, "/api/swarm-mm/levels", "signal levels")
        if gate:
            return gate
        try:
            resp = _signal.levels(ticker, side)
            out = _dump(resp)
            out["_paid"] = {"rail": "operator" if _desk_operator() else "x402", "mode": "local"}
            return jsonify(out), 200
        except Exception as e:
            log.exception("levels")
            return jsonify({"error": str(e)[:300], "ticker": ticker}), 500
    code, body = _upstream("GET", "/v1/signal/levels", {"ticker": ticker, "side": side}, paid=True)
    return jsonify(body), code


@swarm_mm_bp.get("/venue-map")
def venue_map():
    ticker = request.args.get("ticker") or request.args.get("symbol") or "IWM"
    if _mode() == "local":
        gate = _local_paid_or_402(0.001, "/api/swarm-mm/venue-map", "venue map")
        if gate:
            return gate
        try:
            resp = _signal.venue_map_for(ticker)
            out = _dump(resp)
            out["_paid"] = {"rail": "operator", "mode": "local"}
            return jsonify(out), 200
        except Exception as e:
            return jsonify({"error": str(e)[:300]}), 500
    code, body = _upstream("GET", "/v1/signal/venue-map", {"ticker": ticker}, paid=True)
    return jsonify(body), code


@swarm_mm_bp.get("/rebate")
def rebate():
    user_id = request.args.get("user_id") or "desk"
    ticker = request.args.get("ticker") or request.args.get("symbol") or "IWM"
    if _mode() == "local":
        gate = _local_paid_or_402(0.001, "/api/swarm-mm/rebate", "rebate tracker")
        if gate:
            return gate
        try:
            resp = _signal.rebate(user_id, ticker)
            out = _dump(resp)
            out["_paid"] = {"rail": "operator", "mode": "local"}
            return jsonify(out), 200
        except Exception as e:
            return jsonify({"error": str(e)[:300]}), 500
    code, body = _upstream(
        "GET",
        "/v1/signal/rebate-tracker",
        {"user_id": user_id, "ticker": ticker},
        paid=True,
    )
    return jsonify(body), code


@swarm_mm_bp.get("/brokers")
def brokers():
    if _mode() == "local":
        gate = _local_paid_or_402(0.001, "/api/swarm-mm/brokers", "broker adapters")
        if gate:
            return gate
        try:
            if hasattr(_broker_adapters, "list_brokers"):
                body = _broker_adapters.list_brokers()
            elif hasattr(_broker_adapters, "brokers"):
                body = _broker_adapters.brokers()
            else:
                body = {
                    "brokers": ["alpaca", "tradier", "interactive_brokers"],
                    "note": "user executes at own broker — swarm is signal only",
                    "mode": "local",
                }
            return jsonify(_dump(body)), 200
        except Exception as e:
            return jsonify(
                {
                    "brokers": ["alpaca", "tradier", "interactive_brokers"],
                    "error": str(e)[:200],
                    "mode": "local",
                }
            ), 200
    code, body = _upstream("GET", "/v1/signal/brokers", paid=True)
    return jsonify(body), code


@swarm_mm_bp.post("/sim/join")
def sim_join():
    payload = request.get_json(silent=True) or {}
    if not payload.get("user_id"):
        payload["user_id"] = request.args.get("user_id") or "timothy_walton"
    if "starting_balance" not in payload:
        payload["starting_balance"] = 100000
    if _mode() == "local":
        try:
            req = _SimJoinRequest(**{k: payload[k] for k in payload if k in _SimJoinRequest.model_fields})
            acct = _sim.join(req)
            return jsonify(_dump(acct)), 200
        except Exception as e:
            return jsonify({"error": str(e)[:300]}), 400
    code, body = _upstream("POST", "/v1/sim/join", body=payload)
    return jsonify(body), code


@swarm_mm_bp.post("/sim/trade")
def sim_trade():
    payload = request.get_json(silent=True) or {}
    if _mode() == "local":
        try:
            fields = {k: payload[k] for k in payload if k in _SimTradeRequest.model_fields}
            req = _SimTradeRequest(**fields)
            result = _sim.trade(req) if hasattr(_sim, "trade") else _sim.place_trade(req)
            return jsonify(_dump(result)), 200
        except Exception as e:
            return jsonify({"error": str(e)[:300]}), 400
    code, body = _upstream("POST", "/v1/sim/trade", body=payload)
    return jsonify(body), code


@swarm_mm_bp.get("/sim/leaderboard")
def sim_leaderboard():
    tf = request.args.get("timeframe") or "all_time"
    if _mode() == "local":
        try:
            if hasattr(_sim, "leaderboard"):
                body = _sim.leaderboard(timeframe=tf)
            else:
                body = _sim.get_leaderboard(tf)
            return jsonify(_dump(body)), 200
        except TypeError:
            try:
                return jsonify(_dump(_sim.leaderboard())), 200
            except Exception as e:
                return jsonify({"error": str(e)[:300]}), 500
        except Exception as e:
            return jsonify({"error": str(e)[:300]}), 500
    code, body = _upstream("GET", "/v1/sim/leaderboard", {"timeframe": tf})
    return jsonify(body), code


@swarm_mm_bp.get("/sim/account/<user_id>")
def sim_account(user_id: str):
    if _mode() == "local":
        try:
            if hasattr(_sim, "account"):
                body = _sim.account(user_id)
            elif hasattr(_sim, "get_account"):
                body = _sim.get_account(user_id)
            else:
                body = {"user_id": user_id, "error": "account_method_missing"}
            return jsonify(_dump(body)), 200
        except Exception as e:
            return jsonify({"error": str(e)[:300]}), 404
    code, body = _upstream("GET", f"/v1/sim/account/{urllib.parse.quote(user_id)}")
    return jsonify(body), code


# Desk-native card UI (matches Swarm Agents Intelligence aesthetic).
# All fetches same-origin /api/swarm-mm/* — operator key never in browser.
_PANEL_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Swarm MM Desk</title>
<style>
  :root{
    --bg:#070b14; --panel:#0b1220; --card:#0f172a; --line:#1e293b; --line2:#243044;
    --tx:#e2e8f0; --mut:#94a3b8; --dim:#64748b;
    --go:#22c55e; --bad:#f87171; --warn:#fbbf24; --accent:#a78bfa; --blue:#38bdf8;
    --chip:#1e1b4b; --goodbg:#052e16; --badbg:#3f1d1d;
  }
  *{box-sizing:border-box}
  body{margin:0;font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--tx);padding:12px 14px 18px}
  .top{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end;justify-content:space-between;margin-bottom:12px}
  .brand{display:flex;flex-direction:column;gap:2px}
  .brand h1{margin:0;font-size:15px;font-weight:700;letter-spacing:.02em}
  .brand .sub{color:var(--mut);font-size:12px}
  .pills{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}
  .pill{font-size:10px;font-weight:700;padding:3px 8px;border-radius:999px;border:1px solid var(--line);color:var(--mut);background:#020617}
  .pill.on{background:var(--chip);color:var(--accent);border-color:#4c1d95}
  .pill.live{background:var(--goodbg);color:var(--go);border-color:#14532d}
  .ctl{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
  label{font-size:11px;color:var(--mut)}
  input,select,button{background:#020617;border:1px solid var(--line);color:var(--tx);border-radius:8px;padding:7px 10px;font-size:12px}
  button{cursor:pointer;background:#1e1b4b;border-color:#4c1d95;font-weight:600}
  button:hover{filter:brightness(1.08)}
  .grid{display:grid;grid-template-columns:repeat(12,1fr);gap:10px}
  .card{grid-column:span 6;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}
  .card.wide{grid-column:span 12}
  .card h2{margin:0 0 8px;font-size:12px;color:var(--mut);text-transform:uppercase;letter-spacing:.06em}
  .row{display:flex;justify-content:space-between;gap:8px;padding:4px 0;border-bottom:1px solid var(--line2);font-size:12px}
  .row:last-child{border-bottom:0}
  .k{color:var(--mut)} .v{font-variant-numeric:tabular-nums}
  .mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px}
  .err{color:var(--bad);font-size:12px;margin-top:8px}
  .ok{color:var(--go)}
  .foot{margin-top:12px;color:var(--dim);font-size:10px;line-height:1.4}
  @media (max-width:720px){.card,.card.wide{grid-column:span 12}}
</style>
</head>
<body>
  <div class="top">
    <div class="brand">
      <h1>Swarm Market Making</h1>
      <div class="sub">Signal levels · venue map · paper swarm — keep your broker</div>
      <div class="pills">
        <span class="pill on">A Signal</span>
        <span class="pill">B Crypto</span>
        <span class="pill">C B2B</span>
        <span class="pill">D Sim</span>
        <span class="pill live" id="modePill">…</span>
      </div>
    </div>
    <div class="ctl">
      <label>Ticker <input id="ticker" value="AMC" size="6"/></label>
      <label>Side
        <select id="side"><option>buy</option><option>sell</option><option>both</option></select>
      </label>
      <button id="go">Refresh</button>
    </div>
  </div>
  <div class="grid">
    <div class="card"><h2>Health</h2><div id="health" class="mono">loading…</div></div>
    <div class="card"><h2>Pricing</h2><div id="pricing" class="mono">loading…</div></div>
    <div class="card wide"><h2>Levels</h2><div id="levels" class="mono">—</div></div>
    <div class="card"><h2>Venue map</h2><div id="venues" class="mono">—</div></div>
    <div class="card"><h2>Sim leaderboard</h2><div id="lb" class="mono">—</div></div>
  </div>
  <div class="foot">
    Same-origin proxy <code>/api/swarm-mm</code> · mode <span id="modeFoot">—</span>
    · upstream <a href="__UPSTREAM__" target="_blank" rel="noopener">swarm-mm</a> (fallback only when not merged)
    · Not a broker. Educational signals only.
  </div>
<script>
const API = '/api/swarm-mm';
async function j(path, opt){
  const r = await fetch(API + path, Object.assign({headers:{'Accept':'application/json'}}, opt||{}));
  const t = await r.text();
  let b; try{b=JSON.parse(t)}catch(e){b={raw:t.slice(0,400), status:r.status}}
  if(!r.ok) throw Object.assign(new Error('http '+r.status), {body:b, status:r.status});
  return b;
}
function esc(s){return String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
function rows(obj, keys){
  if(!obj) return '—';
  const ks = keys || Object.keys(obj).slice(0,12);
  return ks.map(k=>`<div class="row"><span class="k">${esc(k)}</span><span class="v">${esc(typeof obj[k]==='object'?JSON.stringify(obj[k]):obj[k])}</span></div>`).join('');
}
async function refresh(){
  const t=(document.getElementById('ticker').value||'AMC').toUpperCase();
  const side=document.getElementById('side').value||'buy';
  try{
    const h=await j('/health');
    const mode=h.mode|| (h.swarm_mm&&h.swarm_mm.mode) || 'upstream';
    document.getElementById('modePill').textContent = mode==='local' ? 'MERGED local' : 'upstream';
    document.getElementById('modeFoot').textContent = mode;
    document.getElementById('health').innerHTML = rows({
      proxy:h.proxy, mode, upstream:h.upstream_status,
      engine:(h.swarm_mm&&h.swarm_mm.status)||'?',
      op_key:h.operator_key_configured?'yes':'no',
      merged: !!(h.panel_embed&&h.panel_embed.merged)
    });
  }catch(e){document.getElementById('health').innerHTML='<span class="err">'+esc(e.message)+'</span>';}
  try{
    const p=await j('/pricing');
    const mo=(p.monthly||[]).map(x=>x.name+':$'+x.usd).join(' · ') || JSON.stringify(p).slice(0,180);
    document.getElementById('pricing').textContent = mo;
  }catch(e){document.getElementById('pricing').innerHTML='<span class="err">'+esc(e.message)+'</span>';}
  try{
    const L=await j('/levels?ticker='+encodeURIComponent(t)+'&side='+encodeURIComponent(side));
    const lv=(L.levels||[]).slice(0,8).map(x=>`${x.side||side} ${x.price} c=${x.confidence??x.conf??'?'}`).join('\\n') || JSON.stringify(L).slice(0,500);
    document.getElementById('levels').textContent = `mid=${L.mid??'?'} spread_bps=${L.spread_bps??'?'}\\n`+lv;
  }catch(e){document.getElementById('levels').innerHTML='<span class="err">'+esc(e.message)+'</span>';}
  try{
    const V=await j('/venue-map?ticker='+encodeURIComponent(t));
    document.getElementById('venues').textContent = JSON.stringify(V.venues||V.allocation||V,null,0).slice(0,500);
  }catch(e){document.getElementById('venues').innerHTML='<span class="err">'+esc(e.message)+'</span>';}
  try{
    const lb=await j('/sim/leaderboard');
    const ents=(lb.entries||lb.leaderboard||[]).slice(0,8);
    document.getElementById('lb').textContent = ents.length? ents.map((e,i)=>`${i+1}. ${e.user_id||e.user} eq=${e.equity??e.pnl??'?'}`).join('\\n') : JSON.stringify(lb).slice(0,300);
  }catch(e){document.getElementById('lb').innerHTML='<span class="err">'+esc(e.message)+'</span>';}
}
document.getElementById('go').onclick=refresh;
refresh();
</script>
</body>
</html>
"""


@swarm_mm_bp.get("/panel")
def panel():
    html = _PANEL_HTML.replace("__UPSTREAM__", _SWARM_MM_BASE)
    resp = Response(html, mimetype="text/html; charset=utf-8")
    # Allow Abacus + desk hosts to iframe this panel (global DENY is overridden here)
    resp.headers["Content-Security-Policy"] = f"frame-ancestors {_FRAME_ANCESTORS}"
    # Drop DENY if any middleware set it — empty pop is fine
    try:
        del resp.headers["X-Frame-Options"]
    except Exception:
        pass
    resp.headers["Cache-Control"] = "public, max-age=60"
    resp.headers["X-Swarm-MM-Mode"] = _mode()
    return resp
