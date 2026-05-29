"""
SML MMLE Engine™ — Beast Mode (Python Port)
═══════════════════════════════════════════════════════════════════════════════
Direct Python translation of SML_MMLE_Beast.pine (PineScript v6)

Computes:
  • VPIN proxy          — Volume-Synchronized Probability of Informed Trading
  • VPIN z-score        — Standardized VPIN for fire threshold gating
  • Vanna proxy         — VVIX/VIX ratio deviation from 50-bar SMA
  • Charm proxy         — VIX9D vs VIX term-structure spread
  • Axis Collapse       — Vanna + Charm aligned with 20-bar price momentum
  • TNT State           — NEUTRAL / COMPRESSED / TNT_LONG / TNT_SHORT
  • Call Wall / Put Wall — Pivot high/low auto-detection
  • VCCW Window         — 09:45–15:30 ET fire gate
  • Composite Score     — Weighted signal confidence 0–100

Python bridge: server_v5.py calls mmle_engine.analyze(symbol, bars, vix_data)
and injects state/composite/walls back into TradingView via Pine input overrides.

Author: ScriptMasterLabs™ / SqueezeOS Pro
"""

import logging
import math
import os
import urllib.request
import urllib.error
import json as _json
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── MMLE Discord webhook (set DISCORD_WEBHOOK_MMLE in .env) ──
_MMLE_WEBHOOK = os.getenv("DISCORD_WEBHOOK_MMLE", "")

# Discord color codes
_TNT_GREEN = 3066993   # #2ECC71
_TNT_RED   = 15158332  # #E74C3C
_COMPRESS  = 16776960  # #FFFF00

