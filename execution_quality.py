"""
Execution Quality Primitives
============================
Pure, testable functions for the order-placement layer. Extracted so the
slippage/spread/extension logic can be unit-tested without touching a broker.

Everything here is a RISK FILTER or a PRICING RULE. Nothing here is a claimed
trading edge, and none of it has been backtested as a signal — these functions
exist to stop the executor from (a) paying an unbounded price on a market
order, (b) buying into a spread wide enough to eat the whole thesis, and
(c) chasing a move that has already happened. Per this repo's Prime Directive
they read only real quote/bar data and return an honest "unavailable" rather
than estimating a price that was never quoted.

Design rule that governs every function here:

    ENTRIES FAIL CLOSED. EXITS FAIL OPEN.

If the data needed to price an entry safely is missing, the entry is refused —
there is always another setup. If the data needed to price an EXIT is missing,
we fall back to whatever gets us flat (a market order), because an unmanaged
open position is the larger risk. Capital preservation is the constraint that
outranks fill quality.

Environment variables (all optional, all with safe defaults):
  IAM_LIMIT_OFFSET_BPS        = 10    # marketable-limit offset past the touch, basis points
  IAM_MAX_SPREAD_PCT_EQUITY   = 0.60  # refuse equity ENTRY above this bid/ask spread %
  IAM_MAX_SPREAD_PCT_OPTION   = 8.0   # refuse option ENTRY above this bid/ask spread %
  IAM_MAX_ENTRY_EXTENSION_ATR = 1.0   # refuse entry once price has run this many ATRs
                                      #   past the price the signal was generated at
  IAM_MAX_BAR_EXTENSION_ATR   = 2.0   # refuse entry when the signal bar's own range
                                      #   already exceeds this many ATRs AND price sits
                                      #   in the top/bottom `IAM_BAR_POS_PCT` of it
  IAM_BAR_POS_PCT             = 0.80  # "already at the extreme of the bar" threshold
"""

import os
import logging
from typing import Optional, Sequence

logger = logging.getLogger("EXEC-QUALITY")


# ── Config ─────────────────────────────────────────────────────────────────────
def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


LIMIT_OFFSET_BPS        = lambda: _env_float("IAM_LIMIT_OFFSET_BPS", 10.0)
MAX_SPREAD_PCT_EQUITY   = lambda: _env_float("IAM_MAX_SPREAD_PCT_EQUITY", 0.60)
MAX_SPREAD_PCT_OPTION   = lambda: _env_float("IAM_MAX_SPREAD_PCT_OPTION", 8.0)
MAX_ENTRY_EXTENSION_ATR = lambda: _env_float("IAM_MAX_ENTRY_EXTENSION_ATR", 1.0)
MAX_BAR_EXTENSION_ATR   = lambda: _env_float("IAM_MAX_BAR_EXTENSION_ATR", 2.0)
BAR_POS_PCT             = lambda: _env_float("IAM_BAR_POS_PCT", 0.80)


# ── Bar helpers ────────────────────────────────────────────────────────────────
def _ohlc(bar: dict) -> tuple:
    """Bars in this codebase come from two shapes: DataManager.get_bars emits
    {"o","h","l","c","v"}; some engines/tests use {"open","high","low","close"}.
    Read both rather than assuming one — mismatched key casing has already
    caused one real production incident here (avg_down_engine reading Volume
    as price because it checked "close" and the frame had "Close")."""
    o = bar.get("o", bar.get("open", bar.get("Open")))
    h = bar.get("h", bar.get("high", bar.get("High")))
    l = bar.get("l", bar.get("low", bar.get("Low")))
    c = bar.get("c", bar.get("close", bar.get("Close")))
    return o, h, l, c


def atr(bars: Sequence[dict], period: int = 14) -> Optional[float]:
    """
    True-range average over the last `period` bars (simple mean of TR, matching
    the convention already used by mm_intel_engine._atr_series rather than
    Wilder's smoothing — kept consistent so two modules in this repo don't
    report different ATRs for the same bars).

    Returns None when there is not enough real history. Callers must treat
    None as "unknown", never as zero — a zero ATR would make every extension
    check divide-by-zero or silently pass.
    """
    if not bars or len(bars) < period + 1:
        return None
    trs = []
    for i in range(len(bars) - period, len(bars)):
        _, h, l, c = _ohlc(bars[i])
        _, _, _, prev_c = _ohlc(bars[i - 1])
        if h is None or l is None or prev_c is None:
            return None
        try:
            h, l, prev_c = float(h), float(l), float(prev_c)
        except (TypeError, ValueError):
            return None
        trs.append(max(h - l, abs(h - prev_c), abs(l - prev_c)))
    if not trs:
        return None
    value = sum(trs) / len(trs)
    return value if value > 0 else None


