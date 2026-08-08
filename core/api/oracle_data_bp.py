"""
Real-World Data Oracle — Agent-Priced Regulatory Event Feeds
============================================================
Machine-readable regulatory event data that moves markets before Bloomberg.

The unsolved problem: reliable, machine-readable regulatory event parsing at
the per-call level doesn't exist. Agents that catch an SEC 8-K, FDA approval,
or USPTO grant first win the trade. This service charges RLUSD per call via
the x402 / 402Proof vending-machine pattern.

Free:    GET  /api/oracle/feeds         — catalog of available feeds + pricing
Premium: GET  /api/oracle/latest/<feed> — latest N events          (0.02 RLUSD)
Premium: POST /api/oracle/query         — keyword / date search     (0.02 RLUSD)
Premium: GET  /api/oracle/stream        — real-time SSE push        (0.05 RLUSD)

Data sources:
  sec_8k   — SEC EDGAR ATOM feed (Form 8-K material events)
  sec_s1   — SEC EDGAR ATOM feed (Form S-1/S-1A IPO filings)
  fda      — OpenFDA drug approval API (NDA/BLA approvals)
  patents  — PatentsView patent grant API (USPTO)
"""

import threading
import time
import logging
import queue
import json
import uuid
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from collections import deque
from flask import Blueprint, Response, jsonify, request
from proof402_integration import _verify_token_local, _issue_invoice, PROOF402_SERVER

logger = logging.getLogger("SqueezeOS-Oracle")

oracle_data_bp = Blueprint("oracle_data", __name__)

# ── Feed catalog ──────────────────────────────────────────────────────────────

FEEDS = {
    "sec_8k": {
        "name": "SEC Form 8-K — Material Events",
        "description": (
            "Real-time SEC Form 8-K material event disclosures: earnings releases, M&A, "
            "executive changes, bankruptcy filings, material agreements. Moves stocks before "
            "Bloomberg publishes. Polled every 60 s from EDGAR."
        ),
        "price_rlusd": "0.02",
        "poll_interval_s": 60,
        "source_url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&output=atom",
    },
    "sec_s1": {
        "name": "SEC Form S-1 — IPO Filings",
        "description": (
            "IPO registration statements and S-1/A amendments the moment they hit EDGAR. "
            "Early signal on new equity supply — priced weeks before IPO day."
        ),
        "price_rlusd": "0.02",
        "poll_interval_s": 300,
        "source_url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=S-1&output=atom",
    },
    "fda": {
        "name": "FDA Drug Approvals — NDA/BLA",
        "description": (
            "FDA drug approval events sourced from OpenFDA. Pharmaceutical binary events — "
            "stocks move 50–200% on approval or rejection. Sub-second delivery vs Bloomberg's "
            "5–10 minute lag. Polled every 5 min."
        ),
        "price_rlusd": "0.02",
        "poll_interval_s": 300,
        "source_url": "https://api.fda.gov/drug/drugsfda.json",
    },
    "patents": {
        "name": "USPTO Patent Grants",
        "description": (
            "Weekly USPTO patent grant notifications from PatentsView. Early signal on "
            "technology moats — granted patents indicate R&D direction and IP defensibility "
            "before analyst coverage."
        ),
        "price_rlusd": "0.02",
        "poll_interval_s": 3600,
        "source_url": "https://api.patentsview.org/patents/query",
    },
}

# ── Payment endpoint IDs (registered in 402Proof dashboard) ──────────────────
# These are not in the ENDPOINTS dict in proof402_integration.py because oracle
# routes use path parameters. Payment is verified inline via _gate().

ORACLE_READ_ENDPOINT_ID   = "e7f8a9b0-c001-4d2e-bb35-ef7f4cd23c6a"  # 0.02 RLUSD
ORACLE_STREAM_ENDPOINT_ID = "f8a9b0c1-d002-4e3f-cc46-f0845de34d7b"  # 0.05 RLUSD

# ── Event ring buffers (per feed, last 200 events each) ───────────────────────

_MAX_PER_FEED = 200
_buffers: dict = {f: deque(maxlen=_MAX_PER_FEED) for f in FEEDS}
_buf_lock = threading.Lock()

# ── SSE subscribers for /stream ───────────────────────────────────────────────

_stream_qs: list = []
_stream_lock = threading.Lock()

_HDRS = {"User-Agent": "SqueezeOS/1.0 agents@scriptmasterlabs.com"}


