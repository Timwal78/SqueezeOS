"""
Gamma Ramp Desk — QuantConnect LEAN backtest (real historical option prices)
=============================================================================
Faithful port of tools/gamma_ramp/edge_stack.py's gate logic and
tools/gamma_ramp/live_engine.py's exact exit ladder, running against LEAN's
real historical option chain data (free in QuantConnect's cloud research/
backtest environment — no separate paid data subscription needed for this).

WHY THIS EXISTS: the only backtest evidence for Gamma Ramp so far
(tools/gamma_ramp/backtest_intraday_directional.py, see
docs/GAMMA_RAMP_BACKTEST_2026-07-29.md) tested the DIRECTIONAL signal on the
underlying's own price move, not real option premium -- it explicitly
disclosed that leverage, theta decay, and bid-ask spread were never modeled.
That's a real gap: a strategy can have real directional edge and still lose
money on options (or vice versa) once actual premium economics are priced
in. This algorithm closes that gap using LEAN's real option chain data.

STATUS: written against LEAN's documented Python API as of this writing, but
NEVER RUN -- this sandbox has no LEAN runtime or QuantConnect API access.
Paste this into a new QuantConnect Algorithm Lab Python project and run the
cloud backtest; do not assume it is bug-free until it actually compiles and
runs there. Report back what QC's compiler/backtest engine says.

WHAT'S FAITHFULLY PORTED from edge_stack.py (canonical thresholds, unchanged):
  - RVOL_ENTRY=1.35, RVOL_ENTRY_FULL=1.80
  - Z_ENTRY=1.50, Z_FULL=2.00, Z_WIN=20 (log-return z-score)
  - VPIN_ENTRY=0.28, VPIN_WIN=10 (daily VPIN proxy from bar range position)
  - DELTA_MIN/MAX=0.30/0.40, DELTA_TARGET=0.35
  - MIN_GATES_LONG=4 of 5 core gates (short_gamma, rvol, zscore, vpin, flow_align)
  - short_gamma proxy: RVOL elevated + realized-vol above its own 40-day median
    (same daily proxy edge_stack.py itself uses when no live chain GEX exists --
    the ORIGINAL live engine uses real Tradier chain GEX instead; LEAN's options
    universe here doesn't expose dealer GEX directly, so this backtest uses the
    SAME proxy edge_stack.py already falls back to, not a new invented one)

WHAT'S FAITHFULLY PORTED from live_engine.py's manage_open() exit ladder:
  - HARD_STOP=-20%, SCALE_TP=+50% (sell half), SCALE2_TP=+150% (sell half of
    remainder), BANK_RUNNER_AT=+300% (sell all but 1 lottery contract)
  - GIVEBACK_LOCK_ARM=+50%, GIVEBACK_FRAC=35% (exit if peak gain >=50% and
    current gives back >=35% of that peak, or drops to breakeven/red)
  - RUNNER_TRAIL=22% / RUNNER_TRAIL_LATE=18% (after scale2)
  - DELTA_EXIT=0.60 (MM hedge slowing -- exit if contract delta expands past
    this while up >=50%)
  - TARGET_HI=500% hard cap

WHAT IS NOT PORTED (structural LEAN differences, disclosed not hidden):
  - No live Tradier chain GEX -- uses the RV/RVOL proxy (see above)
  - VPIN uses LEAN's daily TradeBar OHLCV, same bar-range-position proxy as
    edge_stack.py's own vpin_proxy_series() -- not real tick-level VSPIN
  - Position sizing is fixed at 1 contract per entry (matches the live
    executor's ROBINHOOD_OPTION_QTY=1 default) -- no account-equity scaling
"""
from AlgorithmImports import *
from collections import deque
import numpy as np


