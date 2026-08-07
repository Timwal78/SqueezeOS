#!/usr/bin/env python3
"""SML Institutional Live Desk — multi-asset OHLCV companion scanner.

Mirrors the Pine confluence logic on CSV/OHLCV frames for BTC/ETH/SOL (or any
symbol). Educational research tool — not broker execution.

Usage:
  python institutional_live_desk.py scan --csv btc.csv --symbol BTCUSDT
  python institutional_live_desk.py scan --csv eth.csv --min-score 5
  python institutional_live_desk.py demo   # synthetic walk-forward smoke

CSV columns required: timestamp,open,high,low,close,volume
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple


# ── indicators ──────────────────────────────────────────────────────────────

def ema(xs: Sequence[float], n: int) -> List[float]:
    if not xs:
        return []
    k = 2.0 / (n + 1.0)
    out = [xs[0]]
    for v in xs[1:]:
        out.append(v * k + out[-1] * (1.0 - k))
    return out


def sma(xs: Sequence[float], n: int) -> List[float]:
    out: List[float] = []
    s = 0.0
    for i, v in enumerate(xs):
        s += v
        if i >= n:
            s -= xs[i - n]
        if i + 1 >= n:
            out.append(s / n)
        else:
            out.append(s / (i + 1))
    return out


def rma(xs: Sequence[float], n: int) -> List[float]:
    """Wilder RMA (used by ATR / DMI)."""
    if not xs:
        return []
    out = [xs[0]]
    alpha = 1.0 / n
    for v in xs[1:]:
        out.append(out[-1] * (1.0 - alpha) + v * alpha)
    return out


def atr(high: Sequence[float], low: Sequence[float], close: Sequence[float], n: int = 14) -> List[float]:
    trs: List[float] = []
    for i in range(len(close)):
        if i == 0:
            trs.append(high[i] - low[i])
        else:
            trs.append(max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1])))
    return rma(trs, n)


def dmi_adx(
    high: Sequence[float], low: Sequence[float], close: Sequence[float], di_len: int = 14, adx_len: int = 14
) -> Tuple[List[float], List[float], List[float]]:
    n = len(close)
    up = [0.0] * n
    dn = [0.0] * n
    for i in range(1, n):
        up_move = high[i] - high[i - 1]
        dn_move = low[i - 1] - low[i]
        up[i] = up_move if up_move > dn_move and up_move > 0 else 0.0
        dn[i] = dn_move if dn_move > up_move and dn_move > 0 else 0.0
    tr = atr(high, low, close, di_len)
    up_r = rma(up, di_len)
    dn_r = rma(dn, di_len)
    plus_di: List[float] = []
    minus_di: List[float] = []
    dx: List[float] = []
    for i in range(n):
        t = tr[i] if tr[i] != 0 else 1e-12
        p = 100.0 * up_r[i] / t
        m = 100.0 * dn_r[i] / t
        plus_di.append(p)
        minus_di.append(m)
        denom = p + m
        dx.append(100.0 * abs(p - m) / denom if denom else 0.0)
    adx = rma(dx, adx_len)
    return plus_di, minus_di, adx


def pivots(high: Sequence[float], low: Sequence[float], left: int, right: int) -> Tuple[List[Optional[float]], List[Optional[float]]]:
    n = len(high)
    ph: List[Optional[float]] = [None] * n
    pl: List[Optional[float]] = [None] * n
    for i in range(left, n - right):
        window_h = high[i - left : i + right + 1]
        window_l = low[i - left : i + right + 1]
        if high[i] == max(window_h) and window_h.count(high[i]) == 1:
            ph[i + right] = high[i]  # confirm on right bar (TV-like lag)
        if low[i] == min(window_l) and window_l.count(low[i]) == 1:
            pl[i + right] = low[i]
    return ph, pl


# ── bar model ──────────────────────────────────────────────────────────────

@dataclass
class Bar:
    ts: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Signal:
    ts: str
    symbol: str
    side: str
    close: float
    score: int
    stop: float
    target: float
    bias: str
    zone: str
    adx: float
    reason: str


def load_csv(path: Path) -> List[Bar]:
    rows: List[Bar] = []
    with path.open(newline="") as f:
        r = csv.DictReader(f)
        # normalize headers
        def g(d, *keys):
            for k in keys:
                for kk in d:
                    if kk.lower().strip() == k:
                        return d[kk]
            raise KeyError(keys)

        for d in r:
            rows.append(
                Bar(
                    ts=str(g(d, "timestamp", "time", "date", "datetime")),
                    open=float(g(d, "open")),
                    high=float(g(d, "high")),
                    low=float(g(d, "low")),
                    close=float(g(d, "close")),
                    volume=float(g(d, "volume", "vol")),
                )
            )
    return rows


# ── engine (parity with Pine confluence) ────────────────────────────────────

@dataclass
class EngineConfig:
    swing_len: int = 5
    di_len: int = 14
    adx_len: int = 14
    adx_trend: float = 22.0
    flow_len: int = 14
    vol_ma_len: int = 20
    band_len: int = 20
    band_mult: float = 2.0
    min_score: int = 4
    rr: float = 2.0
    stop_atr: float = 1.5
    cooldown: int = 5
    pd_lookback: int = 50


def scan(bars: Sequence[Bar], symbol: str, cfg: EngineConfig) -> List[Signal]:
    if len(bars) < 60:
        return []
    o = [b.open for b in bars]
    h = [b.high for b in bars]
    l = [b.low for b in bars]
    c = [b.close for b in bars]
    v = [b.volume for b in bars]
    n = len(bars)

    atr_s = atr(h, l, c, 14)
    di_p, di_m, adx = dmi_adx(h, l, c, cfg.di_len, cfg.adx_len)
    basis = ema(c, cfg.band_len)
    upper = [basis[i] + cfg.band_mult * atr_s[i] for i in range(n)]
    lower = [basis[i] - cfg.band_mult * atr_s[i] for i in range(n)]

    signed = []
    for i in range(n):
        br = max(h[i] - l[i], 1e-12)
        signed.append(v[i] * ((c[i] - l[i]) - (h[i] - c[i])) / br)
    flow = ema(signed, cfg.flow_len)
    vol_ma = sma(v, cfg.vol_ma_len)

    ph, pl = pivots(h, l, cfg.swing_len, cfg.swing_len)

    last_sh: Optional[float] = None
    last_sl: Optional[float] = None
    struct_dir = 0
    last_sig_i = -10_000
    signals: List[Signal] = []

    for i in range(n):
        if ph[i] is not None:
            last_sh = ph[i]
        if pl[i] is not None:
            last_sl = pl[i]

        bos_up = bos_dn = choch_up = choch_dn = False
        if last_sh is not None and last_sl is not None and i > 0:
            if c[i] > last_sh and c[i - 1] <= last_sh:
                if struct_dir == 1:
                    bos_up = True
                elif struct_dir <= 0:
                    choch_up = True
                struct_dir = 1
            if c[i] < last_sl and c[i - 1] >= last_sl:
                if struct_dir == -1:
                    bos_dn = True
                elif struct_dir >= 0:
                    choch_dn = True
                struct_dir = -1

        swing_hi = last_sh if last_sh is not None else max(h[max(0, i - cfg.pd_lookback) : i + 1])
        swing_lo = last_sl if last_sl is not None else min(l[max(0, i - cfg.pd_lookback) : i + 1])
        eq = 0.5 * (swing_hi + swing_lo)
        in_prem = c[i] > eq
        in_disc = c[i] < eq

        is_trend = adx[i] >= cfg.adx_trend
        flow_bull = flow[i] > 0
        flow_bear = flow[i] < 0
        vol_spike = v[i] > vol_ma[i] * 1.5
        over_up = c[i] > upper[i]
        over_dn = c[i] < lower[i]

        sweep_h = last_sh is not None and h[i] > last_sh and c[i] < last_sh and vol_spike
        sweep_l = last_sl is not None and l[i] < last_sl and c[i] > last_sl and vol_spike

        long_s = 0
        short_s = 0
        reasons: List[str] = []

        if struct_dir == 1:
            long_s += 2
            reasons.append("bull_struct")
        if struct_dir == -1:
            short_s += 2
            reasons.append("bear_struct")
        if bos_up or choch_up:
            long_s += 1
        if bos_dn or choch_dn:
            short_s += 1
        if in_disc:
            long_s += 2
        if in_prem:
            short_s += 2
        if is_trend and flow_bull and di_p[i] > di_m[i]:
            long_s += 2
            reasons.append("trend_flow+")
        if is_trend and flow_bear and di_m[i] > di_p[i]:
            short_s += 2
            reasons.append("trend_flow-")
        if not is_trend:
            if over_dn:
                long_s += 1
            if over_up:
                short_s += 1
        if sweep_l:
            long_s += 2
            reasons.append("sweep_low")
        if sweep_h:
            short_s += 2
            reasons.append("sweep_high")
        if vol_spike and c[i] > o[i]:
            long_s += 1
        if vol_spike and c[i] < o[i]:
            short_s += 1

        long_s = min(10, long_s)
        short_s = min(10, short_s)
        cooled = (i - last_sig_i) >= cfg.cooldown

        long_setup = cooled and long_s >= cfg.min_score and long_s >= short_s and c[i] > o[i]
        short_setup = cooled and short_s >= cfg.min_score and short_s > long_s and c[i] < o[i]
        if long_setup and short_setup:
            if long_s > short_s:
                short_setup = False
            else:
                long_setup = False

        zone = "PREMIUM" if in_prem else "DISCOUNT" if in_disc else "EQ"
        bias = "BULL" if struct_dir == 1 else "BEAR" if struct_dir == -1 else "INIT"
        a = atr_s[i] if atr_s[i] > 0 else 1e-12

        if long_setup:
            last_sig_i = i
            signals.append(
                Signal(
                    ts=bars[i].ts,
                    symbol=symbol,
                    side="LONG",
                    close=c[i],
                    score=long_s,
                    stop=c[i] - cfg.stop_atr * a,
                    target=c[i] + cfg.stop_atr * a * cfg.rr,
                    bias=bias,
                    zone=zone,
                    adx=adx[i],
                    reason=",".join(reasons) or "confluence",
                )
            )
        elif short_setup:
            last_sig_i = i
            signals.append(
                Signal(
                    ts=bars[i].ts,
                    symbol=symbol,
                    side="SHORT",
                    close=c[i],
                    score=short_s,
                    stop=c[i] + cfg.stop_atr * a,
                    target=c[i] - cfg.stop_atr * a * cfg.rr,
                    bias=bias,
                    zone=zone,
                    adx=adx[i],
                    reason=",".join(reasons) or "confluence",
                )
            )
    return signals


def demo_bars(n: int = 400) -> List[Bar]:
    """Synthetic trending + mean-revert series for smoke tests."""
    bars: List[Bar] = []
    px = 100.0
    import random

    random.seed(42)
    for i in range(n):
        # regime switch
        drift = 0.15 if i < 200 else (-0.12 if i < 320 else 0.08)
        shock = random.uniform(-1.2, 1.2)
        o = px
        c = max(1.0, px + drift + shock)
        hi = max(o, c) + random.uniform(0.1, 0.8)
        lo = min(o, c) - random.uniform(0.1, 0.8)
        vol = 1000 + random.uniform(0, 800) + (500 if abs(shock) > 0.9 else 0)
        bars.append(Bar(ts=str(i), open=o, high=hi, low=lo, close=c, volume=vol))
        px = c
    return bars


def cmd_scan(args: argparse.Namespace) -> int:
    cfg = EngineConfig(min_score=args.min_score, rr=args.rr, stop_atr=args.stop_atr, cooldown=args.cooldown)
    bars = load_csv(Path(args.csv))
    sigs = scan(bars, args.symbol, cfg)
    if args.json:
        print(json.dumps([asdict(s) for s in sigs], indent=2))
    else:
        print(f"symbol={args.symbol} bars={len(bars)} signals={len(sigs)} min_score={cfg.min_score}")
        for s in sigs[-args.tail :]:
            print(
                f"{s.ts} {s.side:5} px={s.close:.4f} score={s.score} "
                f"stop={s.stop:.4f} tgt={s.target:.4f} {s.bias}/{s.zone} adx={s.adx:.1f} {s.reason}"
            )
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    cfg = EngineConfig(min_score=args.min_score)
    bars = demo_bars(args.bars)
    sigs = scan(bars, "DEMO", cfg)
    print(f"DEMO bars={len(bars)} signals={len(sigs)}")
    # basic sanity: engine runs, scores in range, stops on correct side
    assert len(bars) == args.bars
    for s in sigs:
        assert 1 <= s.score <= 10
        if s.side == "LONG":
            assert s.stop < s.close < s.target
        else:
            assert s.target < s.close < s.stop
    print("SMOKE_OK", f"last={asdict(sigs[-1]) if sigs else None}")
    if args.json:
        print(json.dumps([asdict(s) for s in sigs[-10:]], indent=2))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="SML Institutional Live Desk scanner")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="Scan OHLCV CSV")
    s.add_argument("--csv", required=True)
    s.add_argument("--symbol", default="SYM")
    s.add_argument("--min-score", type=int, default=4)
    s.add_argument("--rr", type=float, default=2.0)
    s.add_argument("--stop-atr", type=float, default=1.5)
    s.add_argument("--cooldown", type=int, default=5)
    s.add_argument("--tail", type=int, default=30)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_scan)

    d = sub.add_parser("demo", help="Synthetic smoke test")
    d.add_argument("--bars", type=int, default=400)
    d.add_argument("--min-score", type=int, default=4)
    d.add_argument("--json", action="store_true")
    d.set_defaults(func=cmd_demo)

    args = p.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
