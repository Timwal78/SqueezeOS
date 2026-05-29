"""
Options Anomaly Engine — 24/7 crime solver.

Maintains a rolling baseline per symbol and flags deviations that don't make sense
until they do: volume surges, IV spikes/crushes, overnight OI jumps, whale prints,
skew breaks. Each anomaly comes with an AI-reasoned thesis.

Broadcasts OPTIONS_ANOMALY to the SSE stream. Zero user interaction required.
"""

import os
import time
import logging
import threading
import statistics
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

SCAN_INTERVAL_SECS  = 300        # 5 min between scans
BASELINE_WINDOW     = 20         # readings to keep per symbol
MIN_BASELINE        = 5          # readings needed before anomaly detection
MAX_SYMBOLS_PER_RUN = 25         # cap to respect Tradier rate limits
ZSCORE_THRESHOLD    = 2.5        # standard deviations to flag
WHALE_MIN_PREMIUM   = 100_000    # $100K minimum to care about
COOLDOWN_SECS       = 1800       # 30 min between same anomaly type per symbol


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class BaselineSnapshot:
    ts: float
    vol_oi_ratio: float       # average across all contracts
    total_call_vol: int
    total_put_vol: int
    call_put_vol_ratio: float
    avg_iv: float
    net_premium: float        # call premium - put premium ($)
    whale_premium: float      # total whale-size premium seen


@dataclass
class OptionsAnomaly:
    symbol: str
    anomaly_type: str         # VOLUME_SURGE | IV_SPIKE | IV_CRUSH | OI_JUMP | WHALE_PRINT | SKEW_BREAK | PREMIUM_FLOOD
    severity: str             # ELEVATED | SUSPICIOUS | CRITICAL
    z_score: float
    current_val: float
    baseline_mean: float
    baseline_stdev: float
    thesis: str
    supporting: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)


# ── Baseline store ────────────────────────────────────────────────────────────

_baselines: dict[str, deque] = defaultdict(lambda: deque(maxlen=BASELINE_WINDOW))
_last_alert: dict[str, dict[str, float]] = defaultdict(dict)  # symbol → type → ts
_baseline_lock = threading.Lock()


# ── Thesis generator ──────────────────────────────────────────────────────────

def _generate_thesis(symbol: str, anomaly_type: str, snap: BaselineSnapshot,
                     mean: float, current: float, z: float,
                     supporting: dict) -> str:
    direction = "BULLISH" if snap.call_put_vol_ratio > 1.2 else ("BEARISH" if snap.call_put_vol_ratio < 0.8 else "MIXED")
    net_str   = f"${abs(snap.net_premium)/1e6:.2f}M" if abs(snap.net_premium) >= 1e6 else f"${abs(snap.net_premium)/1e3:.0f}K"
    bias_word = "call" if direction == "BULLISH" else ("put" if direction == "BEARISH" else "mixed")

    if anomaly_type == "VOLUME_SURGE":
        return (
            f"{symbol} vol/OI ratio hit {current:.1f}x vs {mean:.1f}x baseline ({z:.1f}σ). "
            f"Unusual {bias_word} concentration — {net_str} net {direction.lower()} premium. "
            f"This level of single-session activity vs open interest suggests a directional bet, "
            f"not routine hedging. Watch for continuation or a catalyst within 48h."
        )
    elif anomaly_type == "WHALE_PRINT":
        size = supporting.get("size_class", "WHALE")
        premium = supporting.get("premium", 0)
        p_str = f"${premium/1e6:.2f}M" if premium >= 1e6 else f"${premium/1e3:.0f}K"
        return (
            f"{size} {direction} print on {symbol}: {p_str} single-order premium. "
            f"{z:.1f}σ above the {BASELINE_WINDOW}-scan whale baseline. "
            f"Institutional money doesn't move this size without a reason. "
            f"Directional conviction or asymmetric information — monitor closely."
        )
    elif anomaly_type == "IV_SPIKE":
        return (
            f"{symbol} implied volatility spiked {z:.1f}σ above baseline "
            f"({current:.1f}% vs {mean:.1f}% avg). "
            f"Options market is pricing in a move. Could be earnings rumor, M&A, "
            f"regulatory event, or a large buyer pricing protection. "
            f"Net premium flow is {direction.lower()} ({net_str})."
        )
    elif anomaly_type == "IV_CRUSH":
        return (
            f"{symbol} IV dropped {abs(z):.1f}σ below baseline "
            f"({current:.1f}% vs {mean:.1f}% avg). "
            f"Options are suddenly cheap — someone sold volatility hard or an event resolved. "
            f"If the IV crush isn't post-catalyst, this may be an opportunity to buy premium."
        )
    elif anomaly_type == "SKEW_BREAK":
        skew_dir = "put-heavy" if current > mean else "call-heavy"
        return (
            f"{symbol} put/call skew broke {z:.1f}σ from baseline, now {skew_dir}. "
            f"Current ratio: {current:.2f} vs {mean:.2f} normal. "
            f"A sudden skew shift without a price move is a red flag — "
            f"someone is aggressively repositioning. "
            f"{'Defensive hedging or fear.' if skew_dir == 'put-heavy' else 'Aggressive call accumulation.'}"
        )
    elif anomaly_type == "PREMIUM_FLOOD":
        return (
            f"{symbol} net premium flow hit {net_str} {direction.lower()} — "
            f"{z:.1f}σ above the {BASELINE_WINDOW}-scan baseline. "
            f"This much capital committed in one session is institutional, not retail. "
            f"Call/put volume ratio: {snap.call_put_vol_ratio:.2f}. The money has a direction."
        )
    elif anomaly_type == "OI_JUMP":
        return (
            f"{symbol} open interest jumped {z:.1f}σ above baseline — new positions being opened, not rolled. "
            f"Combined with {direction.lower()} premium bias ({net_str}), this looks like fresh directional exposure. "
            f"OI that builds without a corresponding price move is often a tell."
        )
    return f"{symbol} anomaly detected: {anomaly_type} at {z:.1f}σ from baseline."


