"""
Apex Sonar: Fractal Swarm Siphon v2 — Fixed + Python Backtest

ROOT CAUSE FIX:
  Original: micro = Sets 1+2+3, macro = Sets 7+8+9
  Problem:  Set 3 anchor = EMA36, Set 9 base = EMA36
            Both conditions required EMA36 to satisfy opposite directions simultaneously
            → signal mathematically impossible

  Fixed:    micro = Sets 1+2 (max anchor EMA24)
            macro = Sets 8+9 (min trigger EMA8)
            No shared EMA levels that conflict.
"""
import pandas as pd
import numpy as np

np.random.seed(42)

# ── Config ────────────────────────────────────────────────────────
INIT_CAPITAL = 100_000
QTY_PCT      = 0.10
COMMISSION   = 0.0001

def ema(s, l):
    return s.ewm(span=l, adjust=False).mean()

def get_alignment(close, t_len, b_len, v_len, a_len):
    t = ema(close, t_len); b = ema(close, b_len)
    v = ema(close, v_len); a = ema(close, a_len)
    bull = (t > b) & (b > v) & (v > a)
    bear = (t < b) & (b < v) & (v < a)
    return bull, bear

def build_signals(close):
    # MICRO — Sets 1 + 2 only (max anchor = EMA24)
    bull1, bear1 = get_alignment(close, 1,  4,  8, 12)
    bull2, bear2 = get_alignment(close, 2,  8, 16, 24)

    # MACRO — Sets 8 + 9 only (min trigger = EMA8, anchors at 96+108)
    bull8, bear8 = get_alignment(close, 8, 32, 64,  96)
    bull9, bear9 = get_alignment(close, 9, 36, 72, 108)

    micro_bull = bull1 & bull2
    micro_bear = bear1 & bear2
    macro_bull = bull8 & bull9
    macro_bear = bear8 & bear9

    siphon_long  = macro_bear & micro_bull   # bear macro + bull micro = sweep detection
    siphon_short = macro_bull & micro_bear   # bull macro + bear micro = trap detection
    return siphon_long, siphon_short, micro_bull, micro_bear

def backtest(close):
    sl, ss, mb, mbe = build_signals(close)
    equity = INIT_CAPITAL
    position = 0; entry_px = 0.0; pos_size = 0.0; entry_date = None
    trades = []; equity_curve = [equity]
    prices = close.values
    dates  = close.index

    for i in range(1, len(prices)):
        px = float(prices[i])

        if position == 1 and not mb.values[i]:
            pnl = (px - entry_px) / entry_px * pos_size - pos_size * COMMISSION
            equity += pnl
            trades.append({"type":"LONG","entry_date":entry_date,"exit_date":dates[i],
                "entry":entry_px,"exit":px,"pnl_pct":(px-entry_px)/entry_px*100,"pnl_usd":pnl,
                "hold":(dates[i]-entry_date).days})
            position = 0

        elif position == -1 and not mbe.values[i]:
            pnl = (entry_px - px) / entry_px * pos_size - pos_size * COMMISSION
            equity += pnl
            trades.append({"type":"SHORT","entry_date":entry_date,"exit_date":dates[i],
                "entry":entry_px,"exit":px,"pnl_pct":(entry_px-px)/entry_px*100,"pnl_usd":pnl,
                "hold":(dates[i]-entry_date).days})
            position = 0

        if sl.values[i] and position != 1:
            position=1; entry_px=px; entry_date=dates[i]
            pos_size=equity*QTY_PCT; equity-=pos_size*COMMISSION

        elif ss.values[i] and position != -1:
            position=-1; entry_px=px; entry_date=dates[i]
            pos_size=equity*QTY_PCT; equity-=pos_size*COMMISSION

        equity_curve.append(equity)

    if position != 0:
        px  = float(prices[-1])
        pnl = ((px-entry_px) if position==1 else (entry_px-px)) / entry_px * pos_size - pos_size*COMMISSION
        equity += pnl
        trades.append({"type":"LONG" if position==1 else "SHORT",
            "entry_date":entry_date,"exit_date":dates[-1],
            "entry":entry_px,"exit":px,"pnl_pct":pnl/pos_size*100,"pnl_usd":pnl,
            "hold":(dates[-1]-entry_date).days})

    return equity, trades, np.array(equity_curve)

