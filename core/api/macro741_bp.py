"""
Pure Macro Matrix — Multi-Layer EMA Structural Alignment Engine
=================================================================
x402-gated premium endpoint. Cost: 0.04 RLUSD per call.

EMA periods configured via MACRO_STACK_CSV (server env only, not in source)
-- the anchor (last/slowest period in that list) determines both the
regime math and the minimum bar history required. Originally shipped with
anchor=741 (hence this module's historical filename/route -- the number was
never itself load-bearing, just the configured anchor at the time); renamed
in comments/logs 2026-07-30 after the operator shortened the anchor to 190
via MACRO_STACK_CSV, per the fixed rule "no fake/stale info" -- do not
re-hardcode a period number into any log/doc text again, since it will
drift the next time MACRO_STACK_CSV changes. The route path (/741macro),
the MCP tool name (macro_741_scan), its payment UUID/price, and the public
"741" JSON key in signal_products_bp.py's /api/signals/full response are
UNCHANGED -- those are live paid-product identifiers already in use by
real callers, and renaming them is a breaking API change requiring its own
separate, explicit decision (deprecation path, registry updates), not
bundled into this internal-naming cleanup.

Secondary gate: X-Macro-Gate header validated against MACRO_GATE_SECRET.
Cache pre-warm: MACRO_STACK_WARMUP_SYMBOLS computed on startup (a
DIFFERENT env var than MACRO_STACK_WARMUP -- see the collision note below).

  PERFECT_BULLISH_REGIME  — full ascending EMA stack (fast → slow)
  PERFECT_BEARISH_REGIME  — full descending EMA stack (fast → slow)
  CONSOLIDATION_CHOP      — mixed stack

matrix_spread_pct = ((EMA_fast - EMA_anchor) / EMA_anchor) * 100

Tickers: fully dynamic via ?symbols= query param. No hardcoded lists.

Squeeze Alert: CONSOLIDATION_CHOP with low |matrix_spread_pct| (<5%) means
price is coiling against the anchor — a macro breakout is building.

Discord webhook fires automatically on every PERFECT_BULLISH or PERFECT_BEARISH hit.

ENV VAR COLLISION FIXED (2026-07-30): this module used to read the SAME
env var name, MACRO_STACK_WARMUP, as a comma-separated SYMBOL list --
except core/api/macro_bp.py (the internal regime engine that actually
gates live iam_executor.py BUY signals) reads that identical name as a
plain INTEGER bar-count buffer (`int(os.environ.get("MACRO_STACK_WARMUP",
"50"))`). The operator's real Render value, MACRO_STACK_WARMUP=50, is
CORRECT for macro_bp.py's purpose and must not be changed or cleared --
doing so would make macro_bp.py's bare int() call raise ValueError at
import time on the next deploy. This module now reads a distinct name,
MACRO_STACK_WARMUP_SYMBOLS, for its own unrelated cache-prewarm feature --
unset by default (no warmup, same as leaving it empty), set it to a real
comma-separated ticker list (e.g. "SPY,QQQ,IWM") only if warmup caching is
wanted. The stray "50" symbol-warmup failure this fixes
(`[ALPACA] Stock bars 400: invalid symbol: 50`) was this collision, not a
typo in what the operator entered.
"""

import hmac
import os
import time
import logging
import threading
from datetime import datetime
from flask import Blueprint, request, jsonify
from proof402_integration import require_payment
from core.legacy import clean_data

logger = logging.getLogger("SqueezeOS-MacroMatrix")

macro741_bp = Blueprint("macro741", __name__)


def _load_periods() -> list[int] | None:
    raw = os.environ.get("MACRO_STACK_CSV", "")
    if not raw:
        return None
    try:
        return [int(x.strip()) for x in raw.split(",") if x.strip()]
    except ValueError:
        logger.error("[MACRO] MACRO_STACK_CSV contains non-integer values — endpoint disabled")
        return None


MACRO_PERIODS: list[int] | None = _load_periods()
_GATE_SECRET: str = os.environ.get("MACRO_GATE_SECRET", "")
_WARMUP_SYMBOLS: list[str] = [
    s.strip().upper()
    for s in os.environ.get("MACRO_STACK_WARMUP_SYMBOLS", "").split(",")
    if s.strip()
]

# 60-second per-ticker cache
_cache: dict = {}
_CACHE_TTL = 60

# Calendar days needed to cover the anchor period with margin
_HISTORY_DAYS: int = int(max(MACRO_PERIODS) * 1.6) if MACRO_PERIODS else 0


