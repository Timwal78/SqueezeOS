import os
import hmac
import hashlib
import time
import threading
import requests
from flask import Blueprint, request, jsonify, redirect

slack_bp = Blueprint("slack", __name__)

_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET", "")
_BOT_TOKEN      = os.environ.get("SLACK_BOT_TOKEN", "")
_CLIENT_ID      = os.environ.get("SLACK_CLIENT_ID", "")
_CLIENT_SECRET  = os.environ.get("SLACK_CLIENT_SECRET", "")
_BASE           = os.environ.get("SQUEEZEOS_BASE_URL", "https://squeezeos-api.onrender.com")
_SITE           = "https://www.scriptmasterlabs.com"

_BIAS_COLOR = {
    "BULLISH": "#00CC44",
    "BEARISH": "#FF3B3B",
    "NEUTRAL": "#FFB300",
    "SHIELD":  "#7B68EE",
}
_BIAS_EMOJI = {
    "BULLISH": "🟢",
    "BEARISH": "🔴",
    "NEUTRAL": "🟡",
    "SHIELD":  "🛡️",
}
_REGIME_LABEL = {
    "ALPHA_EXPANSION": "📈 ALPHA EXPANSION — highway is open",
    "MACRO_COLLAPSE":  "📉 MACRO COLLAPSE — institutional exit in progress",
    "NEUTRAL":         "➡️  NEUTRAL — no directional edge",
    "SHIELD":          "🛡️  SHIELD — risk-off, protect capital",
}


# ─── Signature Verification ──────────────────────────────────────────────────

def _verify(req) -> bool:
    if not _SIGNING_SECRET:
        return True
    ts = req.headers.get("X-Slack-Request-Timestamp", "0")
    try:
        if abs(time.time() - int(ts)) > 300:
            return False
    except ValueError:
        return False
    body  = req.get_data(as_text=True)
    base  = f"v0:{ts}:{body}"
    expected = "v0=" + hmac.new(
        _SIGNING_SECRET.encode(), base.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, req.headers.get("X-Slack-Signature", ""))


# ─── Block Kit Helpers ────────────────────────────────────────────────────────

def _bars(pct: float, width: int = 12) -> str:
    filled = max(0, min(width, round((pct / 100) * width)))
    return "█" * filled + "░" * (width - filled)

def _footer():
    return {
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": f"⚡ SqueezeOS v6.2 · <{_SITE}|Script Master Labs> · x402 RLUSD · No API keys"
        }]
    }

def _payment_cta():
    return {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": (
                "*Unlock full institutional suite via x402 micropayment:*\n"
                "• `council_verdict` — all engines · *0.10 RLUSD*\n"
                "• `options_intelligence` — sweeps + dark pool · *0.05 RLUSD*\n"
                "• `market_scan` — full $1–$50 universe · *0.05 RLUSD*\n"
                "• `iwm_odte` — IWM 0DTE contract scorer · *0.03 RLUSD*\n\n"
                "_No API keys. No subscription. Pay per call on XRP Ledger._"
            )
        },
        "accessory": {
            "type": "button",
            "text": {"type": "plain_text", "text": "Get Access"},
            "url": _SITE,
            "style": "primary"
        }
    }

def _err(msg: str) -> dict:
    return {"response_type": "ephemeral", "text": f"❌ {msg}"}

def _ack(msg: str) -> dict:
    return {"response_type": "ephemeral", "text": msg}

def _delayed(url: str, payload: dict):
    try:
        requests.post(url, json=payload, timeout=12)
    except Exception:
        pass


# ─── /squeeze [SYMBOL] ───────────────────────────────────────────────────────

@slack_bp.route("/squeeze", methods=["POST"])
def slash_squeeze():
    if not _verify(request):
        return jsonify(_err("Invalid request signature")), 403

    symbol       = (request.form.get("text", "").strip().upper() or "IWM")
    response_url = request.form.get("response_url", "")
    channel      = request.form.get("channel_id", "")
    user         = request.form.get("user_name", "")

    threading.Thread(
        target=_deliver_squeeze,
        args=(symbol, response_url, channel, user),
        daemon=True
    ).start()

    return jsonify(_ack(f"⚡ SqueezeOS analyzing *{symbol}*..."))