def _fire_discord(result: Dict) -> None:
    """Send MMLE Beast Mode alert to Discord webhook (non-blocking, best-effort)."""
    if not _MMLE_WEBHOOK:
        return
    state  = result.get("state", "NEUTRAL")
    symbol = result.get("symbol", "?")
    price  = result.get("magnet") or 0
    vpin_z = result.get("vpin_z")
    vpin   = result.get("vpin")
    ax     = result.get("axis_collapse", False)
    cw     = result.get("call_wall")
    pw     = result.get("put_wall")
    comp   = result.get("composite", 0)
    vanna  = result.get("vanna_proxy")
    charm  = result.get("charm_proxy")

    if state == "TNT_LONG":
        color, emoji, action = _TNT_GREEN, "🟢", "FIRE LONG"
    elif state == "TNT_SHORT":
        color, emoji, action = _TNT_RED, "🔴", "FIRE SHORT"
    else:
        color, emoji, action = _COMPRESS, "🟡", "COMPRESSED"

    fields = [
        {"name": "State",        "value": state,                                   "inline": True},
        {"name": "Composite",    "value": f"{comp:.1f}/100",                       "inline": True},
        {"name": "VPIN z",       "value": f"{vpin_z:.2f}" if vpin_z else "n/a",   "inline": True},
        {"name": "VPIN",         "value": f"{vpin:.3f}"   if vpin   else "n/a",   "inline": True},
        {"name": "Axis Collapse","value": "✅ YES" if ax else "no",                 "inline": True},
        {"name": "Vanna proxy",  "value": f"{vanna:.3f}"  if vanna  else "n/a",   "inline": True},
        {"name": "Charm proxy",  "value": f"{charm:.3f}"  if charm  else "n/a",   "inline": True},
        {"name": "Call Wall",    "value": f"${cw:.2f}"    if cw     else "—",      "inline": True},
        {"name": "Put Wall",     "value": f"${pw:.2f}"    if pw     else "—",      "inline": True},
    ]

    payload = _json.dumps({
        "username": "MMLE-BEAST",
        "embeds": [{
            "title": f"{emoji} MMLE-BEAST {action} — {symbol}",
            "color": color,
            "fields": fields,
            "footer": {"text": f"SqueezeOS Pro · {datetime.now().strftime('%H:%M:%S ET')}"}
        }]
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            _MMLE_WEBHOOK,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        logger.warning(f"[MMLE] Discord alert failed: {e}")


VPIN_BUCKETS      = int(os.getenv("MMLE_VPIN_BUCKETS", "50"))
VPIN_BUCKET_PCT   = float(os.getenv("MMLE_VPIN_BUCKET_PCT", "0.005"))
PIVOT_LOOKBACK    = int(os.getenv("MMLE_PIVOT_LOOKBACK", "20"))
EMA_FAST_LEN      = int(os.getenv("MMLE_EMA_FAST", "20"))
EMA_SLOW_LEN      = int(os.getenv("MMLE_EMA_SLOW", "50"))
VCCW_OPEN_MIN     = int(os.getenv("MMLE_VCCW_OPEN_MIN", "585"))   # 09:45 ET
VCCW_CLOSE_MIN    = int(os.getenv("MMLE_VCCW_CLOSE_MIN", "930"))  # 15:30 ET
FIRE_VPIN_Z_MIN   = float(os.getenv("MMLE_FIRE_VPIN_Z_MIN", "1.0"))
VANNA_SMA_LEN     = int(os.getenv("MMLE_VANNA_SMA_LEN", "50"))
RET20_BARS        = int(os.getenv("MMLE_RET20_BARS", "20"))
ACTIVE_AXES_FIRE  = int(os.getenv("MMLE_ACTIVE_AXES_FIRE", "3"))


# ═══════════════════════════════════════════════════════════════
# MATH UTILITIES
# ═══════════════════════════════════════════════════════════════

def _ema(values: List[float], period: int) -> List[float]:
    """Exponential Moving Average (same multiplier as PineScript ta.ema)."""
    if not values:
        return []
    k = 2.0 / (period + 1)
    result = [values[0]]
    for v in values[1:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def _sma(values: List[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _stdev(values: List[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    window = values[-period:]
    mean = sum(window) / len(window)
    variance = sum((x - mean) ** 2 for x in window) / len(window)
    return math.sqrt(variance)


def _pivot_highs(highs: List[float], lookback: int) -> List[float]:
    """Detect pivot highs (local maxima within ±lookback bars)."""
    pivots = []
    for i in range(lookback, len(highs) - lookback):
        window = highs[i - lookback: i + lookback + 1]
        if highs[i] == max(window):
            pivots.append(highs[i])
    return pivots


def _pivot_lows(lows: List[float], lookback: int) -> List[float]:
    """Detect pivot lows (local minima within ±lookback bars)."""
    pivots = []
    for i in range(lookback, len(lows) - lookback):
        window = lows[i - lookback: i + lookback + 1]
        if lows[i] == min(window):
            pivots.append(lows[i])
    return pivots


def _is_vccw_open(dt: Optional[datetime] = None) -> bool:
    """Return True if current ET time is within the VCCW fire window."""
    if dt is None:
        from datetime import timezone
        import time
        # Use system time, convert to ET (UTC-4 or UTC-5)
        utc_now = datetime.now(timezone.utc)
        # Simple ET offset: DST-aware via zoneinfo if available
        try:
            from zoneinfo import ZoneInfo
            et_now = utc_now.astimezone(ZoneInfo("America/New_York"))
        except ImportError:
            # Fallback: assume EDT (UTC-4)
            from datetime import timedelta
            et_now = utc_now - timedelta(hours=4)
        dt = et_now

    nyc_minute = dt.hour * 60 + dt.minute
    return VCCW_OPEN_MIN <= nyc_minute <= VCCW_CLOSE_MIN


# ═══════════════════════════════════════════════════════════════
# VPIN ENGINE
# ═══════════════════════════════════════════════════════════════

class VPINEngine:
    """
    Bucket-based VPIN proxy matching PineScript logic exactly.

    Input: stream of (close, volume) bars.
    Output: vpin (0–1), vpin_z (z-score vs rolling 400-bucket history).
    """

    def __init__(self, n_buckets: int = VPIN_BUCKETS, bucket_pct: float = VPIN_BUCKET_PCT):
        self.n_buckets  = n_buckets
        self.bucket_pct = bucket_pct

        self._cum_buy   = 0.0
        self._cum_sell  = 0.0
        self._cum_total = 0.0
        self._buy_buckets:  deque = deque(maxlen=n_buckets)
        self._sell_buckets: deque = deque(maxlen=n_buckets)
        self._vpin_hist:    deque = deque(maxlen=400)

        self._avg_vol_window: deque = deque(maxlen=200)

    def update(self, close: float, prev_close: float, volume: float) -> Dict:
        """
        Feed one bar. Returns current vpin and vpin_z (None if insufficient data).
        """
        # Rolling avg volume (200 bars, same as Pine sma(volume,200))
        self._avg_vol_window.append(volume)
        avg_vol = sum(self._avg_vol_window) / len(self._avg_vol_window)
        bucket_volume = max(1.0, avg_vol * self.bucket_pct)

        # Bar side classification
        if close > prev_close:
            self._cum_buy   += volume
        elif close < prev_close:
            self._cum_sell  += volume
        else:
            self._cum_buy   += volume / 2.0
            self._cum_sell  += volume / 2.0
        self._cum_total += volume

        # Drain full buckets
        while self._cum_total >= bucket_volume:
            scale = bucket_volume / self._cum_total
            b = self._cum_buy   * scale
            s = self._cum_sell  * scale
            self._buy_buckets.append(b)
            self._sell_buckets.append(s)
            self._cum_buy   -= b
            self._cum_sell  -= s
            self._cum_total -= bucket_volume

        # Compute VPIN
        vpin = None
        if len(self._buy_buckets) >= self.n_buckets:
            num = sum(abs(b - s) for b, s in zip(self._buy_buckets, self._sell_buckets))
            den = sum(b + s         for b, s in zip(self._buy_buckets, self._sell_buckets))
            if den > 0:
                vpin = num / den
                self._vpin_hist.append(vpin)

        # Compute VPIN z-score
        vpin_z = None
        hist = list(self._vpin_hist)
        if vpin is not None and len(hist) >= 30:
            mu = sum(hist) / len(hist)
            sd = math.sqrt(sum((x - mu) ** 2 for x in hist) / len(hist))
            vpin_z = (vpin - mu) / sd if sd > 0 else None

        return {"vpin": vpin, "vpin_z": vpin_z}

    def reset(self):
        self._cum_buy = self._cum_sell = self._cum_total = 0.0
        self._buy_buckets.clear()
        self._sell_buckets.clear()


# ═══════════════════════════════════════════════════════════════
# AXIS COLLAPSE ENGINE
# ═══════════════════════════════════════════════════════════════

class AxisCollapseEngine:
    """
    Detects Axis Collapse: when Vanna + Charm proxies align with price momentum.

    Vanna proxy  = VVIX/VIX ratio deviation from its 50-bar SMA
    Charm proxy  = (VIX9D - VIX) / VIX  (term-structure steepness)
    Axis Collapse = sign(vanna) == sign(charm) == sign(ret20)

    Requires: VIX, VIX9D, VVIX time-series (fetched from Tradier or Polygon).
    """

    def __init__(self, vanna_sma_len: int = VANNA_SMA_LEN, ret20_bars: int = RET20_BARS):
        self.vanna_sma_len = vanna_sma_len
        self.ret20_bars    = ret20_bars
        self._vvix_vix_hist: deque = deque(maxlen=vanna_sma_len + 10)

    def update(
        self,
        closes: List[float],
        vix: Optional[float],
        vix9d: Optional[float],
        vvix: Optional[float],
    ) -> Dict:
        """
        Compute axis collapse signal.

        Args:
            closes: Recent close prices (need >= ret20_bars)
            vix:   Current VIX value
            vix9d: Current VIX9D (9-day VIX) value
            vvix:  Current VVIX value

        Returns dict with:
            vanna_proxy, charm_proxy, axis_collapse, ret20, active_axes
        """
        result = {
            "vanna_proxy":   None,
            "charm_proxy":   None,
            "axis_collapse": False,
            "ret20":         None,
            "active_axes":   0,
        }

        # 20-bar return
        if len(closes) >= self.ret20_bars + 1:
            base = closes[-(self.ret20_bars + 1)]
            ret20 = (closes[-1] - base) / base if base != 0 else 0.0
            result["ret20"] = ret20
        else:
            return result

        # Vanna proxy: needs VIX + VVIX
        vanna_proxy = None
        if vix and vvix and vix > 0:
            ratio = vvix / vix
            self._vvix_vix_hist.append(ratio)
            sma = _sma(list(self._vvix_vix_hist), self.vanna_sma_len)
            if sma is not None:
                vanna_proxy = ratio - sma
        result["vanna_proxy"] = vanna_proxy

        # Charm proxy: needs VIX9D + VIX
        charm_proxy = None
        if vix9d and vix and vix > 0:
            charm_proxy = (vix9d - vix) / vix
        result["charm_proxy"] = charm_proxy

        # Count active axes (signals aligned)
        active_axes = 0
        if vanna_proxy is not None:
            active_axes += 1
        if charm_proxy is not None:
            active_axes += 1
        result["active_axes"] = active_axes

        # Axis Collapse: all three signs agree
        if vanna_proxy is not None and charm_proxy is not None and ret20 != 0:
            def _sign(x):
                return 1 if x > 0 else (-1 if x < 0 else 0)
            if _sign(vanna_proxy) == _sign(charm_proxy) == _sign(ret20):
                result["axis_collapse"] = True

        return result


# ═══════════════════════════════════════════════════════════════
# MMLE ENGINE  (full TNT state machine)
# ═══════════════════════════════════════════════════════════════

class MMLeEngine:
    """
    Full Python port of SML MMLE Beast Mode.

    Usage (per-symbol, called each bar from server_v5.py):

        engine = MMLeEngine()
        result = engine.analyze(symbol, bars, vix_data)

    bars = [{"open":..,"high":..,"low":..,"close":..,"volume":..}, ...]
    vix_data = {"vix": 18.5, "vix9d": 16.2, "vvix": 95.3}  (or None values)
    """

    def __init__(self):
        # Per-symbol state
        self._vpin:    Dict[str, VPINEngine]         = {}
        self._axis:    Dict[str, AxisCollapseEngine] = {}
        self._call_wall: Dict[str, Optional[float]]  = {}
        self._put_wall:  Dict[str, Optional[float]]  = {}

    def _get_vpin(self, symbol: str) -> VPINEngine:
        if symbol not in self._vpin:
            self._vpin[symbol] = VPINEngine()
        return self._vpin[symbol]

    def _get_axis(self, symbol: str) -> AxisCollapseEngine:
        if symbol not in self._axis:
            self._axis[symbol] = AxisCollapseEngine()
        return self._axis[symbol]

    def analyze(
        self,
        symbol: str,
        bars: List[Dict],
        vix_data: Optional[Dict] = None,
        python_override: Optional[Dict] = None,
        dt: Optional[datetime] = None,
    ) -> Dict:
        """
        Full MMLE analysis for one symbol.

        Args:
            symbol:          Ticker (e.g. "AMC")
            bars:            List of OHLCV dicts (oldest first), min 50 bars
            vix_data:        {"vix": float, "vix9d": float, "vvix": float}
            python_override: {"state":"TNT_LONG", "call_wall":15.0, ...} (optional)
            dt:              Current datetime for VCCW window check

        Returns:
            {
              "symbol":        str,
              "state":         "NEUTRAL|COMPRESSED|TNT_LONG|TNT_SHORT",
              "fire_long":     bool,
              "fire_short":    bool,
              "watch_long":    bool,
              "watch_short":   bool,
              "vpin":          float|None,
              "vpin_z":        float|None,
              "vpin_spike":    bool,
              "vanna_proxy":   float|None,
              "charm_proxy":   float|None,
              "axis_collapse": bool,
              "active_axes":   int,
              "ret20":         float|None,
              "call_wall":     float|None,
              "put_wall":      float|None,
              "magnet":        float|None,  (VWAP proxy = avg close)
              "composite":     float,        (0–100)
              "vccw_open":     bool,
              "source":        "Python"|"Local",
            }
        """
        if not bars or len(bars) < 2:
            logger.warning(f"[MMLE] {symbol}: insufficient bars")
            return self._empty(symbol)

        closes  = [float(b["close"])  for b in bars]
        highs   = [float(b["high"])   for b in bars]
        lows    = [float(b["low"])    for b in bars]
        volumes = [float(b["volume"]) for b in bars]

        # ── VPIN ──────────────────────────────────────────────
        vpin_engine = self._get_vpin(symbol)
        # Feed all bars to VPIN (stateful — only new bars in production,
        # but for batch analysis we replay all)
        vpin_result = {"vpin": None, "vpin_z": None}
        for i in range(1, len(bars)):
            vpin_result = vpin_engine.update(closes[i], closes[i - 1], volumes[i])

        vpin     = vpin_result["vpin"]
        vpin_z   = vpin_result["vpin_z"]
        vpin_spike = (vpin_z is not None and vpin_z >= 2.0)

        # ── AXIS COLLAPSE ──────────────────────────────────────
        vix_d = vix_data or {}
        axis_engine = self._get_axis(symbol)
        axis = axis_engine.update(
            closes,
            vix   = vix_d.get("vix"),
            vix9d = vix_d.get("vix9d"),
            vvix  = vix_d.get("vvix"),
        )

        # ── WALLS (pivot high/low) ─────────────────────────────
        call_wall = None
        put_wall  = None
        if len(highs) > PIVOT_LOOKBACK * 2:
            ph = _pivot_highs(highs, PIVOT_LOOKBACK)
            pl = _pivot_lows(lows,   PIVOT_LOOKBACK)
            if ph:
                call_wall = ph[-1]
                self._call_wall[symbol] = call_wall
            elif symbol in self._call_wall:
                call_wall = self._call_wall[symbol]

            if pl:
                put_wall = pl[-1]
                self._put_wall[symbol] = put_wall
            elif symbol in self._put_wall:
                put_wall = self._put_wall[symbol]

        # Python override takes precedence
        if python_override:
            if python_override.get("call_wall", 0) > 0:
                call_wall = python_override["call_wall"]
            if python_override.get("put_wall", 0) > 0:
                put_wall = python_override["put_wall"]

        # ── EMA TREND ─────────────────────────────────────────
        ema_fast_vals = _ema(closes, EMA_FAST_LEN)
        ema_slow_vals = _ema(closes, EMA_SLOW_LEN)
        ema_fast = ema_fast_vals[-1] if ema_fast_vals else closes[-1]
        ema_slow = ema_slow_vals[-1] if ema_slow_vals else closes[-1]
        spot = closes[-1]
        trend_up = spot > ema_fast and ema_fast > ema_slow
        trend_dn = spot < ema_fast and ema_fast < ema_slow

        # ── TNT STATE MACHINE ─────────────────────────────────
        vpin_ready  = (vpin_z is not None and vpin_z >= FIRE_VPIN_Z_MIN)
        ret20       = axis.get("ret20", 0) or 0
        ax_collapse = axis.get("axis_collapse", False)
        active_axes = axis.get("active_axes", 0)

        local_long  = trend_up and vpin_ready and (ax_collapse and ret20 > 0 or active_axes >= ACTIVE_AXES_FIRE)
        local_short = trend_dn and vpin_ready and (ax_collapse and ret20 < 0 or active_axes >= ACTIVE_AXES_FIRE)
        local_comp  = vpin_ready and not local_long and not local_short

        use_python = bool(python_override and python_override.get("state") not in (None, "AUTO"))
        if use_python:
            state = python_override["state"]
        elif local_long:
            state = "TNT_LONG"
        elif local_short:
            state = "TNT_SHORT"
        elif local_comp:
            state = "COMPRESSED"
        else:
            state = "NEUTRAL"

        # ── VCCW WINDOW ───────────────────────────────────────
        vccw_open = _is_vccw_open(dt)

        # ── FIRE / WATCH ──────────────────────────────────────
        trap_long  = (state == "TNT_LONG")
        trap_short = (state == "TNT_SHORT")

        # bar side (last bar)
        bar_side = 1 if closes[-1] > closes[-2] else (-1 if closes[-1] < closes[-2] else 0)
        lit_long  = bar_side >= 0
        lit_short = bar_side <= 0

        fire_long  = vccw_open and trap_long  and lit_long
        fire_short = vccw_open and trap_short and lit_short
        watch_long  = trap_long  and not fire_long
        watch_short = trap_short and not fire_short

        # ── COMPOSITE SCORE (0–100) ───────────────────────────
        composite = self._composite(vpin_z, ax_collapse, active_axes, state, axis)

        # ── MAGNET (VWAP proxy = average of last 20 closes × volume) ─
        magnet = self._vwap_proxy(closes[-20:], volumes[-20:]) if len(closes) >= 20 else spot

        result = {
            "symbol":        symbol,
            "state":         state,
            "fire_long":     fire_long,
            "fire_short":    fire_short,
            "watch_long":    watch_long,
            "watch_short":   watch_short,
            "vpin":          round(vpin, 4)      if vpin    is not None else None,
            "vpin_z":        round(vpin_z, 3)    if vpin_z  is not None else None,
            "vpin_spike":    vpin_spike,
            "vanna_proxy":   round(axis["vanna_proxy"], 4) if axis["vanna_proxy"] is not None else None,
            "charm_proxy":   round(axis["charm_proxy"], 4) if axis["charm_proxy"] is not None else None,
            "axis_collapse": ax_collapse,
            "active_axes":   active_axes,
            "ret20":         round(ret20, 4),
            "call_wall":     round(call_wall, 2) if call_wall else None,
            "put_wall":      round(put_wall, 2)  if put_wall  else None,
            "magnet":        round(magnet, 2),
            "composite":     round(composite, 1),
            "vccw_open":     vccw_open,
            "ema_fast":      round(ema_fast, 2),
            "ema_slow":      round(ema_slow, 2),
            "source":        "Python" if use_python else "Local",
        }

        # ── DISCORD FIRE ALERT ────────────────────────────────
        if fire_long or fire_short:
            import threading as _t
            _t.Thread(target=_fire_discord, args=(result,), daemon=True).start()

        return result

    def _composite(self, vpin_z, axis_collapse, active_axes, state, axis) -> float:
        """
        Composite score 0–100.
        Mirrors PineScript composite logic:
          40% VPIN pressure, 30% Axis Collapse, 20% State alignment, 10% Active Axes
        """
        vpin_score = min(100.0, max(0.0, (vpin_z or 0) / 3.0 * 100)) * 0.40
        axis_score = (100.0 if axis_collapse else 0.0) * 0.30
        state_score = (
            100.0 if state in ("TNT_LONG", "TNT_SHORT") else
            60.0  if state == "COMPRESSED" else
            0.0
        ) * 0.20
        axes_score = min(100.0, (active_axes / 2.0) * 100) * 0.10
        return vpin_score + axis_score + state_score + axes_score

    def _vwap_proxy(self, closes: List[float], volumes: List[float]) -> float:
        """Simple VWAP proxy using typical price × volume / total volume."""
        tv = sum(volumes)
        if tv == 0:
            return closes[-1]
        return sum(c * v for c, v in zip(closes, volumes)) / tv

    def _empty(self, symbol: str) -> Dict:
        return {
            "symbol": symbol, "state": "NEUTRAL",
            "fire_long": False, "fire_short": False,
            "watch_long": False, "watch_short": False,
            "vpin": None, "vpin_z": None, "vpin_spike": False,
            "vanna_proxy": None, "charm_proxy": None,
            "axis_collapse": False, "active_axes": 0, "ret20": None,
            "call_wall": None, "put_wall": None,
            "magnet": None, "composite": 0.0,
            "vccw_open": False, "ema_fast": None, "ema_slow": None,
            "source": "Local",
        }


# ═══════════════════════════════════════════════════════════════
# SINGLETON — import and reuse across server_v5.py
# ═══════════════════════════════════════════════════════════════

_engine_instance: Optional[MMLeEngine] = None

def get_engine() -> MMLeEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = MMLeEngine()
    return _engine_instance


def analyze(symbol: str, bars: List[Dict], vix_data: Optional[Dict] = None,
            python_override: Optional[Dict] = None) -> Dict:
    """Convenience wrapper — call this from server_v5.py."""
    return get_engine().analyze(symbol, bars, vix_data, python_override)
