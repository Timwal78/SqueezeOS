"""Swarm MM proxy for Trade Desk (Swarm Agents Intelligence).

Abacus frontend cannot hold operator keys. SqueezeOS proxies free + desk
calls to https://swarm-mm.onrender.com with server-side X-Operator-Key.

Routes (all under /api/swarm-mm):
  GET  /health
  GET  /panel          — embeddable HTML for iframe in Abacus UI
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
import urllib.error
import urllib.parse
import urllib.request

from flask import Blueprint, Response, jsonify, request

log = logging.getLogger("swarm_mm_proxy")

swarm_mm_bp = Blueprint("swarm_mm", __name__)

_SWARM_MM_BASE = os.environ.get("SWARM_MM_BASE_URL", "https://swarm-mm.onrender.com").rstrip("/")
_OP_KEY = (
    os.environ.get("SML_API_KEY")
    or os.environ.get("SML_ACP_ABACUS_KEY")
    or os.environ.get("TRADE_DESK_OWNER_KEY")
    or ""
)
_UA = "SqueezeOS-SwarmMM-Proxy/1.0 (+https://swarmagentsintelligence.scriptmasterlabs.com)"

# Desk origins allowed to iframe /api/swarm-mm/panel (also enforced in app.py CSP).
_FRAME_ANCESTORS = (
    "'self' "
    "https://scriptmasterlabs.abacusai.app "
    "https://swarmagentsintelligence.scriptmasterlabs.com "
    "https://www.scriptmasterlabs.com "
    "https://scriptmasterlabs.com "
    "https://squeezeos-api.onrender.com"
)


def _upstream(method: str, path: str, query: dict | None = None, body: dict | None = None, paid: bool = False):
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
            payload = {"error": raw[:500]}
        return e.code, payload
    except Exception as e:
        log.warning("swarm-mm upstream fail %s %s: %s", method, path, e)
        return 502, {"error": "swarm_mm_upstream_unavailable", "detail": str(e)[:200], "base": _SWARM_MM_BASE}


@swarm_mm_bp.get("/health")
def health():
    code, body = _upstream("GET", "/health")
    return jsonify({
        "proxy": "ok",
        "upstream_status": code,
        "swarm_mm": body,
        "base": _SWARM_MM_BASE,
        "operator_key_configured": bool(_OP_KEY),
        "panel_embed": {
            "url": "/api/swarm-mm/panel",
            "frame_ancestors": _FRAME_ANCESTORS,
            "preferred_for_desk": True,
        },
    }), (200 if code == 200 else 502)


@swarm_mm_bp.get("/pricing")
def pricing():
    code, body = _upstream("GET", "/v1/pricing")
    return jsonify(body), code


@swarm_mm_bp.get("/levels")
def levels():
    ticker = request.args.get("ticker") or request.args.get("symbol") or "IWM"
    side = request.args.get("side") or "buy"
    code, body = _upstream("GET", "/v1/signal/levels", {"ticker": ticker, "side": side}, paid=True)
    return jsonify(body), code


@swarm_mm_bp.get("/venue-map")
def venue_map():
    ticker = request.args.get("ticker") or request.args.get("symbol") or "IWM"
    code, body = _upstream("GET", "/v1/signal/venue-map", {"ticker": ticker}, paid=True)
    return jsonify(body), code


@swarm_mm_bp.get("/rebate")
def rebate():
    user_id = request.args.get("user_id") or "desk"
    ticker = request.args.get("ticker") or request.args.get("symbol") or "IWM"
    code, body = _upstream(
        "GET",
        "/v1/signal/rebate-tracker",
        {"user_id": user_id, "ticker": ticker},
        paid=True,
    )
    return jsonify(body), code


@swarm_mm_bp.get("/brokers")
def brokers():
    code, body = _upstream("GET", "/v1/signal/brokers", paid=True)
    return jsonify(body), code


@swarm_mm_bp.post("/sim/join")
def sim_join():
    payload = request.get_json(silent=True) or {}
    if not payload.get("user_id"):
        payload["user_id"] = request.args.get("user_id") or "timothy_walton"
    if "starting_balance" not in payload:
        payload["starting_balance"] = 100000
    code, body = _upstream("POST", "/v1/sim/join", body=payload)
    return jsonify(body), code


@swarm_mm_bp.post("/sim/trade")
def sim_trade():
    payload = request.get_json(silent=True) or {}
    code, body = _upstream("POST", "/v1/sim/trade", body=payload)
    return jsonify(body), code


@swarm_mm_bp.get("/sim/leaderboard")
def sim_leaderboard():
    tf = request.args.get("timeframe") or "all_time"
    code, body = _upstream("GET", "/v1/sim/leaderboard", {"timeframe": tf})
    return jsonify(body), code


@swarm_mm_bp.get("/sim/account/<user_id>")
def sim_account(user_id: str):
    code, body = _upstream("GET", f"/v1/sim/account/{urllib.parse.quote(user_id)}")
    return jsonify(body), code


# Same-origin panel: all fetches hit /api/swarm-mm/* so CSP default-src 'self' works
# and X-Operator-Key stays server-side on paid routes.
_PANEL_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Swarm MM — Desk Panel</title>
<style>
  :root { --bg:#070b14; --card:#0f172a; --line:#1e293b; --tx:#e2e8f0; --mut:#94a3b8; --go:#22c55e; --accent:#38bdf8; }
  *{box-sizing:border-box} body{margin:0;font-family:ui-sans-serif,system-ui,sans-serif;background:var(--bg);color:var(--tx);padding:12px}
  h1{font-size:15px;margin:0 0 4px} .sub{color:var(--mut);font-size:12px;margin-bottom:12px}
  .row{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px;align-items:end}
  label{font-size:11px;color:var(--mut);display:block;margin-bottom:3px}
  input,select,button{background:#020617;border:1px solid var(--line);color:var(--tx);border-radius:8px;padding:8px 10px;font-size:13px}
  button{background:linear-gradient(135deg,#0369a1,#0ea5e9);border:0;font-weight:700;cursor:pointer}
  button.secondary{background:#1e293b}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
  @media(max-width:720px){.grid{grid-template-columns:1fr}}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}
  .card h2{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--mut);margin:0 0 8px}
  pre{white-space:pre-wrap;word-break:break-word;font-size:11px;line-height:1.4;margin:0;max-height:280px;overflow:auto}
  .pill{display:inline-block;padding:2px 8px;border-radius:999px;background:#052e16;color:var(--go);font-size:11px;font-weight:700}
  .err{color:#f87171}
  a{color:var(--accent)}
</style>
</head>
<body>
  <h1>Swarm MM <span class="pill">DESK PROXY</span></h1>
  <div class="sub">Same-origin via SqueezeOS · operator key server-side · free paper · limit levels · your broker executes</div>
  <div class="row">
    <div><label>Ticker</label><input id="ticker" value="IWM" size="8"/></div>
    <div><label>Side</label><select id="side"><option>buy</option><option>sell</option></select></div>
    <div><label>User ID</label><input id="uid" value="timothy_walton" size="16"/></div>
    <button onclick="loadAll()">Refresh swarm</button>
    <button class="secondary" onclick="joinSim()">Join paper $100k</button>
  </div>
  <div class="grid">
    <div class="card"><h2>Limit levels</h2><pre id="levels">—</pre></div>
    <div class="card"><h2>Venue map</h2><pre id="venue">—</pre></div>
    <div class="card"><h2>Paper account</h2><pre id="sim">—</pre></div>
    <div class="card"><h2>Leaderboard</h2><pre id="lb">—</pre></div>
  </div>
  <p class="sub" style="margin-top:12px">
    Proxy base: <code>/api/swarm-mm</code> · Upstream: __UPSTREAM__ ·
    Direct panel fallback: <a href="__UPSTREAM__/panel" target="_blank" rel="noopener">swarm-mm/panel</a>
  </p>
<script>
// Same-origin only — works under SqueezeOS CSP + keeps operator key off the browser.
const API = '/api/swarm-mm';
async function jget(path){
  const r = await fetch(API + path, {headers:{'Accept':'application/json'}});
  const t = await r.text(); let b; try{b=JSON.parse(t)}catch(e){b={raw:t}}
  return {status:r.status, body:b};
}
async function jpost(path, body){
  const r = await fetch(API + path, {
    method:'POST',
    headers:{'Content-Type':'application/json','Accept':'application/json'},
    body:JSON.stringify(body||{})
  });
  const t = await r.text(); let b; try{b=JSON.parse(t)}catch(e){b={raw:t}}
  return {status:r.status, body:b};
}
function show(id, status, body){
  const el = document.getElementById(id);
  el.textContent = 'HTTP '+status+'\n' + JSON.stringify(body, null, 2);
  el.className = status >= 400 ? 'err' : '';
}
async function loadAll(){
  const t = (document.getElementById('ticker').value||'IWM').trim().toUpperCase();
  const side = document.getElementById('side').value;
  const uid = (document.getElementById('uid').value||'timothy_walton').trim();
  const [L,V,LB,A] = await Promise.all([
    jget('/levels?ticker='+encodeURIComponent(t)+'&side='+side),
    jget('/venue-map?ticker='+encodeURIComponent(t)),
    jget('/sim/leaderboard?timeframe=all_time'),
    jget('/sim/account/'+encodeURIComponent(uid)),
  ]);
  show('levels', L.status, L.body);
  show('venue', V.status, V.body);
  show('lb', LB.status, LB.body);
  show('sim', A.status, A.body);
}
async function joinSim(){
  const uid = (document.getElementById('uid').value||'timothy_walton').trim();
  const r = await jpost('/sim/join', {user_id: uid, starting_balance: 100000});
  show('sim', r.status, r.body);
  loadAll();
}
loadAll();
</script>
</body>
</html>
"""


@swarm_mm_bp.get("/panel")
def panel():
    html = _PANEL_HTML.replace("__UPSTREAM__", _SWARM_MM_BASE)
    resp = Response(html, mimetype="text/html; charset=utf-8")
    # Belt-and-suspenders: set embed headers on the response object too
    # (global after_request also special-cases this path).
    resp.headers.pop("X-Frame-Options", None)
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        f"frame-ancestors {_FRAME_ANCESTORS}"
    )
    return resp