# ── Live quote ─────────────────────────────────────────────────────────────────
def live_nbbo(symbol: str) -> Optional[dict]:
    """
    Real bid/ask/last for an equity symbol from Tradier. Returns None when no
    real quote is available — never a synthesised or last-known price.

    Why this exists: every scanner in this repo passes the SIGNAL BAR'S CLOSE
    down to the executor as `price` (e.g. breakout_scanner passes
    bars[-1]["c"]). On a daily-bar engine that number can be up to a full
    session stale by the time the order is actually placed, and it was being
    used for BOTH position sizing AND the protective stop level. A stop
    computed off a stale close is not the stop the operator thinks they have.
    """
    try:
        import tradier_api
        q = tradier_api.get_quote(symbol)
    except Exception as e:
        logger.warning(f"[EXEC-QUALITY] quote fetch failed for {symbol}: {e}")
        return None
    if not q:
        return None

    def _f(key):
        try:
            v = q.get(key)
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    bid, ask, last = _f("bid"), _f("ask"), _f("last")
    mid = (bid + ask) / 2.0 if (bid and ask and bid > 0 and ask > 0 and ask >= bid) else None
    return {"bid": bid, "ask": ask, "last": last, "mid": mid,
            "reference": mid or last or ask or bid}


def spread_pct(bid: Optional[float], ask: Optional[float]) -> Optional[float]:
    """Bid/ask spread as a percentage of the mid. None when not computable."""
    if not bid or not ask or bid <= 0 or ask <= 0 or ask < bid:
        return None
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return None
    return (ask - bid) / mid * 100.0


def spread_ok(bid: Optional[float], ask: Optional[float], *,
              is_option: bool, is_entry: bool) -> tuple:
    """
    (allowed: bool, reason: str) — spread guard.

    Entries fail closed: an unquotable or too-wide book refuses the ENTRY,
    because the spread is a guaranteed, immediate loss on a position we chose
    to open. Exits always pass: we never trap ourselves in a position because
    the book got wide, which is exactly when getting out matters most.
    """
    if not is_entry:
        return True, "exit — spread guard not applied"
    sp = spread_pct(bid, ask)
    if sp is None:
        return False, "no real two-sided quote — entry refused (fail closed)"
    cap = MAX_SPREAD_PCT_OPTION() if is_option else MAX_SPREAD_PCT_EQUITY()
    if sp > cap:
        return False, f"spread {sp:.2f}% > cap {cap:.2f}% — entry refused"
    return True, f"spread {sp:.2f}% within {cap:.2f}%"


# ── Marketable limit pricing ───────────────────────────────────────────────────
def have_book(bid: Optional[float], ask: Optional[float]) -> bool:
    """True when there is a real, sane two-sided quote to price against."""
    return bool(bid and ask and bid > 0 and ask > 0 and ask >= bid)


def fallback_limit(reference_price: float, side: str,
                   *, offset_bps: Optional[float] = None) -> Optional[float]:
    """
    A bounded limit derived from a reference price (the signal price) for when
    no live two-sided quote is available.

    This exists so a quote outage DEGRADES execution instead of halting it. The
    behaviour being replaced was a raw market order, and a bounded limit off a
    slightly stale reference strictly dominates that: worst case it simply does
    not fill, which is a far better failure than an unbounded print. The offset
    is deliberately wider than `marketable_limit`'s (4x) because the reference
    is less trustworthy than a live touch.
    """
    if not reference_price or reference_price <= 0:
        return None
    bps = (LIMIT_OFFSET_BPS() if offset_bps is None else offset_bps) * 4.0
    if side == "buy":
        px = reference_price * (1.0 + bps / 10000.0)
    elif side == "sell":
        px = reference_price * (1.0 - bps / 10000.0)
    else:
        return None
    px = round(px, 2)
    return px if px > 0 else None


def marketable_limit(bid: Optional[float], ask: Optional[float], side: str,
                     *, offset_bps: Optional[float] = None) -> Optional[float]:
    """
    A limit price that should fill immediately but cannot fill at an arbitrary
    price — the replacement for the raw market orders this executor was
    sending during regular hours.

    buy  → ask + offset   (crosses the spread, capped)
    sell → bid - offset   (crosses the spread, capped)

    `offset_bps` is measured against the touch price, so it scales with the
    instrument instead of being a flat dollar amount that is trivial on SPY
    and enormous on a $0.40 option.

    Returns None when there is no real two-sided quote to price against —
    the caller decides what that means (entries refuse, exits fall back to a
    market order).
    """
    if not bid or not ask or bid <= 0 or ask <= 0 or ask < bid:
        return None
    bps = LIMIT_OFFSET_BPS() if offset_bps is None else offset_bps
    if side == "buy":
        px = ask * (1.0 + bps / 10000.0)
    elif side == "sell":
        px = bid * (1.0 - bps / 10000.0)
    else:
        return None
    px = round(px, 2)
    return px if px > 0 else None


