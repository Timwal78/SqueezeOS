"""
Apex Sonar: Fractal Swarm Siphon v2 — Real-Data Backtest
ScriptMasterLabs | Timothy Walton

Fetches daily OHLCV from Polygon.io (free tier: 5 calls/min, unlimited history).
Set POLYGON_API_KEY in .env or as an environment variable before running.

Usage:
    python backtest_realdata.py
    POLYGON_API_KEY=your_key python backtest_realdata.py
"""
import os, sys, time, json
import urllib.request
import pandas as pd
import numpy as np
from pathlib import Path

# ── Load env from .env file manually (no dotenv dependency) ──────────────────
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

POLYGON_KEY = os.environ.get("POLYGON_API_KEY", "").strip()

if not POLYGON_KEY:
    print("ERROR: POLYGON_API_KEY not set.")
    print("  Option 1: add POLYGON_API_KEY=<key> to your .env file")
    print("  Option 2: POLYGON_API_KEY=<key> python backtest_realdata.py")
    print("\nGet a free key at https://polygon.io (free tier = unlimited history, 5 calls/min)")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────────────
TICKERS    = ["GME", "AMC", "MSTR", "NVDA", "SPY"]
START_DATE = "2021-01-01"
END_DATE   = "2024-12-31"
INIT_CAP   = 100_000
QTY_PCT    = 0.10
COMMISSION = 0.0001
RATE_LIMIT = 13          # seconds between Polygon calls (5 calls/min free tier)

# ── Polygon fetch ─────────────────────────────────────────────────────────────
def fetch_polygon(ticker: str) -> pd.Series:
    """Fetch daily adjusted close from Polygon free tier."""
    url = (
        f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day"
        f"/{START_DATE}/{END_DATE}"
        f"?adjusted=true&sort=asc&limit=50000&apiKey={POLYGON_KEY}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "SML-Backtest/2.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"Polygon {ticker}: HTTP {e.code} — {body[:200]}")

    if data.get("status") not in ("OK", "DELAYED"):
        raise RuntimeError(f"Polygon {ticker}: {data.get('status')} — {data.get('error','')}")

    results = data.get("results", [])
    if not results:
        raise RuntimeError(f"Polygon {ticker}: no data returned for {START_DATE}→{END_DATE}")

    df = pd.DataFrame(results)
    df["date"] = pd.to_datetime(df["t"], unit="ms").dt.normalize()
    df = df.set_index("date").sort_index()
    close = df["c"].rename(ticker)
    print(f"  {ticker:6s}  {len(close):>4d} bars  "
          f"{close.index[0].date()} → {close.index[-1].date()}  "
          f"${close.iloc[0]:.2f} → ${close.iloc[-1]:.2f}")
    return close

# ── EMA helpers ───────────────────────────────────────────────────────────────
def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()

def get_set(close: pd.Series, t, b, v, a):
    et, eb, ev, ea = ema(close, t), ema(close, b), ema(close, v), ema(close, a)
    bull = (et > eb) & (eb > ev) & (ev > ea)
    bear = (et < eb) & (eb < ev) & (ev < ea)
    return bull, bear, et, ea

# ── Signal builder (Tier 2 — backtest-validated) ──────────────────────────────
def build_signals(close: pd.Series):
    bull1, bear1, _, _ = get_set(close, 1,  4,  8,  12)
    bull2, bear2, _, _ = get_set(close, 2,  8, 16,  24)
    bull8, bear8, _, _ = get_set(close, 8, 32, 64,  96)
    bull9, bear9, _, _ = get_set(close, 9, 36, 72, 108)

    micro_bull = bull1 & bull2
    micro_bear = bear1 & bear2
    macro_bull = bull8 & bull9
    macro_bear = bear8 & bear9

    siphon_long  = macro_bear & micro_bull
    siphon_short = macro_bull & micro_bear
    return siphon_long, siphon_short, micro_bull, micro_bear