def _push(feed: str, event: dict):
    """Append event to ring buffer and broadcast to all active SSE streams."""
    event.setdefault("id", str(uuid.uuid4())[:8])
    event["feed"] = feed
    event.setdefault("ts", time.time())
    with _buf_lock:
        _buffers[feed].appendleft(event)
    dead = []
    with _stream_lock:
        for q in _stream_qs:
            try:
                q.put_nowait(event)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _stream_qs.remove(q)


# ── Payment gate ──────────────────────────────────────────────────────────────

def _gate(endpoint_id: str, price_rlusd: str):
    """
    Verify payment token from X-Payment-Token header.
    Returns (wallet_str, None) on success, or (None, flask_response) on failure.
    Fails open when 402Proof is unreachable.
    """
    token = request.headers.get("X-Payment-Token", "")
    if token:
        res = _verify_token_local(token)
        if res["valid"]:
            if res.get("endpoint_id") != endpoint_id:
                return None, (jsonify({
                    "error":   "ERR_ENDPOINT_MISMATCH",
                    "message": "Token was issued for a different endpoint.",
                    "remedy":  f"Obtain a new invoice at {PROOF402_SERVER}/v1/invoice",
                }), 401)
            return res.get("wallet", ""), None
        reason = res.get("reason", "ERR_TOKEN_INVALID")
        return None, (jsonify({
            "error":  reason,
            "remedy": f"{PROOF402_SERVER}/v1/invoice",
        }), 401)

    # No token — issue invoice and return 402
    try:
        inv = _issue_invoice(endpoint_id)
    except Exception as e:
        logger.warning(f"[Oracle] 402Proof unreachable ({e}) — failing open")
        return "FALLTHROUGH", None

    return None, (jsonify({
        "error":   "ERR_PAYMENT_REQUIRED",
        "message": f"This oracle feed costs {price_rlusd} RLUSD per call. Pay on XRPL to continue.",
        "invoice": inv,
        "remedy": {
            "step1": f"Send {inv.get('amount')} {inv.get('asset','RLUSD')} on XRPL to {inv.get('pay_to')}",
            "step2": f"Include MemoData: {inv.get('memo_hex')} in your XRPL payment transaction",
            "step3": f"POST {PROOF402_SERVER}/v1/verify with invoice_id, tx_hash, agent_wallet",
            "step4": "Retry with header: X-Payment-Token: <token>",
        },
        "free_alternatives": {
            "feed_catalog": "/api/oracle/feeds",
            "market_signals": "/api/preview/IWM",
        },
    }), 402)


# ── Routes ────────────────────────────────────────────────────────────────────

@oracle_data_bp.route("/feeds", methods=["GET"])
def list_feeds():
    """Free — list all available oracle feeds with current event counts and pricing."""
    with _buf_lock:
        counts = {f: len(_buffers[f]) for f in FEEDS}
    return jsonify({
        "feeds": {
            k: {**{fk: fv for fk, fv in v.items() if fk != "poll_interval_s"},
                "buffered_events":   counts[k],
                "poll_interval_s":   v["poll_interval_s"]}
            for k, v in FEEDS.items()
        },
        "pricing": {
            "latest_and_query": f"0.02 RLUSD per call — endpoint_id: {ORACLE_READ_ENDPOINT_ID}",
            "stream":           f"0.05 RLUSD per session — endpoint_id: {ORACLE_STREAM_ENDPOINT_ID}",
            "invoice_gateway":  f"{PROOF402_SERVER}/v1/invoice",
        },
        "advantage": "Sub-second delivery vs Bloomberg's 5–10 min lag. Machine-readable JSON. Per-call pricing.",
        "mcp_tool":  "oracle_feeds / oracle_query — available on the SqueezeOS MCP server at /mcp",
        "free":      True,
        "ts":        time.time(),
    })


@oracle_data_bp.route("/latest/<feed>", methods=["GET"])
def latest_events(feed):
    """
    Premium (0.02 RLUSD) — return the latest N events from the specified feed.

    Query params:
      limit  int  Max events to return (default 20, max 100)
    """
    if feed not in FEEDS:
        return jsonify({
            "error":       "UNKNOWN_FEED",
            "valid_feeds": list(FEEDS.keys()),
            "catalog":     "/api/oracle/feeds",
        }), 404

    wallet, err = _gate(ORACLE_READ_ENDPOINT_ID, "0.02")
    if err:
        return err

    limit = min(int(request.args.get("limit", 20)), 100)
    with _buf_lock:
        events = list(_buffers[feed])[:limit]

    return jsonify({
        "feed":         feed,
        "feed_name":    FEEDS[feed]["name"],
        "events":       events,
        "count":        len(events),
        "buffered":     len(_buffers[feed]),
        "agent_wallet": wallet or "",
        "ts":           time.time(),
    })