# ── Canonical thresholds -- copied verbatim from tools/gamma_ramp/edge_stack.py ──
RVOL_ENTRY = 1.35
RVOL_ENTRY_FULL = 1.80
Z_ENTRY = 1.50
Z_FULL = 2.00
Z_WIN = 20
VPIN_ENTRY = 0.28
VPIN_WIN = 10
DELTA_MIN = 0.30
DELTA_MAX = 0.40
DELTA_TARGET = 0.35
DELTA_EXIT = 0.60
MIN_GATES_LONG = 4

# ── Exit ladder -- copied verbatim from tools/gamma_ramp/live_engine.py ──
HARD_STOP = -0.20
SCALE_TP = 0.50
SCALE2_TP = 1.50
BANK_RUNNER_AT = 3.00
RUNNER_TRAIL = 0.22
RUNNER_TRAIL_LATE = 0.18
GIVEBACK_LOCK_ARM = 0.50
GIVEBACK_FRAC = 0.35
TARGET_HI = 5.00

RV_WIN = 10
RV_MEDIAN_WIN = 40
DTE_MIN = 7
DTE_MAX = 21


class GammaRampDesk(QCAlgorithm):
    """
    Real-option-premium backtest of the Gamma Ramp 0.30-0.40 delta MM
    forced-move strategy. Same symbol basket as the directional backtest in
    docs/GAMMA_RAMP_BACKTEST_2026-07-29.md for a direct comparison.
    """

    def Initialize(self):
        self.SetStartDate(2024, 1, 1)
        self.SetEndDate(2026, 7, 29)
        self.SetCash(25000)

        self.symbols = ["SPY", "QQQ", "IWM", "NVDA", "TSLA"]
        self.bars = {}       # ticker -> deque of (o,h,l,c,v)
        self.option_symbol = {}  # ticker -> canonical option Symbol
        self.positions = {}  # ticker -> dict tracking the open contract position

        for ticker in self.symbols:
            equity = self.AddEquity(ticker, Resolution.Daily)
            equity.SetDataNormalizationMode(DataNormalizationMode.Adjusted)

            option = self.AddOption(ticker, Resolution.Daily)
            option.SetFilter(self._option_filter)
            self.option_symbol[ticker] = option.Symbol

            self.bars[ticker] = deque(maxlen=RV_MEDIAN_WIN + Z_WIN + 5)
            self.positions[ticker] = None

        self.SetWarmUp(RV_MEDIAN_WIN + Z_WIN + 5, Resolution.Daily)

    def _option_filter(self, universe):
        # 0.30-0.40 delta, both calls and puts, 7-21 DTE -- matches the
        # "HV equity swing" window from edge_stack.py's CONTRACT WINDOW gate.
        return universe.Delta(DELTA_MIN, DELTA_MAX).Expiration(DTE_MIN, DTE_MAX)

    def OnData(self, slice: Slice):
        for ticker in self.symbols:
            equity_symbol = self.Securities[ticker].Symbol
            if not slice.Bars.ContainsKey(equity_symbol):
                continue
            bar = slice.Bars[equity_symbol]
            self.bars[ticker].append((bar.Open, bar.High, bar.Low, bar.Close, bar.Volume))

            if self.positions[ticker] is not None:
                self._manage_open(ticker, slice)
                continue  # one position at a time per symbol, matches live_engine.py

            if self.IsWarmingUp or len(self.bars[ticker]) < RV_MEDIAN_WIN + Z_WIN:
                continue

            self._check_entry(ticker, slice)

    # ── Gate evaluation -- port of edge_stack.evaluate_edge() ──────────────
    def _check_entry(self, ticker, slice: Slice):
        arr = np.array(self.bars[ticker])
        opens, highs, lows, closes, volumes = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4]
        i = len(closes) - 1

        rvol = self._rvol_at(volumes, i)
        z = self._zscore_at(closes, i)
        vp, sf = self._vpin_at(highs, lows, closes, volumes, i)
        rv = self._realized_vol_at(closes, i)
        rv_hist = self._realized_vol_series(closes)
        short_gamma = self._short_gamma_proxy(i, rvol, rv, rv_hist)

        gates = {
            "short_gamma": short_gamma,
            "rvol": (not np.isnan(rvol)) and rvol >= RVOL_ENTRY,
            "zscore": (not np.isnan(z)) and abs(z) >= Z_ENTRY,
            "vpin": (not np.isnan(vp)) and vp >= VPIN_ENTRY,
        }

        bull = (not np.isnan(z) and z >= Z_ENTRY) and (np.isnan(sf) or sf > 0.05)
        bear = (not np.isnan(z) and z <= -Z_ENTRY) and (np.isnan(sf) or sf < -0.05)
        if not np.isnan(z) and not np.isnan(sf):
            if z >= Z_FULL and sf >= 0:
                bull = True
            if z <= -Z_FULL and sf <= 0:
                bear = True
            if z >= Z_ENTRY and sf < -0.15:
                bull = False
            if z <= -Z_ENTRY and sf > 0.15:
                bear = False

        if bull and not bear:
            side, gates["flow_align"] = "CALL", (np.isnan(sf) or sf > 0.0)
        elif bear and not bull:
            side, gates["flow_align"] = "PUT", (np.isnan(sf) or sf < 0.0)
        else:
            side, gates["flow_align"] = "NONE", False

        passed = sum(1 for k in ("short_gamma", "rvol", "zscore", "vpin", "flow_align") if gates.get(k))
        if side == "NONE" or passed < MIN_GATES_LONG or not gates["short_gamma"] or not gates["rvol"]:
            return

        self._enter_position(ticker, side, slice)

    def _enter_position(self, ticker, side, slice: Slice):
        chain = slice.OptionChains.get(self.option_symbol[ticker])
        if chain is None or len(chain) == 0:
            return
        right = OptionRight.Call if side == "CALL" else OptionRight.Put
        candidates = [c for c in chain if c.Right == right]
        if not candidates:
            return
        # nearest to the 0.35 target delta within the already-filtered 0.30-0.40 band
        best = min(candidates, key=lambda c: abs(abs(c.Greeks.Delta) - DELTA_TARGET))
        if best.AskPrice <= 0:
            return

        qty = 1
        self.MarketOrder(best.Symbol, qty)
        self.positions[ticker] = {
            "contract": best.Symbol,
            "side": side,
            "entry_price": best.AskPrice,
            "qty": qty,
            "remaining": qty,
            "scaled": False,
            "scale_frac": 0.0,
            "peak_ret": 0.0,
        }
        self.Debug(f"{self.Time} ENTER {ticker} {side} {best.Symbol} delta={best.Greeks.Delta:.2f} premium={best.AskPrice:.2f}")

    # ── Exit ladder -- port of live_engine.manage_open() ───────────────────
    def _manage_open(self, ticker, slice: Slice):
        pos = self.positions[ticker]
        chain = slice.OptionChains.get(self.option_symbol[ticker])
        if chain is None:
            return
        contract = next((c for c in chain if c.Symbol == pos["contract"]), None)
        if contract is None or contract.BidPrice <= 0:
            return  # contract expired/no quote -- LEAN will auto-expire/settle it

        mid = (contract.BidPrice + contract.AskPrice) / 2.0
        ret = (mid - pos["entry_price"]) / pos["entry_price"]
        pos["peak_ret"] = max(pos["peak_ret"], ret)

        exit_qty, reason = 0, None

        if ret <= HARD_STOP:
            exit_qty, reason = pos["remaining"], "hard_stop"
        elif ret >= TARGET_HI:
            exit_qty, reason = pos["remaining"], "target_500"
        elif (not pos["scaled"]) and ret >= SCALE_TP:
            exit_qty = max(1, pos["remaining"] // 2)
            pos["scaled"], pos["scale_frac"] = True, 0.5
            reason = "scale_1"
        elif pos["scaled"] and pos["scale_frac"] < 0.75 and ret >= SCALE2_TP:
            exit_qty = max(1, pos["remaining"] // 2)
            pos["scale_frac"] = 0.75
            reason = "scale_2"
        elif pos["scaled"] and ret >= BANK_RUNNER_AT and pos["remaining"] > 1:
            exit_qty, reason = pos["remaining"] - 1, "bank_300"
        elif pos["peak_ret"] >= GIVEBACK_LOCK_ARM and pos["peak_ret"] > 0:
            frac_lost = (pos["peak_ret"] - ret) / pos["peak_ret"] if pos["peak_ret"] > 0 else 0
            if frac_lost >= GIVEBACK_FRAC and ret > 0:
                exit_qty, reason = pos["remaining"], "giveback_lock"
            elif ret <= 0:
                exit_qty, reason = pos["remaining"], "giveback_to_red"
        if reason is None and pos["scaled"]:
            trail = RUNNER_TRAIL_LATE if pos["scale_frac"] >= 0.75 else RUNNER_TRAIL
            if (pos["peak_ret"] - ret) >= trail and pos["peak_ret"] > 0:
                exit_qty, reason = pos["remaining"], "trail"
        if reason is None:
            delta = abs(contract.Greeks.Delta)
            if delta >= DELTA_EXIT and ret >= 0.50:
                exit_qty, reason = pos["remaining"], "delta_expansion"

        if exit_qty > 0:
            self.MarketOrder(pos["contract"], -exit_qty)
            pos["remaining"] -= exit_qty
            self.Debug(f"{self.Time} EXIT {ticker} {reason} ret={ret:+.2%} qty={exit_qty} remaining={pos['remaining']}")
            if pos["remaining"] <= 0 or reason not in ("scale_1", "scale_2", "bank_300"):
                self.positions[ticker] = None

    # ── edge_stack.py math helpers, ported verbatim ─────────────────────────
    def _rvol_at(self, volumes, i, win=20):
        if i < win:
            return float("nan")
        base = float(np.mean(volumes[i - win:i]))
        return float(volumes[i] / base) if base > 0 else float("nan")

    def _zscore_at(self, closes, i, win=Z_WIN):
        if i < win + 1:
            return float("nan")
        rets = np.diff(np.log(closes[i - win:i + 1]))
        if len(rets) < win:
            return float("nan")
        mu = float(np.mean(rets[:-1])) if len(rets) > 1 else 0.0
        sig = float(np.std(rets[:-1])) if len(rets) > 1 else 0.0
        if sig < 1e-12:
            return 0.0
        return float((rets[-1] - mu) / sig)

    def _vpin_at(self, highs, lows, closes, volumes, i, win=VPIN_WIN):
        if i < win:
            return float("nan"), float("nan")
        buy, sell = [], []
        for j in range(i - win + 1, i + 1):
            h, l, c, v = highs[j], lows[j], closes[j], volumes[j]
            rng = h - l
            if rng <= 1e-12 or v <= 0:
                buy.append(v * 0.5)
                sell.append(v * 0.5)
                continue
            frac = min(1.0, max(0.0, (c - l) / rng))
            buy.append(v * frac)
            sell.append(v * (1.0 - frac))
        b, s = sum(buy), sum(sell)
        tot = b + s
        if tot <= 0:
            return float("nan"), float("nan")
        return abs(b - s) / tot, (b - s) / tot

    def _realized_vol_at(self, closes, i, win=RV_WIN):
        if i < win:
            return float("nan")
        rets = np.diff(np.log(closes[i - win + 1:i + 1]))
        if len(rets) < 2:
            return float("nan")
        return float(np.std(rets) * np.sqrt(252))

    def _realized_vol_series(self, closes):
        return np.array([self._realized_vol_at(closes, k) for k in range(len(closes))])

    def _short_gamma_proxy(self, i, rvol, rv, rv_hist):
        if i < 5 or np.isnan(rvol) or np.isnan(rv) or rvol < RVOL_ENTRY:
            return False
        hist = rv_hist[max(0, i - 40):i]
        hist = hist[~np.isnan(hist)]
        if len(hist) < 10:
            return False
        return rv >= float(np.median(hist)) * 1.05