# ── Backtest engine ───────────────────────────────────────────────────────────
def backtest(close: pd.Series):
    sl, ss, mb, mbe = build_signals(close)
    equity   = INIT_CAP
    position = 0
    entry_px = 0.0
    pos_size = 0.0
    entry_dt = None
    trades   = []
    eq_curve = [equity]
    prices   = close.values
    dates    = close.index

    for i in range(1, len(prices)):
        px = float(prices[i])

        # Exit logic
        if position == 1 and not bool(mb.iloc[i]):
            pnl    = (px - entry_px) / entry_px * pos_size - pos_size * COMMISSION
            equity += pnl
            trades.append({"type": "LONG", "entry_date": entry_dt, "exit_date": dates[i],
                           "entry": entry_px, "exit": px,
                           "pnl_pct": (px - entry_px) / entry_px * 100,
                           "pnl_usd": pnl, "hold": (dates[i] - entry_dt).days})
            position = 0

        elif position == -1 and not bool(mbe.iloc[i]):
            pnl    = (entry_px - px) / entry_px * pos_size - pos_size * COMMISSION
            equity += pnl
            trades.append({"type": "SHORT", "entry_date": entry_dt, "exit_date": dates[i],
                           "entry": entry_px, "exit": px,
                           "pnl_pct": (entry_px - px) / entry_px * 100,
                           "pnl_usd": pnl, "hold": (dates[i] - entry_dt).days})
            position = 0

        # Entry logic
        if bool(sl.iloc[i]) and position != 1:
            position = 1; entry_px = px; entry_dt = dates[i]
            pos_size = equity * QTY_PCT; equity -= pos_size * COMMISSION

        elif bool(ss.iloc[i]) and position != -1:
            position = -1; entry_px = px; entry_dt = dates[i]
            pos_size = equity * QTY_PCT; equity -= pos_size * COMMISSION

        eq_curve.append(equity)

    # Close open position at last bar
    if position != 0:
        px  = float(prices[-1])
        if position == 1:
            pnl = (px - entry_px) / entry_px * pos_size - pos_size * COMMISSION
        else:
            pnl = (entry_px - px) / entry_px * pos_size - pos_size * COMMISSION
        equity += pnl
        trades.append({"type": "LONG" if position == 1 else "SHORT",
                       "entry_date": entry_dt, "exit_date": dates[-1],
                       "entry": entry_px, "exit": px,
                       "pnl_pct": pnl / pos_size * 100,
                       "pnl_usd": pnl, "hold": (dates[-1] - entry_dt).days})

    return equity, trades, np.array(eq_curve)

# ── Stats printer ─────────────────────────────────────────────────────────────
def print_stats(ticker, close, final_equity, trades, eq_curve):
    n = len(trades)
    print(f"\n{'═'*65}")
    print(f"  APEX SONAR SIPHON v2  |  {ticker}  |  {START_DATE} → {END_DATE}")
    print(f"{'═'*65}")
    if n == 0:
        print("  No trades fired — no Siphon events in this period.")
        print(f"{'═'*65}")
        return

    df      = pd.DataFrame(trades)
    wins    = df[df["pnl_usd"] > 0]
    losses  = df[df["pnl_usd"] <= 0]
    wr      = len(wins) / n * 100
    avg_w   = wins["pnl_pct"].mean()   if len(wins)   else 0.0
    avg_l   = losses["pnl_pct"].mean() if len(losses) else 0.0
    rr      = abs(avg_w / avg_l)       if avg_l != 0  else float("inf")
    pf      = (wins["pnl_usd"].sum() / abs(losses["pnl_usd"].sum())
               if len(losses) else float("inf"))
    total_r = (final_equity - INIT_CAP) / INIT_CAP * 100
    bh_r    = (float(close.iloc[-1]) - float(close.iloc[0])) / float(close.iloc[0]) * 100
    peak    = np.maximum.accumulate(eq_curve)
    max_dd  = ((eq_curve - peak) / peak * 100).min()
    avg_h   = df["hold"].mean()
    longs   = len(df[df["type"] == "LONG"])
    shorts  = len(df[df["type"] == "SHORT"])
    best    = df.loc[df["pnl_pct"].idxmax()]
    worst   = df.loc[df["pnl_pct"].idxmin()]

    print(f"  Trades              {n}  ({longs} long / {shorts} short)")
    print(f"  Win Rate            {wr:.1f}%")
    print(f"  Avg Win             +{avg_w:.2f}%")
    print(f"  Avg Loss            {avg_l:.2f}%")
    print(f"  Risk / Reward       {rr:.2f}×")
    print(f"  Profit Factor       {pf:.2f}")
    print(f"  Avg Hold            {avg_h:.1f} days")
    print(f"{'─'*65}")
    print(f"  Net Return          {total_r:+.2f}%   (${final_equity:,.0f})")
    print(f"  Buy & Hold          {bh_r:+.2f}%")
    print(f"  Max Drawdown        {max_dd:.2f}%")
    print(f"{'─'*65}")
    print(f"  Best Trade          +{best['pnl_pct']:.2f}%  "
          f"({best['type']}  {str(best['entry_date'])[:10]})")
    print(f"  Worst Trade         {worst['pnl_pct']:.2f}%  "
          f"({worst['type']}  {str(worst['entry_date'])[:10]})")
    print(f"{'─'*65}")
    print(f"  {'DATE':>12}  {'TYPE':>6}  {'ENTRY':>8}  {'EXIT':>8}  "
          f"{'P&L%':>8}  {'P&L$':>10}  {'DAYS':>5}")
    for _, t in df.iterrows():
        sign = "+" if t["pnl_pct"] >= 0 else ""
        print(f"  {str(t['entry_date'])[:10]:>12}  {t['type']:>6}  "
              f"${t['entry']:>7.2f}  ${t['exit']:>7.2f}  "
              f"{sign}{t['pnl_pct']:>6.2f}%  ${t['pnl_usd']:>+9.0f}  "
              f"{int(t['hold']):>5}")
    print(f"{'═'*65}")