def _deliver_squeeze(symbol: str, response_url: str, channel: str, user: str):
    try:
        r    = requests.get(f"{_BASE}/api/preview/{symbol}", timeout=20)
        data = r.json()
    except Exception as exc:
        _delayed(response_url, _err(f"SqueezeOS engine unavailable: {exc}"))
        return

    bias       = data.get("bias", "UNKNOWN")
    regime     = data.get("regime", "UNKNOWN")
    confidence = float(data.get("confidence", 0))
    signal     = data.get("signal", "—")
    directive  = data.get("directive", "Awaiting data")
    triple_lock = data.get("triple_lock", False)
    squeeze    = data.get("squeeze_detected", False)

    color      = _BIAS_COLOR.get(bias, "#888888")
    emoji      = _BIAS_EMOJI.get(bias, "⚪")
    r_label    = _REGIME_LABEL.get(regime, regime)
    bars       = _bars(confidence)

    tl_line = ""
    if triple_lock:
        tl_line = "\n⚡ *TRIPLE LOCK* — all 3 engines aligned · max conviction signal"
    elif squeeze:
        tl_line = "\n🔥 *SQUEEZE DETECTED* — compression building"

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"⚡ SqueezeOS Signal — {symbol}"}
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*BIAS*\n{emoji} {bias}"},
                {"type": "mrkdwn", "text": f"*SIGNAL*\n{signal}"}
            ]
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*CONFIDENCE*\n`{bars}` {confidence:.0f}%"},
                {"type": "mrkdwn", "text": f"*REGIME*\n{r_label}"}
            ]
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Directive:* {directive}{tl_line}"
            }
        },
        {"type": "divider"},
        _payment_cta(),
        _footer()
    ]

    _delayed(response_url, {
        "response_type": "in_channel",
        "text": f"SqueezeOS — {symbol}: {bias} ({confidence:.0f}%)",
        "attachments": [{"color": color, "blocks": blocks}]
    })


# ─── /scan ───────────────────────────────────────────────────────────────────

@slack_bp.route("/scan", methods=["POST"])
def slash_scan():
    if not _verify(request):
        return jsonify(_err("Invalid request signature")), 403

    response_url = request.form.get("response_url", "")
    threading.Thread(target=_deliver_scan, args=(response_url,), daemon=True).start()

    return jsonify(_ack("🔍 Running SqueezeOS scanner..."))


def _deliver_scan(response_url: str):
    candidates = []

    # Pull recent signals from history ring buffer
    try:
        r = requests.get(f"{_BASE}/api/history", timeout=15)
        records = r.json() if r.status_code == 200 else []
        if isinstance(records, list):
            seen = set()
            for rec in records:
                sym = rec.get("symbol", "")
                if sym and sym not in seen:
                    seen.add(sym)
                    candidates.append({
                        "symbol":     sym,
                        "bias":       rec.get("data", {}).get("bias", "NEUTRAL"),
                        "confidence": rec.get("data", {}).get("confidence", 0),
                        "signal":     rec.get("data", {}).get("signal", "—"),
                    })
                if len(candidates) >= 8:
                    break
    except Exception:
        pass

    # Fall back to demo if history empty
    if not candidates:
        try:
            r   = requests.get(f"{_BASE}/api/demo/council", timeout=15)
            d   = r.json()
            candidates = [{
                "symbol":     "IWM",
                "bias":       d.get("bias", "NEUTRAL"),
                "confidence": d.get("confidence", 0),
                "signal":     d.get("signal", "—"),
            }]
        except Exception:
            _delayed(response_url, _err("Scanner unavailable — try again shortly"))
            return

    top = sorted(candidates, key=lambda x: x["confidence"], reverse=True)[:5]

    rows = []
    for c in top:
        emoji = _BIAS_EMOJI.get(c["bias"], "⚪")
        conf  = c["confidence"]
        rows.append(
            f"{emoji} *{c['symbol']}* — {c['bias']} · {conf:.0f}% · {c['signal']}"
        )

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "🔍 SqueezeOS Scanner — Top Setups"}},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(rows) or "No setups in recent history"}
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "_These are the highest-confidence signals from the recent ring buffer.\n"
                    "Run `/squeeze [TICKER]` for full bias + regime on any symbol.\n"
                    "Full $1–$50 universe scanner (250 symbols) available via x402 · 0.05 RLUSD._"
                )
            }
        },
        _footer()
    ]

    _delayed(response_url, {
        "response_type": "in_channel",
        "text": "SqueezeOS Scanner — top setups",
        "attachments": [{"color": "#1A1A44", "blocks": blocks}]
    })