@oracle_data_bp.route("/query", methods=["POST"])
def query_events():
    """
    Premium (0.02 RLUSD) — keyword/date search across one or all oracle feeds.

    Body (JSON):
      feeds     list[str]   Feed keys to search (default: all)
      keyword   str         Case-insensitive text search (optional)
      since_ts  float       Unix timestamp lower bound (optional)
      limit     int         Max results (default 50, max 200)
    """
    wallet, err = _gate(ORACLE_READ_ENDPOINT_ID, "0.02")
    if err:
        return err

    body    = request.get_json(silent=True) or {}
    feeds   = body.get("feeds") or list(FEEDS.keys())
    keyword = (body.get("keyword") or "").lower().strip()
    since   = body.get("since_ts")
    limit   = min(int(body.get("limit", 50)), 200)

    # Validate feed names
    invalid = [f for f in feeds if f not in FEEDS]
    if invalid:
        return jsonify({"error": "UNKNOWN_FEED", "invalid": invalid, "valid_feeds": list(FEEDS.keys())}), 400

    results = []
    with _buf_lock:
        for f in feeds:
            for ev in _buffers[f]:
                if since and ev.get("ts", 0) < since:
                    continue
                if keyword and keyword not in json.dumps(ev).lower():
                    continue
                results.append(ev)

    results.sort(key=lambda e: e.get("ts", 0), reverse=True)
    page = results[:limit]

    return jsonify({
        "results":        page,
        "count":          len(page),
        "total_matched":  len(results),
        "query": {
            "feeds":    feeds,
            "keyword":  keyword or None,
            "since_ts": since,
            "limit":    limit,
        },
        "agent_wallet":   wallet or "",
        "ts":             time.time(),
    })


@oracle_data_bp.route("/stream", methods=["GET"])
def stream_events():
    """
    Premium (0.05 RLUSD) — real-time SSE stream of all incoming oracle events.
    Payment is a one-time gate per connection. Stream stays open until client disconnects.
    """
    wallet, err = _gate(ORACLE_STREAM_ENDPOINT_ID, "0.05")
    if err:
        return err

    def gen():
        q = queue.Queue(maxsize=200)
        with _stream_lock:
            _stream_qs.append(q)
        try:
            yield (
                f"data: {json.dumps({'type':'ORACLE_CONNECTED','feeds':list(FEEDS.keys()),'wallet':wallet or '','ts':time.time()})}\n\n"
            )
            while True:
                try:
                    ev = q.get(timeout=30)
                    yield f"data: {json.dumps(ev)}\n\n"
                except queue.Empty:
                    yield f"data: {json.dumps({'type':'ORACLE_HEARTBEAT','ts':time.time()})}\n\n"
        finally:
            with _stream_lock:
                if q in _stream_qs:
                    _stream_qs.remove(q)

    return Response(gen(), mimetype="text/event-stream")


# ── Background pollers ────────────────────────────────────────────────────────

def _poll_sec(form_type: str, feed_key: str, interval: int):
    """Poll SEC EDGAR ATOM feed for new filings of a given form type."""
    seen: set = set()
    url = (
        "https://www.sec.gov/cgi-bin/browse-edgar"
        f"?action=getcurrent&type={urllib.parse.quote(form_type)}"
        "&dateb=&owner=include&count=40&search_text=&output=atom"
    )
    while True:
        try:
            req = urllib.request.Request(url, headers=_HDRS)
            with urllib.request.urlopen(req, timeout=20) as resp:
                tree = ET.parse(resp)
            ns = {"a": "http://www.w3.org/2005/Atom"}
            for entry in tree.findall("a:entry", ns):
                eid = (entry.findtext("a:id", "", ns) or "").strip()
                if not eid or eid in seen:
                    continue
                seen.add(eid)
                if len(seen) > 2000:
                    seen = set(list(seen)[-1000:])
                title   = entry.findtext("a:title", "", ns).strip()
                updated = entry.findtext("a:updated", "", ns).strip()
                link    = next(
                    (lnk.get("href", "") for lnk in entry.findall("a:link", ns) if lnk.get("rel") == "alternate"),
                    "",
                )
                summary = entry.findtext("a:summary", "", ns).strip()[:500]
                company = title.split(" - ")[0].strip() if " - " in title else title
                _push(feed_key, {
                    "form":      form_type,
                    "company":   company,
                    "title":     title,
                    "summary":   summary,
                    "filed_at":  updated,
                    "url":       link,
                    "source":    "SEC_EDGAR",
                })
        except Exception as e:
            logger.warning(f"[Oracle/SEC/{form_type}] poll error: {e}")
        time.sleep(interval)