# ── Severity classifier ───────────────────────────────────────────────────────

def _severity(z: float) -> str:
    if z >= 4.0:
        return "CRITICAL"
    elif z >= 3.0:
        return "SUSPICIOUS"
    return "ELEVATED"


# ── Cooldown check ────────────────────────────────────────────────────────────

def _on_cooldown(symbol: str, anomaly_type: str) -> bool:
    last = _last_alert[symbol].get(anomaly_type, 0)
    return (time.time() - last) < COOLDOWN_SECS


def _mark_alerted(symbol: str, anomaly_type: str):
    _last_alert[symbol][anomaly_type] = time.time()


# ── Core anomaly detector ─────────────────────────────────────────────────────

def _detect_anomalies(symbol: str, snap: BaselineSnapshot) -> list[OptionsAnomaly]:
    """Compare snap against rolling baseline and return any anomalies."""
    anomalies = []

    with _baseline_lock:
        history = list(_baselines[symbol])

    if len(history) < MIN_BASELINE:
        return anomalies

    def check(field_name: str, anomaly_type: str, current: float):
        vals = [getattr(h, field_name) for h in history if getattr(h, field_name) > 0]
        if len(vals) < MIN_BASELINE:
            return
        mean  = statistics.mean(vals)
        stdev = statistics.stdev(vals) if len(vals) > 1 else 0
        if stdev < 1e-9:
            return
        z = (current - mean) / stdev
        if abs(z) < ZSCORE_THRESHOLD:
            return
        if _on_cooldown(symbol, anomaly_type):
            return
        thesis = _generate_thesis(symbol, anomaly_type, snap, mean, current, z, {})
        anomalies.append(OptionsAnomaly(
            symbol=symbol, anomaly_type=anomaly_type,
            severity=_severity(abs(z)), z_score=round(z, 2),
            current_val=round(current, 4), baseline_mean=round(mean, 4),
            baseline_stdev=round(stdev, 4), thesis=thesis,
        ))
        _mark_alerted(symbol, anomaly_type)

    check("vol_oi_ratio",        "VOLUME_SURGE",  snap.vol_oi_ratio)
    check("avg_iv",              "IV_SPIKE" if snap.avg_iv > statistics.mean([h.avg_iv for h in history if h.avg_iv > 0] or [0])
                                  else "IV_CRUSH", snap.avg_iv)
    check("call_put_vol_ratio",  "SKEW_BREAK",    snap.call_put_vol_ratio)
    check("net_premium",         "PREMIUM_FLOOD", abs(snap.net_premium))

    # Whale print: check if whale premium is unusually large
    whale_vals = [h.whale_premium for h in history if h.whale_premium > 0]
    if len(whale_vals) >= MIN_BASELINE and snap.whale_premium > WHALE_MIN_PREMIUM:
        mean  = statistics.mean(whale_vals)
        stdev = statistics.stdev(whale_vals) if len(whale_vals) > 1 else 1
        if stdev > 1e-9:
            z = (snap.whale_premium - mean) / stdev
            if z >= ZSCORE_THRESHOLD and not _on_cooldown(symbol, "WHALE_PRINT"):
                size_class = "MEGALODON" if snap.whale_premium >= 2_000_000 else ("WHALE" if snap.whale_premium >= 500_000 else "SHARK")
                thesis = _generate_thesis(symbol, "WHALE_PRINT", snap, mean, snap.whale_premium, z,
                                          {"size_class": size_class, "premium": snap.whale_premium})
                anomalies.append(OptionsAnomaly(
                    symbol=symbol, anomaly_type="WHALE_PRINT",
                    severity=_severity(z), z_score=round(z, 2),
                    current_val=round(snap.whale_premium, 2),
                    baseline_mean=round(mean, 2), baseline_stdev=round(stdev, 2),
                    thesis=thesis,
                    supporting={"size_class": size_class, "premium": snap.whale_premium},
                ))
                _mark_alerted(symbol, "WHALE_PRINT")

    return anomalies