# ─── /preview [SYMBOL] ───────────────────────────────────────────────────────

@slack_bp.route("/preview", methods=["POST"])
def slash_preview():
    if not _verify(request):
        return jsonify(_err("Invalid request signature")), 403

    symbol       = (request.form.get("text", "").strip().upper() or "IWM")
    response_url = request.form.get("response_url", "")

    threading.Thread(
        target=_deliver_squeeze,
        args=(symbol, response_url, "", ""),
        daemon=True
    ).start()

    return jsonify(_ack(f"📊 Fetching preview for *{symbol}*..."))


# ─── /ftd [GME|AMC] ──────────────────────────────────────────────────────────

@slack_bp.route("/ftd", methods=["POST"])
def slash_ftd():
    if not _verify(request):
        return jsonify(_err("Invalid request signature")), 403

    symbol       = (request.form.get("text", "").strip().upper() or "GME")
    response_url = request.form.get("response_url", "")

    if symbol not in ("GME", "AMC"):
        return jsonify({
            "response_type": "ephemeral",
            "text": "⚠️ FTD Oracle covers *GME* and *AMC*. Usage: `/ftd GME` or `/ftd AMC`"
        })

    threading.Thread(target=_deliver_ftd, args=(symbol, response_url), daemon=True).start()
    return jsonify(_ack(f"📋 Fetching SEC FTD data for *{symbol}*..."))


def _deliver_ftd(symbol: str, response_url: str):
    try:
        r    = requests.get(f"{_BASE}/api/ftd", timeout=15)
        data = r.json()
    except Exception:
        _delayed(response_url, _err("FTD Oracle unavailable"))
        return

    # Handle both dict-of-symbols and list response formats
    entry = {}
    if isinstance(data, dict):
        entry = data.get(symbol, data.get("data", {}).get(symbol, {}))
    elif isinstance(data, list):
        for item in data:
            if item.get("symbol") == symbol:
                entry = item
                break

    if not entry:
        _delayed(response_url, _err(f"No FTD data found for {symbol}"))
        return

    ftd_count    = entry.get("ftd_count", entry.get("count", "—"))
    threshold    = entry.get("threshold_list", entry.get("on_threshold", False))
    cycle_day    = entry.get("cycle_day", entry.get("t_day", "—"))
    close_out    = entry.get("close_out_required", False)
    risk_score   = entry.get("risk_score", entry.get("score", "—"))

    t_label = "✅ *YES* — SEC Reg SHO Threshold List" if threshold else "No"
    co_label = "⚠️ *YES* — T+35 close-out required" if close_out else "No"

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"📋 FTD Oracle — {symbol}"}},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*FTD Count*\n{ftd_count}"},
                {"type": "mrkdwn", "text": f"*Settlement Cycle Day*\n{cycle_day}"},
                {"type": "mrkdwn", "text": f"*SEC Threshold List*\n{t_label}"},
                {"type": "mrkdwn", "text": f"*T+35 Close-Out*\n{co_label}"}
            ]
        },
    ]

    if risk_score and risk_score != "—":
        bars = _bars(float(risk_score)) if isinstance(risk_score, (int, float)) else "—"
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Risk Score:* `{bars}` {risk_score}"
            }
        })

    blocks += [
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"_Source: SEC Reg SHO · SqueezeOS FTD Oracle_\n"
                    f"Full cycle bundle (T+21/T+35 markers, spike stats, ETF basket): "
                    f"`/api/ftd/cycle/{symbol}` · *0.05 RLUSD*"
                )
            }
        },
        _footer()
    ]

    color = "#FF3B3B" if threshold else "#FFB300"
    _delayed(response_url, {
        "response_type": "in_channel",
        "text": f"FTD Oracle — {symbol}",
        "attachments": [{"color": color, "blocks": blocks}]
    })