def print_stats(label, close, final_equity, trades, equity_curve):
    n = len(trades)
    print(f"\n{'═'*60}")
    print(f"  APEX SONAR SIPHON v2  |  {label}")
    print(f"{'═'*60}")
    if n == 0:
        print("  No trades — signal still not triggering on this scenario.")
        print(f"{'═'*60}")
        return
    df = pd.DataFrame(trades)
    wins    = df[df["pnl_usd"] > 0]
    losses  = df[df["pnl_usd"] <= 0]
    wr      = len(wins) / n * 100
    avg_w   = wins["pnl_pct"].mean()   if len(wins)   else 0
    avg_l   = losses["pnl_pct"].mean() if len(losses) else 0
    rr      = abs(avg_w / avg_l) if avg_l != 0 else float("inf")
    pf      = wins["pnl_usd"].sum() / abs(losses["pnl_usd"].sum()) if len(losses) else float("inf")
    total_r = (final_equity - INIT_CAPITAL) / INIT_CAPITAL * 100
    bh_r    = (float(close.iloc[-1]) - float(close.iloc[0])) / float(close.iloc[0]) * 100
    peak    = np.maximum.accumulate(equity_curve)
    max_dd  = ((equity_curve - peak) / peak * 100).min()
    avg_h   = df["hold"].mean()
    longs   = len(df[df["type"]=="LONG"])
    shorts  = len(df[df["type"]=="SHORT"])
    best    = df.loc[df["pnl_pct"].idxmax()]
    worst   = df.loc[df["pnl_pct"].idxmin()]
    print(f"  Trades              {n}  ({longs} long / {shorts} short)")
    print(f"  Win Rate            {wr:.1f}%")
    print(f"  Avg Win             +{avg_w:.2f}%")
    print(f"  Avg Loss            {avg_l:.2f}%")
    print(f"  Risk / Reward       {rr:.2f}x")
    print(f"  Profit Factor       {pf:.2f}")
    print(f"  Avg Hold            {avg_h:.1f} days")
    print(f"{'─'*60}")
    print(f"  Net Return          {total_r:+.2f}%   (${final_equity:,.0f})")
    print(f"  Buy & Hold          {bh_r:+.2f}%")
    print(f"  Max Drawdown        {max_dd:.2f}%")
    print(f"{'─'*60}")
    print(f"  Best Trade          +{best['pnl_pct']:.2f}%  ({best['type']}  {str(best['entry_date'])[:10]})")
    print(f"  Worst Trade         {worst['pnl_pct']:.2f}%  ({worst['type']}  {str(worst['entry_date'])[:10]})")
    print(f"{'─'*60}")
    print(f"\n  TRADE LOG  (10% equity | 0.01% commission each side)")
    print(f"  {'DATE':>12}  {'TYPE':>6}  {'ENTRY':>8}  {'EXIT':>8}  {'P&L%':>8}  {'P&L$':>10}  {'DAYS':>5}")
    for _, t in df.iterrows():
        sign = "+" if t["pnl_pct"] >= 0 else ""
        print(f"  {str(t['entry_date'])[:10]:>12}  {t['type']:>6}  "
              f"${t['entry']:>7.2f}  ${t['exit']:>7.2f}  "
              f"{sign}{t['pnl_pct']:>6.2f}%  ${t['pnl_usd']:>+9.0f}  {int(t['hold']):>5}")
    print(f"{'═'*60}")

# ── Synthetic scenarios ───────────────────────────────────────────
def make_series(n, start, vol, drift, spikes=None):
    r = np.random.normal(drift/252, vol/np.sqrt(252), n)
    if spikes:
        for bar, mag, days in spikes:
            if bar < n:
                r[bar:bar+days] += mag
                r[bar+days:bar+days+int(days*1.5)] -= mag * 0.4
    prices = start * np.exp(np.cumsum(r))
    dates  = pd.date_range("2022-01-03", periods=n, freq="B")
    return pd.Series(prices, index=dates)

N = 1200

scenarios = [
    ("MEME BEAR + SQUEEZE EVENTS  (AMC/GME-like)",
     make_series(N, 25.0, 0.055, -0.40,
         spikes=[(200,0.07,8),(500,0.09,12),(900,0.06,10)])),

    ("STRONG UPTREND + PULLBACKS  (NVDA-like)",
     make_series(N, 20.0, 0.035, 0.55,
         spikes=[(300,-0.05,6),(700,-0.06,8)])),

    ("CHOP / RANGE  (sideways meme)",
     make_series(N, 10.0, 0.045, 0.00,
         spikes=[(150,0.08,5),(400,-0.07,5),(700,0.06,6),(950,-0.05,4)])),

    ("SLOW GRIND + CRASH  (SPY-like with correction)",
     make_series(N, 400.0, 0.012, 0.10,
         spikes=[(600,-0.035,20)])),
]

for label, close in scenarios:
    fe, trades, ec = backtest(close)
    print_stats(label, close, fe, trades, ec)

# ── Signal frequency on bear+squeeze scenario ─────────────────────
print("\nSIGNAL FREQUENCY  (meme bear + squeeze scenario)")
close_s = scenarios[0][1]
sl, ss, mb, mbe = build_signals(close_s)
macro_bear = ~sl & ~ss  # approximate
print(f"  Siphon Long  fires: {sl.sum()} bars")
print(f"  Siphon Short fires: {ss.sum()} bars")
print(f"  Micro Bull active:  {mb.sum()} bars  ({mb.mean()*100:.1f}%)")
print(f"  Micro Bear active:  {mbe.sum()} bars  ({mbe.mean()*100:.1f}%)")
