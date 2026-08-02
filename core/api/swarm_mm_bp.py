"""Swarm MM proxy for Trade Desk (Swarm Agents Intelligence).

Abacus frontend cannot hold operator keys. SqueezeOS proxies free + desk
calls to https://swarm-mm.onrender.com with server-side X-Operator-Key.

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
            payload = {"error": raw[:500], "detail": raw[:500]}
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
            "ui": "desk-cards-v2",
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
  .controls{display:flex;gap:8px;flex-wrap:wrap;align-items:end}
  label{display:block;font-size:10px;color:var(--dim);margin-bottom:3px;text-transform:uppercase;letter-spacing:.06em}
  input,select,button{background:#020617;border:1px solid var(--line);color:var(--tx);border-radius:8px;padding:8px 10px;font-size:13px}
  input:focus,select:focus{outline:1px solid #7c3aed;border-color:#7c3aed}
  button{background:linear-gradient(135deg,#5b21b6,#7c3aed);border:0;font-weight:700;cursor:pointer}
  button:hover{filter:brightness(1.08)}
  button.secondary{background:#1e293b}
  button:disabled{opacity:.5;cursor:wait}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
  @media(max-width:820px){.grid{grid-template-columns:1fr}}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 12px 10px;min-height:180px;display:flex;flex-direction:column}
  .card head,.ch{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:10px}
  .ch h2{margin:0;font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--mut)}
  .badge{font-size:10px;font-weight:700;padding:2px 7px;border-radius:999px;background:#020617;border:1px solid var(--line);color:var(--mut)}
  .badge.ok{color:var(--go);border-color:#14532d;background:var(--goodbg)}
  .badge.err{color:var(--bad);border-color:#7f1d1d;background:var(--badbg)}
  .badge.warn{color:var(--warn);border-color:#854d0e;background:#1c1408}
  .body{flex:1;min-height:0}
  .empty{color:var(--dim);font-size:12px;padding:8px 2px;line-height:1.45}
  .errtxt{color:var(--bad);font-size:12px}
  table{width:100%;border-collapse:collapse;font-size:12px}
  th{text-align:left;color:var(--dim);font-weight:600;font-size:10px;text-transform:uppercase;letter-spacing:.05em;padding:0 6px 6px 0;border-bottom:1px solid var(--line)}
  td{padding:7px 6px 7px 0;border-bottom:1px solid var(--line2);vertical-align:top}
  tr:last-child td{border-bottom:0}
  .px{font-variant-numeric:tabular-nums;font-weight:700;color:#fff}
  .mut{color:var(--mut)}
  .go{color:var(--go)} .bad{color:var(--bad)} .blue{color:var(--blue)} .purp{color:var(--accent)}
  .side-buy{color:var(--go);font-weight:700;text-transform:uppercase;font-size:10px}
  .side-sell{color:var(--bad);font-weight:700;text-transform:uppercase;font-size:10px}
  .barwrap{display:flex;flex-direction:column;gap:8px}
  .vrow{display:grid;grid-template-columns:64px 1fr 48px;gap:8px;align-items:center}
  .vname{font-weight:700;font-size:12px}
  .track{height:8px;background:#020617;border:1px solid var(--line);border-radius:999px;overflow:hidden}
  .fill{height:100%;background:linear-gradient(90deg,#6d28d9,#38bdf8);border-radius:999px}
  .pct{font-size:11px;color:var(--mut);text-align:right;font-variant-numeric:tabular-nums}
  .statgrid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
  .stat{background:#020617;border:1px solid var(--line);border-radius:10px;padding:8px 10px}
  .stat .k{font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:.05em}
  .stat .v{font-size:15px;font-weight:700;margin-top:2px;font-variant-numeric:tabular-nums}
  .foot{margin-top:10px;font-size:11px;color:var(--dim);line-height:1.4}
  .foot a{color:var(--blue);text-decoration:none}
  .disc{margin-top:8px;font-size:10px;color:var(--dim);line-height:1.35}
  .lb-row{display:flex;justify-content:space-between;gap:8px;padding:6px 0;border-bottom:1px solid var(--line2);font-size:12px}
  .lb-row:last-child{border-bottom:0}
  .rank{color:var(--accent);font-weight:700;width:28px}
</style>
</head>
<body>
  <div class="top">
    <div class="brand">
      <h1>Swarm MM Desk</h1>
      <div class="sub">Coordination without custody · resting levels at <em>your</em> broker</div>
      <div class="pills">
        <span class="pill on">SIGNAL</span>
        <span class="pill live">PAPER FREE</span>
        <span class="pill">PROXY</span>
        <span class="pill" id="feedPill">LOADING</span>
      </div>
    </div>
    <div class="controls">
      <div><label>Ticker</label><input id="ticker" value="IWM" size="7"/></div>
      <div><label>Side</label><select id="side"><option>buy</option><option>sell</option></select></div>
      <div><label>User ID</label><input id="uid" value="timothy_walton" size="14"/></div>
      <button id="btnRefresh" onclick="loadAll()">Refresh</button>
      <button class="secondary" id="btnJoin" onclick="joinSim()">Join paper $100k</button>
    </div>
  </div>

  <div class="grid">
    <section class="card">
      <div class="ch"><h2>Limit levels</h2><span class="badge" id="lvlBadge">—</span></div>
      <div class="body" id="levels"><div class="empty">Loading swarm levels…</div></div>
      <div class="disc" id="lvlDisc"></div>
    </section>
    <section class="card">
      <div class="ch"><h2>Venue map</h2><span class="badge" id="venBadge">—</span></div>
      <div class="body" id="venue"><div class="empty">Loading venue weights…</div></div>
    </section>
    <section class="card">
      <div class="ch"><h2>Paper account</h2><span class="badge" id="simBadge">—</span></div>
      <div class="body" id="sim"><div class="empty">Loading…</div></div>
    </section>
    <section class="card">
      <div class="ch"><h2>Leaderboard</h2><span class="badge" id="lbBadge">—</span></div>
      <div class="body" id="lb"><div class="empty">Loading…</div></div>
    </section>
  </div>

  <div class="foot">
    Same-origin proxy <code>/api/swarm-mm</code> · upstream <a href="__UPSTREAM__" target="_blank" rel="noopener">swarm-mm</a>
    · direct fallback <a href="__UPSTREAM__/panel" target="_blank" rel="noopener">/panel</a>
    · educational signals only · not a broker-dealer
  </div>

<script>
const API = '/api/swarm-mm';
function money(n){
  if(n==null||n==='') return '—';
  const x=Number(n); if(Number.isNaN(x)) return String(n);
  return x.toLocaleString(undefined,{style:'currency',currency:'USD',maximumFractionDigits:2});
}
function num(n,d=2){
  if(n==null||n==='') return '—';
  const x=Number(n); if(Number.isNaN(x)) return String(n);
  return x.toLocaleString(undefined,{maximumFractionDigits:d});
}
function pct(n){
  if(n==null||n==='') return '—';
  const x=Number(n); if(Number.isNaN(x)) return String(n);
  return (x<=1?x*100:x).toFixed(1)+'%';
}
function setBadge(id, status, label){
  const el=document.getElementById(id);
  el.className='badge '+(status>=400?'err':status===0?'warn':'ok');
  el.textContent=label||('HTTP '+status);
}
async function jget(path){
  const r=await fetch(API+path,{headers:{'Accept':'application/json'}});
  const t=await r.text(); let b; try{b=JSON.parse(t)}catch(e){b={raw:t}}
  return {status:r.status, body:b};
}
async function jpost(path, body){
  const r=await fetch(API+path,{method:'POST',headers:{'Content-Type':'application/json','Accept':'application/json'},body:JSON.stringify(body||{})});
  const t=await r.text(); let b; try{b=JSON.parse(t)}catch(e){b={raw:t}}
  return {status:r.status, body:b};
}
function renderLevels(status, body){
  setBadge('lvlBadge', status);
  const root=document.getElementById('levels');
  const disc=document.getElementById('lvlDisc');
  disc.textContent = body && body.disclaimer ? body.disclaimer : '';
  if(status>=400){
    root.innerHTML='<div class="errtxt">'+(body.detail||body.error||'Unavailable')+'</div>';
    return;
  }
  const levels = body.levels || body.signal_levels || [];
  if(!levels.length){
    root.innerHTML='<div class="empty">No levels for this ticker/side right now.</div>';
    return;
  }
  let rows='';
  levels.slice(0,8).forEach(L=>{
    const side=(L.side||'').toLowerCase();
    rows += '<tr>'
      +'<td><span class="side-'+(side==='sell'?'sell':'buy')+'">'+(side||'—')+'</span></td>'
      +'<td class="px">'+num(L.price,4)+'</td>'
      +'<td>'+num(L.size,2)+'</td>'
      +'<td class="purp">'+(L.venue_hint||L.venue||'—')+'</td>'
      +'<td class="mut">'+num((L.confidence!=null?L.confidence*100:null),1)+(L.confidence!=null?'%':'')+'</td>'
      +'<td class="mut">'+num(L.expected_rebate_bps,2)+' bps</td>'
      +'</tr>';
  });
  root.innerHTML='<table><thead><tr><th>Side</th><th>Price</th><th>Size</th><th>Venue</th><th>Conf</th><th>Rebate</th></tr></thead><tbody>'+rows+'</tbody></table>';
}
function renderVenue(status, body){
  setBadge('venBadge', status);
  const root=document.getElementById('venue');
  if(status>=400){
    root.innerHTML='<div class="errtxt">'+(body.detail||body.error||'Unavailable')+'</div>';
    return;
  }
  const alloc=body.allocations||body.venues||[];
  if(!alloc.length){
    root.innerHTML='<div class="empty">No venue map available.</div>';
    return;
  }
  let html='<div class="barwrap">';
  alloc.forEach(a=>{
    const w=Number(a.weight||0);
    const pctv=(w<=1?w*100:w);
    html += '<div class="vrow">'
      +'<div class="vname">'+(a.venue||'—')+'</div>'
      +'<div class="track"><div class="fill" style="width:'+Math.max(2,Math.min(100,pctv))+'%"></div></div>'
      +'<div class="pct">'+pctv.toFixed(1)+'%</div>'
      +'</div>'
      +'<div class="mut" style="font-size:11px;margin:-2px 0 4px 72px">'+(a.reason||'')+'</div>';
  });
  html+='</div>';
  root.innerHTML=html;
}
function renderSim(status, body){
  setBadge('simBadge', status);
  const root=document.getElementById('sim');
  if(status===404 || (body && (body.detail||'').toLowerCase().includes('not found'))){
    root.innerHTML='<div class="empty">No paper account yet. Click <b>Join paper $100k</b> to start free sim (track record, no real capital).</div>';
    setBadge('simBadge', 0, 'JOIN');
    return;
  }
  if(status>=400){
    root.innerHTML='<div class="errtxt">'+(body.detail||body.error||'Unavailable')+'</div>';
    return;
  }
  const a=body.account||body;
  root.innerHTML='<div class="statgrid">'
    +'<div class="stat"><div class="k">User</div><div class="v" style="font-size:13px">'+(a.user_id||'—')+'</div></div>'
    +'<div class="stat"><div class="k">Equity</div><div class="v go">'+money(a.equity!=null?a.equity:a.cash)+'</div></div>'
    +'<div class="stat"><div class="k">Cash</div><div class="v">'+money(a.cash)+'</div></div>'
    +'<div class="stat"><div class="k">Starting</div><div class="v">'+money(a.starting_balance)+'</div></div>'
    +'<div class="stat"><div class="k">Realized P&amp;L</div><div class="v">'+(Number(a.realized_pnl||0)>=0?'<span class="go">':'<span class="bad">')+money(a.realized_pnl||0)+'</span></div></div>'
    +'<div class="stat"><div class="k">Open / Fills</div><div class="v">'+num(a.open_orders,0)+' / '+num(a.fills,0)+'</div></div>'
    +'</div>';
}
function renderLb(status, body){
  setBadge('lbBadge', status);
  const root=document.getElementById('lb');
  if(status>=400){
    root.innerHTML='<div class="errtxt">'+(body.detail||body.error||'Unavailable')+'</div>';
    return;
  }
  const entries=body.entries||[];
  if(!entries.length){
    root.innerHTML='<div class="empty">Paper leaderboard empty — join and place sim limits to build track record. <span class="mut">Educational only.</span></div>';
    return;
  }
  let html='';
  entries.slice(0,8).forEach((e,i)=>{
    html += '<div class="lb-row"><span><span class="rank">#'+(e.rank||i+1)+'</span> '+(e.user_id||e.name||'trader')+'</span>'
      +'<span class="go">'+money(e.equity!=null?e.equity:e.pnl)+'</span></div>';
  });
  root.innerHTML=html;
}
async function ensureJoined(uid){
  const a=await jget('/sim/account/'+encodeURIComponent(uid));
  if(a.status===200 && !(a.body && (a.body.detail||'').toString().toLowerCase().includes('not found'))){
    return a;
  }
  // auto-join free paper so desk never shows dead 404 on first paint
  await jpost('/sim/join',{user_id:uid, starting_balance:100000});
  return jget('/sim/account/'+encodeURIComponent(uid));
}
async function loadAll(){
  const btn=document.getElementById('btnRefresh');
  btn.disabled=true;
  document.getElementById('feedPill').textContent='REFRESH…';
  try{
    const t=(document.getElementById('ticker').value||'IWM').trim().toUpperCase();
    const side=document.getElementById('side').value;
    const uid=(document.getElementById('uid').value||'timothy_walton').trim();
    const [L,V,LB,A] = await Promise.all([
      jget('/levels?ticker='+encodeURIComponent(t)+'&side='+side),
      jget('/venue-map?ticker='+encodeURIComponent(t)),
      jget('/sim/leaderboard?timeframe=all_time'),
      ensureJoined(uid),
    ]);
    renderLevels(L.status, L.body||{});
    renderVenue(V.status, V.body||{});
    renderLb(LB.status, LB.body||{});
    renderSim(A.status, A.body||{});
    document.getElementById('feedPill').textContent='HTTP OK';
    document.getElementById('feedPill').className='pill live';
  }catch(e){
    document.getElementById('feedPill').textContent='ERROR';
    document.getElementById('feedPill').className='pill';
  }finally{
    btn.disabled=false;
  }
}
async function joinSim(){
  const uid=(document.getElementById('uid').value||'timothy_walton').trim();
  document.getElementById('btnJoin').disabled=true;
  try{
    const r=await jpost('/sim/join',{user_id:uid, starting_balance:100000});
    renderSim(r.status, r.body||{});
    await loadAll();
  }finally{
    document.getElementById('btnJoin').disabled=false;
  }
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