# ─── /sqstatus ───────────────────────────────────────────────────────────────

@slack_bp.route("/status", methods=["POST"])
def slash_status():
    if not _verify(request):
        return jsonify(_err("Invalid request signature")), 403

    try:
        r    = requests.get(f"{_BASE}/api/status", timeout=10)
        data = r.json()
    except Exception:
        return jsonify({"response_type": "ephemeral", "text": "⚠️ Could not reach SqueezeOS engine"})

    engines  = data.get("engines_loaded", data.get("services", {}).get("loaded", 0))
    workers  = data.get("active_workers", data.get("workers", 0))
    uptime_s = data.get("uptime_seconds", data.get("uptime", 0))
    version  = data.get("version", "—")
    tools    = data.get("mcp_tools", 47)

    if isinstance(uptime_s, (int, float)) and uptime_s > 0:
        h = int(uptime_s // 3600)
        m = int((uptime_s % 3600) // 60)
        uptime_label = f"{h}h {m}m"
    else:
        uptime_label = str(uptime_s) if uptime_s else "—"

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "🔧 SqueezeOS Engine Status"}},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": "*Status*\n🟢 ONLINE"},
                {"type": "mrkdwn", "text": f"*Version*\n{version}"},
                {"type": "mrkdwn", "text": f"*Uptime*\n{uptime_label}"},
                {"type": "mrkdwn", "text": f"*Engines*\n{engines} loaded"},
                {"type": "mrkdwn", "text": f"*Active Workers*\n{workers}"},
                {"type": "mrkdwn", "text": f"*MCP Tools*\n{tools} tools"}
            ]
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Subsystems:* Squeeze Scanner · Oracle Engine · Battle Computer · "
                    f"Options Intelligence · IWM 0DTE · 741 Macro Stack · Avg-Down Engine · "
                    f"FTD Oracle · Signal Futures · Stigmergy Protocol · Decision Notary"
                )
            }
        },
        _footer()
    ]

    return jsonify({
        "response_type": "in_channel",
        "attachments": [{"color": "#00CC44", "blocks": blocks}]
    })


# ─── OAuth 2.0 ───────────────────────────────────────────────────────────────

@slack_bp.route("/install", methods=["GET"])
def slack_install():
    if not _CLIENT_ID:
        return "SLACK_CLIENT_ID not configured", 503
    scopes = (
        "chat:write,chat:write.public,commands,incoming-webhook,"
        "channels:read,app_mentions:read,im:history,im:read,im:write"
    )
    redirect_uri = f"{_BASE}/api/slack/oauth/callback"
    url = (
        f"https://slack.com/oauth/v2/authorize"
        f"?client_id={_CLIENT_ID}"
        f"&scope={scopes}"
        f"&redirect_uri={redirect_uri}"
    )
    return redirect(url)


@slack_bp.route("/oauth/callback", methods=["GET"])
def oauth_callback():
    code  = request.args.get("code", "")
    error = request.args.get("error", "")

    if error:
        return redirect(f"{_SITE}?slack=error&reason={error}")
    if not code:
        return "Missing authorization code", 400
    if not _CLIENT_ID or not _CLIENT_SECRET:
        return "OAuth not configured", 503

    try:
        r    = requests.post("https://slack.com/api/oauth.v2.access", data={
            "client_id":     _CLIENT_ID,
            "client_secret": _CLIENT_SECRET,
            "code":          code,
            "redirect_uri":  f"{_BASE}/api/slack/oauth/callback"
        }, timeout=15)
        data = r.json()
    except Exception as exc:
        return f"OAuth request failed: {exc}", 500

    if not data.get("ok"):
        return f"OAuth error: {data.get('error', 'unknown')}", 400

    # TODO: persist (team_id, access_token) to database for multi-workspace support
    # data["team"]["id"], data["access_token"]

    return redirect(f"{_SITE}?slack=connected")