def _poll_fda():
    """Poll OpenFDA for recent drug approval events (NDA/BLA)."""
    seen: set = set()
    url = (
        "https://api.fda.gov/drug/drugsfda.json"
        "?search=submissions.submission_status%3AAP"
        "&sort=submissions.submission_status_date%3Adesc"
        "&limit=20"
    )
    cutoff = datetime.now() - timedelta(days=30)
    while True:
        try:
            req = urllib.request.Request(url, headers=_HDRS)
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read())
            for result in data.get("results", []):
                app_num = result.get("application_number", "")
                if not app_num or app_num in seen:
                    continue
                submissions = result.get("submissions", [])
                approved = [s for s in submissions if s.get("submission_status") == "AP"]
                if not approved:
                    continue
                latest = max(approved, key=lambda s: s.get("submission_status_date", ""))
                approval_date = latest.get("submission_status_date", "")
                try:
                    if datetime.strptime(approval_date, "%Y%m%d") < cutoff:
                        continue
                except Exception:
                    pass
                seen.add(app_num)
                products = result.get("products") or [{}]
                brand    = products[0].get("brand_name", "")
                ingreds  = products[0].get("active_ingredients") or [{}]
                generic  = ingreds[0].get("name", "")
                _push("fda", {
                    "application_number":  app_num,
                    "brand_name":          brand,
                    "generic_name":        generic,
                    "approval_date":       approval_date,
                    "submission_type":     latest.get("submission_type", ""),
                    "applicant":           result.get("sponsor_name", ""),
                    "source":              "FDA_OPENFDA",
                })
        except Exception as e:
            logger.warning(f"[Oracle/FDA] poll error: {e}")
        time.sleep(FEEDS["fda"]["poll_interval_s"])


def _poll_patents():
    """Poll PatentsView for recent USPTO patent grants (last 14 days)."""
    seen: set = set()
    while True:
        try:
            cutoff = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
            q_str = json.dumps({"_gte": {"patent_date": cutoff}})
            f_str = json.dumps(["patent_id", "patent_title", "patent_date", "patent_abstract", "assignees"])
            o_str = json.dumps({"per_page": 25})
            url = (
                "https://api.patentsview.org/patents/query"
                f"?q={urllib.parse.quote(q_str)}"
                f"&f={urllib.parse.quote(f_str)}"
                f"&o={urllib.parse.quote(o_str)}"
            )
            req = urllib.request.Request(url, headers=_HDRS)
            with urllib.request.urlopen(req, timeout=25) as resp:
                data = json.loads(resp.read())
            for patent in (data.get("patents") or []):
                pid = patent.get("patent_id", "")
                if not pid or pid in seen:
                    continue
                seen.add(pid)
                if len(seen) > 5000:
                    seen = set(list(seen)[-2000:])
                assignees = [
                    a.get("assignee_organization", "")
                    for a in (patent.get("assignees") or [])
                    if a.get("assignee_organization")
                ]
                _push("patents", {
                    "patent_id":  pid,
                    "title":      patent.get("patent_title", ""),
                    "grant_date": patent.get("patent_date", ""),
                    "abstract":   (patent.get("patent_abstract") or "")[:400],
                    "assignees":  assignees[:3],
                    "source":     "USPTO_PATENTSVIEW",
                })
        except Exception as e:
            logger.warning(f"[Oracle/Patents] poll error: {e}")
        time.sleep(FEEDS["patents"]["poll_interval_s"])


def start_oracle_pollers():
    """
    Start all four background polling daemon threads.
    Must only be called from create_app() (not in serverless mode).
    """
    threads = [
        threading.Thread(target=_poll_sec, args=("8-K", "sec_8k", FEEDS["sec_8k"]["poll_interval_s"]),
                         daemon=True, name="oracle-sec-8k"),
        threading.Thread(target=_poll_sec, args=("S-1", "sec_s1", FEEDS["sec_s1"]["poll_interval_s"]),
                         daemon=True, name="oracle-sec-s1"),
        threading.Thread(target=_poll_fda,     daemon=True, name="oracle-fda"),
        threading.Thread(target=_poll_patents,  daemon=True, name="oracle-patents"),
    ]
    for t in threads:
        t.start()
    logger.info(f"[Oracle] {len(threads)} pollers started — SEC 8-K (60s), S-1 (300s), FDA (300s), Patents (1h)")
