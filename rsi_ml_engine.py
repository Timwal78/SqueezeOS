"""
SML RSI Multi Length PRO Engine — Python port of the pasted "SML RSI Multi
Length PRO [Beast Mode]" Pine script (CC BY-NC-SA 4.0, core logic credited to
LuxAlgo, upgraded by ScriptMasterLabs). NOT YET SAVED to indicators/ — see
docs/AETHER_RSI_ML_BACKTEST_2026-07-25.md for the licensing note (NonCommercial
clause) that needs a decision before this goes anywhere near a paid product
or live execution.

Computes, per bar, a multi-length adaptive RSI (RMA-based, lengths min_len..
max_len, default 14-35) averaged into avg_rsi, plus adaptive buy/sell RSI
bands and an EMA signal line. Trading signal: CALL (long) on avg_rsi crossing
above sig_line, PUT (flat/short-proxy) on avg_rsi crossing below it — mirrors
the Pine script's cross_up/cross_dn exactly.

This script's own alertcondition() calls are explicitly titled "(Watchlist)"
— it has no SqueezeOS webhook payload and is not wired to any executor.
"""
from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass
class RsiMlParams:
    min_len: int = 14
    max_len: int = 35
    overbought: float = 70.0
    oversold: float = 30.0
    sig_len: int = 21

    @classmethod
    def from_env(cls) -> "RsiMlParams":
        return cls(
            min_len=int(os.environ.get("RSIML_MIN_LEN", "14")),
            max_len=int(os.environ.get("RSIML_MAX_LEN", "35")),
            sig_len=int(os.environ.get("RSIML_SIG_LEN", "21")),
        )


def _bar_val(bar: dict, *keys, default=0.0) -> float:
    for k in keys:
        v = bar.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return default


def compute_series(bars: list, p: RsiMlParams = None) -> dict:
    p = p or RsiMlParams.from_env()
    n = len(bars)
    closes = [_bar_val(b, "close", "c") for b in bars]
    lengths = list(range(p.min_len, p.max_len + 1))
    N = len(lengths)

    num_rma = [0.0] * N
    den_rma = [0.0] * N

    avg_rsi = [0.0] * n
    overbuy_frac = [0.0] * n
    oversell_frac = [0.0] * n

    for i in range(n):
        diff = closes[i] - closes[i - 1] if i > 0 else 0.0
        total = 0.0
        ob_count = 0
        os_count = 0
        for k, length in enumerate(lengths):
            alpha = 1.0 / length
            num_rma[k] = alpha * diff + (1 - alpha) * num_rma[k]
            den_rma[k] = alpha * abs(diff) + (1 - alpha) * den_rma[k]
            rsi = 50 * num_rma[k] / den_rma[k] + 50 if den_rma[k] != 0 else 50.0
            total += rsi
            if rsi > p.overbought:
                ob_count += 1
            if rsi < p.oversold:
                os_count += 1
        avg_rsi[i] = total / N
        overbuy_frac[i] = ob_count / N
        oversell_frac[i] = os_count / N

    buy_rsi_ma = [0.0] * n
    sell_rsi_ma = [0.0] * n
    for i in range(n):
        prev_buy = buy_rsi_ma[i - 1] if i > 0 else avg_rsi[i]
        prev_sell = sell_rsi_ma[i - 1] if i > 0 else avg_rsi[i]
        buy_rsi_ma[i] = prev_buy + overbuy_frac[i] * (avg_rsi[i] - prev_buy)
        sell_rsi_ma[i] = prev_sell + oversell_frac[i] * (avg_rsi[i] - prev_sell)

    # EMA signal line over avg_rsi
    k_ema = 2.0 / (p.sig_len + 1)
    sig_line = [avg_rsi[0]]
    for v in avg_rsi[1:]:
        sig_line.append(v * k_ema + sig_line[-1] * (1 - k_ema))

    cross_up = [False] * n
    cross_dn = [False] * n
    for i in range(1, n):
        cross_up[i] = avg_rsi[i - 1] <= sig_line[i - 1] and avg_rsi[i] > sig_line[i]
        cross_dn[i] = avg_rsi[i - 1] >= sig_line[i - 1] and avg_rsi[i] < sig_line[i]

    return {
        "avg_rsi": avg_rsi, "sig_line": sig_line,
        "buy_rsi_ma": buy_rsi_ma, "sell_rsi_ma": sell_rsi_ma,
        "cross_up": cross_up, "cross_dn": cross_dn,
    }


def analyze(symbol: str, bars: list, p: RsiMlParams = None) -> dict:
    p = p or RsiMlParams.from_env()
    min_bars = p.max_len + p.sig_len + 5
    if not bars or len(bars) < min_bars:
        return {"symbol": symbol.upper(), "status": "insufficient_data",
                "bars": len(bars or []), "min_bars": min_bars}
    out = compute_series(bars, p)
    last = len(bars) - 1
    signal = "CALL" if out["cross_up"][last] else "PUT" if out["cross_dn"][last] else None
    return {
        "symbol": symbol.upper(), "status": "success",
        "price": _bar_val(bars[-1], "close", "c"),
        "signal": signal,
        "avg_rsi": round(out["avg_rsi"][last], 2),
        "sig_line": round(out["sig_line"][last], 2),
    }