def _compute_ema(closes: list[float], span: int) -> float:
    """
    Compute the last EMA value for the given close series and span.
    Uses exponential weighting: alpha = 2 / (span + 1).
    Requires at least span bars to produce a meaningful value.
    Returns None if series is too short.
    """
    if len(closes) < span:
        return None
    alpha = 2.0 / (span + 1)
    ema = sum(closes[:span]) / span  # seed: SMA of first `span` values
    for close in closes[span:]:
        ema = close * alpha + ema * (1.0 - alpha)
    return round(ema, 4)


def _fetch_closes(symbol: str) -> tuple[list[float], str]:
    """
    Fetch daily close prices in chronological order.
    Priority: Tradier → Alpaca → returns ([], source).
    Returns (closes, source_label).
    """
    # --- Tradier (preferred — brokerage-grade daily bars) ---
    try:
        from tradier_api import get_history_df
        df = get_history_df(symbol, days=_HISTORY_DAYS, interval="daily")
        if df is not None and len(df) > 10:
            closes = df["Close"].dropna().tolist()
            return closes, "tradier"
    except Exception as e:
        logger.warning("[MACRO] Tradier fetch failed for %s: %s", symbol, e)

    # --- Alpaca fallback ---
    try:
        from data_providers import AlpacaProvider
        alp = AlpacaProvider()
        if alp.available:
            bars = alp.get_historical_bars(symbol, timeframe="1Day", limit=_HISTORY_DAYS)
            if bars:
                closes = [float(b.get("c", b.get("close", 0))) for b in bars if b.get("c") or b.get("close")]
                if len(closes) > 10:
                    return closes, "alpaca"
    except Exception as e:
        logger.warning("[MACRO] Alpaca fetch failed for %s: %s", symbol, e)

    return [], "unavailable"


def _calculate_matrix_stack(symbol: str) -> dict:
    """Compute the macro matrix for one symbol."""
    closes, source = _fetch_closes(symbol)
    if not closes:
        return {
            "ticker": symbol,
            "error": "DATA_UNAVAILABLE",
            "message": "Could not fetch historical bars from Tradier or Alpaca.",
            "data_source": source,
        }

    anchor_period = MACRO_PERIODS[-1]
    if len(closes) < anchor_period:
        return {
            "ticker": symbol,
            "error": "INSUFFICIENT_HISTORY",
            "message": f"Need ≥{anchor_period} daily bars; got {len(closes)}.",
            "bars_available": len(closes),
            "data_source": source,
        }

    layers = {f"EMA_{p}": _compute_ema(closes, p) for p in MACRO_PERIODS}
    ema_vals = [layers[f"EMA_{p}"] for p in MACRO_PERIODS]

    if None in ema_vals:
        return {"ticker": symbol, "error": "EMA_COMPUTE_FAILED", "data_source": source}

    e_fast = ema_vals[0]
    e_anchor = ema_vals[-1]

    bullish_stack = all(ema_vals[i] > ema_vals[i + 1] for i in range(len(ema_vals) - 1))
    bearish_stack = all(ema_vals[i] < ema_vals[i + 1] for i in range(len(ema_vals) - 1))
    matrix_spread_pct = round(((e_fast - e_anchor) / e_anchor) * 100, 3)

    if bullish_stack:
        alignment = "PERFECT_BULLISH_REGIME"
    elif bearish_stack:
        alignment = "PERFECT_BEARISH_REGIME"
    else:
        alignment = "CONSOLIDATION_CHOP"

    squeeze_alert = (alignment == "CONSOLIDATION_CHOP") and (abs(matrix_spread_pct) < 5.0)

    return {
        "ticker": symbol,
        "current_close": round(closes[-1], 2),
        "structural_alignment": alignment,
        "matrix_spread_pct": matrix_spread_pct,
        "squeeze_alert": squeeze_alert,
        "layers": layers,
        "bars_used": len(closes),
        "data_source": source,
        "ts": datetime.utcnow().isoformat() + "Z",
    }