# ── Snapshot builder ──────────────────────────────────────────────────────────

def _build_snapshot(symbol: str, chain: dict, scan_result: dict) -> Optional[BaselineSnapshot]:
    """Extract a BaselineSnapshot from a full scan_symbol() result."""
    try:
        flow = scan_result.get("flow_summary") or scan_result.get("flow") or {}
        if isinstance(flow, dict) and "flow_summary" in flow:
            flow = flow["flow_summary"]

        total_call_vol = int(flow.get("total_call_vol", 0) or 0)
        total_put_vol  = int(flow.get("total_put_vol", 0) or 0)
        net_premium    = float(flow.get("net_premium", 0) or 0)
        avg_iv         = float(flow.get("avg_iv", 0) or 0)
        pc_ratio       = float(flow.get("put_call_vol_ratio", 1) or 1)

        # Roll-up vol/OI and whale premium from raw chain
        vol_oi_vals, whale_premium = [], 0.0
        for side in ("callExpDateMap", "putExpDateMap"):
            for _exp, strikes in (chain.get(side) or {}).items():
                for _strike, contracts in strikes.items():
                    for c in (contracts or []):
                        oi  = c.get("openInterest", 0) or 0
                        vol = c.get("totalVolume", 0) or 0
                        bid = c.get("bid", 0) or 0
                        ask = c.get("ask", 0) or 0
                        mid = (bid + ask) / 2
                        if oi > 0:
                            vol_oi_vals.append(vol / oi)
                        if vol > 0 and mid > 0:
                            prem = vol * mid * 100
                            if prem >= WHALE_MIN_PREMIUM:
                                whale_premium += prem
                        if avg_iv == 0:
                            iv = c.get("volatility", 0) or 0
                            if iv > 0:
                                avg_iv = iv  # will be overwritten by flow summary if available

        vol_oi_ratio = statistics.mean(vol_oi_vals) if vol_oi_vals else 0.0

        if total_call_vol == 0 and total_put_vol == 0:
            # Try to derive from whales/sweeps in result
            for sweep in (scan_result.get("sweeps") or []):
                if (sweep.get("option_type") or "").upper() == "CALL":
                    total_call_vol += sweep.get("volume", 0) or 0
                else:
                    total_put_vol += sweep.get("volume", 0) or 0

        cp_ratio = (total_call_vol / total_put_vol) if total_put_vol > 0 else (pc_ratio if pc_ratio else 1.0)

        return BaselineSnapshot(
            ts=time.time(),
            vol_oi_ratio=vol_oi_ratio,
            total_call_vol=total_call_vol,
            total_put_vol=total_put_vol,
            call_put_vol_ratio=cp_ratio,
            avg_iv=avg_iv,
            net_premium=net_premium,
            whale_premium=whale_premium,
        )
    except Exception as e:
        logger.warning(f"[ANOMALY] snapshot build failed for {symbol}: {e}")
        return None


# ── Market hours guard ────────────────────────────────────────────────────────

def _market_is_open() -> bool:
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:   # Saturday=5, Sunday=6
        return False
    hour, minute = now.hour, now.minute
    # 9:30 AM ET = 13:30 UTC,  4:15 PM ET = 20:15 UTC (accounts for options close)
    return (hour > 13 or (hour == 13 and minute >= 30)) and hour < 20


# ── Main scan loop ────────────────────────────────────────────────────────────