# ── Anti-chase / extension guards ──────────────────────────────────────────────
def entry_extension_atr(signal_price: float, current_price: float,
                        atr_value: Optional[float]) -> Optional[float]:
    """
    How far price has ALREADY travelled past the price the signal fired at,
    measured in ATRs. Signed relative to nothing — the caller supplies the
    direction context via `chase_guard`.

    None when ATR is unknown (insufficient history) or either price is invalid.
    """
    if not atr_value or atr_value <= 0:
        return None
    if signal_price is None or current_price is None:
        return None
    if signal_price <= 0 or current_price <= 0:
        return None
    return (current_price - signal_price) / atr_value


def bar_exhausted(bars: Sequence[dict], current_price: float,
                  action: str, atr_value: Optional[float]) -> tuple:
    """
    (exhausted: bool, reason: str)

    "The move already happened on this bar." True when the most recent bar's
    own high-low range already exceeds MAX_BAR_EXTENSION_ATR × ATR *and* the
    current price is sitting in the top (for a BUY) or bottom (for a SELL)
    BAR_POS_PCT of that range — i.e. we would be buying the high of an
    already-outsized bar.

    This is a classic don't-chase filter, not a proven edge. It is disclosed
    as a heuristic in the module docstring and in the executor's log line.
    """
    if not bars or not atr_value or atr_value <= 0:
        return False, "insufficient data for bar-exhaustion check — not blocking"
    _, h, l, _ = _ohlc(bars[-1])
    if h is None or l is None:
        return False, "bar missing high/low — not blocking"
    try:
        h, l = float(h), float(l)
    except (TypeError, ValueError):
        return False, "bar high/low not numeric — not blocking"
    rng = h - l
    if rng <= 0:
        return False, "zero-range bar — not blocking"
    if rng < MAX_BAR_EXTENSION_ATR() * atr_value:
        return False, f"bar range {rng:.2f} < {MAX_BAR_EXTENSION_ATR():.1f}×ATR — normal bar"
    pos = (current_price - l) / rng  # 0.0 = at the low, 1.0 = at the high
    thresh = BAR_POS_PCT()
    if action == "BUY" and pos >= thresh:
        return True, (f"bar range {rng:.2f} ≥ {MAX_BAR_EXTENSION_ATR():.1f}×ATR "
                      f"and price is at {pos*100:.0f}% of it — buying the high, refused")
    if action == "SELL" and pos <= (1.0 - thresh):
        return True, (f"bar range {rng:.2f} ≥ {MAX_BAR_EXTENSION_ATR():.1f}×ATR "
                      f"and price is at {pos*100:.0f}% of it — selling the low, refused")
    return False, f"bar extended but price at {pos*100:.0f}% of range — not at the extreme"


def chase_guard(action: str, signal_price: float, current_price: float,
                bars: Sequence[dict], atr_period: int = 14) -> tuple:
    """
    (allowed: bool, reason: str) — the composite anti-chase gate for ENTRIES.

    Blocks an entry when EITHER:
      1. Price has already run more than MAX_ENTRY_EXTENSION_ATR ATRs in the
         signal's own direction since the signal fired. The edge the signal
         claimed is the move from the signal price; if most of it is already
         realised, what's left is a worse risk/reward than the backtest that
         justified the strategy ever measured.
      2. The signal bar is exhausted (see bar_exhausted).

    Deliberately does NOT block when ATR is unknown — with no real history to
    measure against, refusing every entry would silently disable the live
    systems entirely. That is the one place this module tolerates fail-open,
    and it is logged by the caller rather than hidden.
    """
    a = atr(bars, atr_period)
    if a is None:
        return True, "ATR unavailable (insufficient real history) — chase guard not applied"

    ext = entry_extension_atr(signal_price, current_price, a)
    if ext is not None:
        cap = MAX_ENTRY_EXTENSION_ATR()
        # A BUY is "chased" when price ran UP past the signal; a SELL (which in
        # this executor means close-long + buy-put, i.e. a bearish entry) is
        # chased when price ran DOWN past the signal.
        travelled = ext if action == "BUY" else -ext
        if travelled > cap:
            return False, (f"already extended {travelled:.2f} ATR past signal price "
                           f"${signal_price:.2f} (now ${current_price:.2f}, cap {cap:.2f}) "
                           f"— move already happened, entry refused")

    exhausted, why = bar_exhausted(bars, current_price, action, a)
    if exhausted:
        return False, why

    return True, f"not extended (ATR={a:.2f})"