# ─── Events API ──────────────────────────────────────────────────────────────

@slack_bp.route("/events", methods=["POST"])
def slack_events():
    if not _verify(request):
        return "", 403

    body = request.get_json(silent=True) or {}

    # Slack URL verification handshake
    if body.get("type") == "url_verification":
        return jsonify({"challenge": body["challenge"]})

    event = body.get("event", {})
    etype = event.get("type", "")

    if etype == "app_mention":
        threading.Thread(
            target=_handle_mention,
            args=(event.get("channel", ""), event.get("ts", "")),
            daemon=True
        ).start()

    elif etype == "message" and event.get("channel_type") == "im":
        text = event.get("text", "").strip().upper()
        ch   = event.get("channel", "")
        if text and ch:
            threading.Thread(
                target=_handle_dm,
                args=(ch, text),
                daemon=True
            ).start()

    return "", 200


def _post_to_channel(channel: str, blocks: list, text: str = ""):
    if not _BOT_TOKEN:
        return
    try:
        requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {_BOT_TOKEN}", "Content-Type": "application/json"},
            json={"channel": channel, "text": text, "blocks": blocks},
            timeout=10
        )
    except Exception:
        pass


def _handle_mention(channel: str, _ts: str):
    _post_to_channel(channel, [
        {"type": "header", "text": {"type": "plain_text", "text": "⚡ SqueezeOS — Slash Commands"}},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*/squeeze [TICKER]* — AI signal for any symbol (bias, regime, confidence, directive)\n"
                    "*/scan* — Top squeeze candidates from the live signal ring buffer\n"
                    "*/preview [TICKER]* — Free bias + regime preview for any symbol\n"
                    "*/ftd [GME|AMC]* — SEC Fails-To-Deliver data + Threshold List status\n"
                    "*/sqstatus* — Full engine health check (all subsystems)\n\n"
                    "*Premium tools via x402 micropayment (RLUSD on XRP Ledger):*\n"
                    "• Full Council Verdict (all 3 engines): 0.10 RLUSD\n"
                    "• Options Intelligence (sweeps + dark pool): 0.05 RLUSD\n"
                    "• Full Universe Scanner (250 symbols): 0.05 RLUSD\n"
                    "• IWM 0DTE Scorer: 0.03 RLUSD\n\n"
                    f"<{_SITE}|Learn more at scriptmasterlabs.com>"
                )
            }
        },
        _footer()
    ], text="SqueezeOS commands")


def _handle_dm(channel: str, text: str):
    parts  = text.split()
    cmd    = parts[0] if parts else ""
    symbol = parts[1] if len(parts) > 1 else "IWM"

    if cmd in ("SQUEEZE", "SIGNAL", "CHECK"):
        # synthesize a fake response_url using bot token direct post
        _post_to_channel(channel, [], text=f"⚡ Analyzing {symbol}...")
        # fetch preview and post
        try:
            r    = requests.get(f"{_BASE}/api/preview/{symbol}", timeout=20)
            data = r.json()
            bias = data.get("bias", "UNKNOWN")
            conf = float(data.get("confidence", 0))
            sig  = data.get("signal", "—")
            directive = data.get("directive", "—")
            emoji = _BIAS_EMOJI.get(bias, "⚪")
            bars  = _bars(conf)
            _post_to_channel(channel, [
                {"type": "section", "text": {"type": "mrkdwn",
                    "text": f"*{symbol}* — {emoji} {bias}\n`{bars}` {conf:.0f}%\n*{sig}*\n{directive}"
                }},
                _footer()
            ], text=f"{symbol}: {bias}")
        except Exception:
            _post_to_channel(channel, [], text="⚠️ Engine unavailable")
    else:
        _handle_mention(channel, "")


# ─── Interactive Components ───────────────────────────────────────────────────

@slack_bp.route("/interactive", methods=["POST"])
def slack_interactive():
    if not _verify(request):
        return "", 403
    # Placeholder — button clicks, menu selections
    return "", 200