# ── Signal frequency helper ───────────────────────────────────────────────────
def print_signal_freq(ticker, close):
    sl, ss, mb, mbe = build_signals(close)
    total = len(close)
    print(f"\n  Signal Frequency — {ticker}")
    print(f"  Siphon Long  fires: {sl.sum():>4d} bars  ({sl.mean()*100:.1f}%)")
    print(f"  Siphon Short fires: {ss.sum():>4d} bars  ({ss.mean()*100:.1f}%)")
    print(f"  Micro Bull active:  {mb.sum():>4d} bars  ({mb.mean()*100:.1f}%)")
    print(f"  Micro Bear active:  {mbe.sum():>4d} bars  ({mbe.mean()*100:.1f}%)")
    print(f"  Total bars:         {total}")

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print(f"\nAPEX SONAR: Fractal Swarm Siphon v2 — Real-Data Backtest")
    print(f"ScriptMasterLabs | {START_DATE} → {END_DATE}")
    print(f"Capital: ${INIT_CAP:,}  |  Position: {QTY_PCT*100:.0f}%  |  Commission: {COMMISSION*100:.2f}%\n")
    print("Fetching data from Polygon.io...")

    results = []
    for i, ticker in enumerate(TICKERS):
        if i > 0:
            time.sleep(RATE_LIMIT)   # free tier: 5 calls/min
        try:
            close = fetch_polygon(ticker)
            fe, trades, ec = backtest(close)
            print_stats(ticker, close, fe, trades, ec)
            print_signal_freq(ticker, close)
            bh = (float(close.iloc[-1]) - float(close.iloc[0])) / float(close.iloc[0]) * 100
            net = (fe - INIT_CAP) / INIT_CAP * 100
            peak = np.maximum.accumulate(ec)
            dd = ((ec - peak) / peak * 100).min()
            results.append({"ticker": ticker, "trades": len(trades),
                             "net_pct": net, "bh_pct": bh, "max_dd": dd})
        except Exception as e:
            print(f"  SKIP {ticker}: {e}")

    if len(results) > 1:
        print(f"\n{'═'*65}")
        print("  SUMMARY ACROSS ALL TICKERS")
        print(f"{'─'*65}")
        print(f"  {'TICKER':>6}  {'TRADES':>6}  {'NET%':>8}  {'B&H%':>8}  {'MAX DD':>8}")
        for r in results:
            edge = r["net_pct"] - r["bh_pct"]
            print(f"  {r['ticker']:>6}  {r['trades']:>6}  "
                  f"{r['net_pct']:>+7.2f}%  {r['bh_pct']:>+7.2f}%  "
                  f"{r['max_dd']:>7.2f}%   edge: {edge:+.2f}%")
        print(f"{'═'*65}")

if __name__ == "__main__":
    main()