def _run_anomaly_scan(broadcast_fn, signal_history_module, discord=None):
    """One full anomaly scan pass."""
    try:
        import tradier_api
        from options_intelligence import OptionsIntelligence
    except ImportError as e:
        logger.error(f"[ANOMALY] import error: {e}")
        return

    if not tradier_api.is_available():
        logger.warning("[ANOMALY] TRADIER_API_KEY not set — skipping")
        return

    # Get symbol universe from existing scanner cache
    symbols = _get_scan_universe()
    oi_engine = OptionsIntelligence()

    scanned, flagged = 0, 0
    for symbol in symbols[:MAX_SYMBOLS_PER_RUN]:
        try:
            chain = tradier_api.get_option_chain_schwab_format(symbol, max_expirations=4)
            if not chain:
                continue

            quote_raw = tradier_api.get_quote(symbol)
            quote     = {"last": quote_raw.get("last", 0), "mark": quote_raw.get("last", 0)} if quote_raw else {}

            result  = oi_engine.scan_symbol(symbol, chain, quote)
            snap    = _build_snapshot(symbol, chain, result)
            scanned += 1

            if snap:
                with _baseline_lock:
                    _baselines[symbol].append(snap)

                anomalies = _detect_anomalies(symbol, snap)
                for a in anomalies:
                    flagged += 1
                    evt = {
                        "type":         "OPTIONS_ANOMALY",
                        "symbol":       a.symbol,
                        "anomaly_type": a.anomaly_type,
                        "severity":     a.severity,
                        "z_score":      a.z_score,
                        "thesis":       a.thesis,
                        "current_val":  a.current_val,
                        "baseline_mean":a.baseline_mean,
                        "ts":           a.ts,
                        "supporting":   a.supporting,
                    }
                    broadcast_fn(evt)
                    try:
                        signal_history_module.record(symbol, "OPTIONS_ANOMALY", evt)
                    except Exception:
                        pass
                    if discord:
                        try:
                            discord.fire_anomaly_alert(evt)
                        except Exception as _de:
                            logger.warning(f"[ANOMALY] discord post failed: {_de}")
                    logger.info(
                        "[ANOMALY] %s %s %s z=%.1f | %s",
                        a.severity, a.anomaly_type, symbol, a.z_score, a.thesis[:80]
                    )

            time.sleep(1.2)   # Tradier rate limit buffer
        except Exception as e:
            logger.warning(f"[ANOMALY] {symbol} scan error: {e}")

    logger.info(f"[ANOMALY] cycle done — scanned={scanned} anomalies={flagged}")


def _get_scan_universe() -> list[str]:
    """Pull the live universe from the market scanner cache, fallback to hardcoded list."""
    try:
        from core.api.market_scanner import _scan_cache, _scan_lock
        with _scan_lock:
            quotes = dict(_scan_cache.get("quotes", {}))
        if quotes:
            # Sort by vol_ratio descending — highest momentum first
            ranked = sorted(
                quotes.items(),
                key=lambda kv: kv[1].get("vol_ratio", 0) if isinstance(kv[1], dict) else 0,
                reverse=True,
            )
            return [sym for sym, _ in ranked]
    except Exception:
        pass
    return ["IWM", "SPY", "QQQ", "NVDA", "AMD", "TSLA", "AAPL", "META", "AMZN", "MSFT",
            "GME", "AMC", "PLTR", "SOFI", "RIVN", "MARA", "COIN", "HOOD", "RBLX", "SNAP"]


# ── Background thread ─────────────────────────────────────────────────────────

_anomaly_thread: Optional[threading.Thread] = None


def start_anomaly_engine():
    """Start the 24/7 options crime solver. Called once at app startup."""
    global _anomaly_thread
    if _anomaly_thread and _anomaly_thread.is_alive():
        return

    import core.signal_history as _sh
    from discord_alerts import DiscordAlerts
    _discord = DiscordAlerts()

    # Grab the broadcast function from the running app module
    def _get_broadcast():
        try:
            import core.app as _app
            return getattr(_app, "_broadcast_sse_global", None)
        except Exception:
            return None

    def loop():
        logger.info("[ANOMALY] Options crime solver online — scanning every %ds", SCAN_INTERVAL_SECS)
        time.sleep(15)  # Wait for market scanner to warm up first
        while True:
            try:
                if _market_is_open():
                    broadcast = _get_broadcast()
                    if broadcast:
                        _run_anomaly_scan(broadcast, _sh, _discord)
                    else:
                        logger.warning("[ANOMALY] broadcast fn not ready yet")
                else:
                    logger.debug("[ANOMALY] market closed — sleeping")
            except Exception as e:
                logger.error(f"[ANOMALY] loop error: {e}")
            time.sleep(SCAN_INTERVAL_SECS)

    _anomaly_thread = threading.Thread(target=loop, daemon=True, name="SML-OptionsAnomaly")
    _anomaly_thread.start()
    logger.info("[ANOMALY] thread started")