def _fire_discord(results: list[dict]) -> None:
    """Non-blocking Discord notification for PERFECT alignment events."""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_ALL", "")
    if not webhook_url:
        return

    perfect = [r for r in results if r.get("structural_alignment", "").startswith("PERFECT_")]
    if not perfect:
        return

    lines = ["**Pure Macro Matrix — Trend Lock Alert** 🔒"]
    for r in perfect:
        alignment = r["structural_alignment"]
        emoji = "🟢" if "BULLISH" in alignment else "🔴"
        lines.append(
            f"{emoji} **{r['ticker']}** → `{alignment}` | spread={r['matrix_spread_pct']}% | close={r['current_close']}"
        )

    payload = {"content": "\n".join(lines), "username": "SqueezeOS-MacroMatrix"}

    def _post():
        try:
            import urllib.request, json as _j
            data = _j.dumps(payload).encode()
            req = urllib.request.Request(webhook_url, data=data, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            logger.warning("[MACRO] Discord notify failed: %s", e)

    threading.Thread(target=_post, daemon=True).start()


def _run_warmup() -> None:
    """Pre-warm cache for MACRO_STACK_WARMUP_SYMBOLS symbols after a short startup delay."""
    if not _WARMUP_SYMBOLS or not MACRO_PERIODS:
        return
    time.sleep(8)
    for sym in _WARMUP_SYMBOLS:
        try:
            data = _calculate_matrix_stack(sym)
            data["_cached_at"] = time.time()
            _cache[sym] = data
            logger.info("[MACRO] Warmed %s → %s", sym, data.get("structural_alignment", "ERROR"))
        except Exception as e:
            logger.warning("[MACRO] Warmup failed for %s: %s", sym, e)


threading.Thread(target=_run_warmup, daemon=True).start()


@macro741_bp.route("/741macro", methods=["GET", "POST"])
@require_payment
def macro_741_scan():
    """
    Pure Macro Matrix scan — x402 premium endpoint (0.04 RLUSD).

    Query params / JSON body:
      symbols (str) — comma-separated list of tickers, e.g. "SPY,QQQ,NVDA,GME"
                      Required — no default list. You choose the universe.

    Returns per-ticker:
      structural_alignment: PERFECT_BULLISH_REGIME | PERFECT_BEARISH_REGIME | CONSOLIDATION_CHOP
      matrix_spread_pct:    ((EMA_fast - EMA_anchor) / EMA_anchor) * 100
      squeeze_alert:        true when CONSOLIDATION_CHOP and |spread| < 5% (macro coil)
      layers:               configured EMA stack (periods set server-side)
    """
    if not MACRO_PERIODS:
        return jsonify({
            "error": "CONFIG_NOT_SET",
            "message": "MACRO_STACK_CSV is not configured on this server.",
        }), 503

    # Secondary B2B gate — constant-time comparison against MACRO_GATE_SECRET
    if _GATE_SECRET:
        provided = request.headers.get("X-Macro-Gate", "")
        if not hmac.compare_digest(provided, _GATE_SECRET):
            return jsonify({"error": "GATE_DENIED", "message": "Invalid or missing X-Macro-Gate header."}), 403

    # Parse symbols — from JSON body or query param
    body = request.get_json(silent=True) or {}
    raw = body.get("symbols") or request.args.get("symbols", "")
    if not raw:
        return jsonify({
            "error": "SYMBOLS_REQUIRED",
            "message": (
                "Pass ?symbols=SPY,QQQ,GME or a JSON body {\"symbols\": \"SPY,QQQ,GME\"}. "
                "No hardcoded universe — you drive the scan."
            ),
        }), 400

    symbols = [s.strip().upper() for s in raw.split(",") if s.strip()]
    if not symbols:
        return jsonify({"error": "SYMBOLS_REQUIRED", "message": "No valid symbols provided."}), 400
    if len(symbols) > 50:
        return jsonify({"error": "TOO_MANY_SYMBOLS", "message": "Max 50 symbols per call."}), 400

    now = time.time()
    results = []
    fresh_perfect = []

    for sym in symbols:
        cached = _cache.get(sym)
        if cached and (now - cached["_cached_at"]) < _CACHE_TTL:
            results.append({k: v for k, v in cached.items() if k != "_cached_at"})
            continue

        data = _calculate_matrix_stack(sym)
        data["_cached_at"] = now
        _cache[sym] = data
        entry = {k: v for k, v in data.items() if k != "_cached_at"}
        results.append(entry)

        if entry.get("structural_alignment", "").startswith("PERFECT_"):
            fresh_perfect.append(entry)

    if fresh_perfect:
        _fire_discord(fresh_perfect)

    alignments = [r.get("structural_alignment") for r in results if "structural_alignment" in r]
    summary = {
        "perfect_bullish": alignments.count("PERFECT_BULLISH_REGIME"),
        "perfect_bearish": alignments.count("PERFECT_BEARISH_REGIME"),
        "consolidation_chop": alignments.count("CONSOLIDATION_CHOP"),
        "squeeze_alerts": sum(1 for r in results if r.get("squeeze_alert")),
        "errors": sum(1 for r in results if "error" in r),
    }

    return jsonify(clean_data({
        "status": "success",
        "product": "Pure Macro Matrix",
        "description": (
            "Multi-layer EMA structural alignment engine. "
            "PERFECT_BULLISH_REGIME: institutional uptrend highway. "
            "PERFECT_BEARISH_REGIME: macro distribution confirmed. "
            "CONSOLIDATION_CHOP + squeeze_alert: macro coil building — watch for breakout."
        ),
        "layer_count": len(MACRO_PERIODS),
        "symbols_scanned": len(symbols),
        "summary": summary,
        "results": results,
        "ts": datetime.utcnow().isoformat() + "Z",
    }))
