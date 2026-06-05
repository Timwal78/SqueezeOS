"""
Apex Sonar: Fractal Swarm Siphon — Python Backtest
Uses synthetic GBM price data calibrated to meme stock volatility.
"""
import pandas as pd
import numpy as np

np.random.seed(42)

# ── Config ────────────────────────────────────────────────────────
INIT_CAPITAL = 100_000
QTY_PCT      = 0.10
COMMISSION   = 0.0001
N_BARS       = 1000         # ~4 years daily bars

# ── Synthetic meme stock price generator ─────────────────────────
def make_price_series(n, start_price, daily_vol, drift, regime_changes=True):
    """GBM with occasional volatility regime shifts to mimic meme behavior."""
    log_returns = np.random.normal(drift / 252, daily_vol / np.sqrt(252), n)
    # Inject 3 squeeze-like events
    for spike in [150, 380, 720]:
        if spike < n:
            log_returns[spike:spike+5]   += np.random.uniform(0.04, 0.08, 5)
            log_returns[spike+5:spike+15] -= np.random.uniform(0.02, 0.04, 10)
    prices = start_price * np.exp(np.cumsum(log_returns))
    dates  = pd.date_range("2022-01-03", periods=n, freq="B")
    return pd.Series(prices, index=dates)

# ── EMA (matches Pine Script ta.ema) ──────────────────────────────
def ema(series, length):
    return series.ewm(span=length, adjust=False).mean()

# ── Alignment ─────────────────────────────────────────────────────
def get_alignment(close, t_len, b_len, v_len, a_len):
    t = ema(close, t_len)
    b = ema(close, b_len)
    v = ema(close, v_len)
    a = ema(close, a_len)
    bull = (t > b) & (b > v) & (v > a)
    bear = (t < b) & (b < v) & (v < a)
    return bull, bear

# ── Signals ───────────────────────────────────────────────────────
def build_signals(close):
    bull1, bear1 = get_alignment(close, 1,  4,  8,  12)
    bull2, bear2 = get_alignment(close, 2,  8, 16,  24)
    bull3, bear3 = get_alignment(close, 3, 12, 24,  36)
    bull7, bear7 = get_alignment(close, 7, 28, 56,  84)
    bull8, bear8 = get_alignment(close, 8, 32, 64,  96)
    bull9, bear9 = get_alignment(close, 9, 36, 72, 108)

    micro_bull = bull1 & bull2 & bull3
    micro_bear = bear1 & bear2 & bear3
    macro_bull = bull7 & bull8 & bull9
    macro_bear = bear7 & bear8 & bear9

    siphon_long  = macro_bear & micro_bull
    siphon_short = macro_bull & micro_bear
    return siphon_long, siphon_short, micro_bull, micro_bear

# ── Backtest engine ───────────────────────────────────────────────
def backtest(close):
    sl, ss, mb, mbe = build_signals(close)

    equity       = INIT_CAPITAL
    position     = 0
    entry_px     = 0.0
    pos_size     = 0.0
    entry_date   = None
    trades       = []
    equity_curve = [equity]

    prices = close.values
    sl_v   = sl.values
    ss_v   = ss.values
    mb_v   = mb.values
    mbe_v  = mbe.values
    dates  = close.index

    for i in range(1, len(prices)):
        px = float(prices[i])

        # ── Exits ─────────────────────────────────────────────────
        if position == 1 and not mb_v[i]:
            pnl = (px - entry_px) / entry_px * pos_size - pos_size * COMMISSION
            equity += pnl
            trades.append({"type":"LONG","entry_date":entry_date,
                "exit_date":dates[i],"entry":entry_px,"exit":px,
                "pnl_pct":(px-entry_px)/entry_px*100,"pnl_usd":pnl})
            position = 0

        elif position == -1 and not mbe_v[i]:
            pnl = (entry_px - px) / entry_px * pos_size - pos_size * COMMISSION
            equity += pnl
            trades.append({"type":"SHORT","entry_date":entry_date,
                "exit_date":dates[i],"entry":entry_px,"exit":px,
                "pnl_pct":(entry_px-px)/entry_px*100,"pnl_usd":pnl})
            position = 0

        # ── Entries ───────────────────────────────────────────────
        if sl_v[i] and position != 1:
            position   = 1
            entry_px   = px
            entry_date = dates[i]
            pos_size   = equity * QTY_PCT
            equity    -= pos_size * COMMISSION

        elif ss_v[i] and position != -1:
            position   = -1
            entry_px   = px
            entry_date = dates[i]
            pos_size   = equity * QTY_PCT
            equity    -= pos_size * COMMISSION

        equity_curve.append(equity)

    # Force-close open position at last bar
    if position != 0:
        px  = float(prices[-1])
        pnl = ((px - entry_px) if position == 1 else (entry_px - px)) / entry_px * pos_size
        pnl -= pos_size * COMMISSION
        equity += pnl
        trades.append({"type":"LONG" if position==1 else "SHORT",
            "entry_date":entry_date,"exit_date":dates[-1],
            "entry":entry_px,"exit":px,
            "pnl_pct":pnl/pos_size*100,"pnl_usd":pnl})

    return equity, trades, np.array(equity_curve)

# ── Stats printer ─────────────────────────────────────────────────
def print_stats(label, close, final_equity, trades, equity_curve):
    n = len(trades)
    print(f"\n{'═'*58}")
    print(f"  APEX SONAR SIPHON  |  {label}")
    print(f"{'═'*58}")

    if n == 0:
        print("  NO TRADES FIRED — signal never triggered on this data.")
        print(f"{'═'*58}")
        return

    df       = pd.DataFrame(trades)
    wins     = df[df["pnl_usd"] > 0]
    losses   = df[df["pnl_usd"] <= 0]
    win_rate = len(wins) / n * 100
    avg_win  = wins["pnl_pct"].mean()   if len(wins)   else 0
    avg_loss = losses["pnl_pct"].mean() if len(losses) else 0
    rr       = abs(avg_win / avg_loss)  if avg_loss != 0 else float("inf")
    prof_fac = wins["pnl_usd"].sum() / abs(losses["pnl_usd"].sum()) if len(losses) else float("inf")

    total_ret = (final_equity - INIT_CAPITAL) / INIT_CAPITAL * 100
    bh_ret    = (float(close.iloc[-1]) - float(close.iloc[0])) / float(close.iloc[0]) * 100

    peak  = np.maximum.accumulate(equity_curve)
    dd    = (equity_curve - peak) / peak * 100
    max_dd = dd.min()

    df["hold"] = (pd.to_datetime(df["exit_date"]) - pd.to_datetime(df["entry_date"])).dt.days
    avg_hold   = df["hold"].mean()

    longs  = df[df["type"]=="LONG"]
    shorts = df[df["type"]=="SHORT"]
    best   = df.loc[df["pnl_pct"].idxmax()]
    worst  = df.loc[df["pnl_pct"].idxmin()]

    print(f"  Trades              {n}  ({len(longs)} long / {len(shorts)} short)")
    print(f"  Win Rate            {win_rate:.1f}%")
    print(f"  Avg Win             +{avg_win:.2f}%")
    print(f"  Avg Loss            {avg_loss:.2f}%")
    print(f"  Risk / Reward       {rr:.2f}x")
    print(f"  Profit Factor       {prof_fac:.2f}")
    print(f"  Avg Hold            {avg_hold:.1f} days")
    print(f"{'─'*58}")
    print(f"  Net Return          {total_ret:+.2f}%   (${final_equity:,.0f})")
    print(f"  Buy & Hold          {bh_ret:+.2f}%")
    print(f"  Max Drawdown        {max_dd:.2f}%")
    print(f"{'─'*58}")
    print(f"  Best Trade          +{best['pnl_pct']:.2f}%  "
          f"({best['type']}  {str(best['entry_date'])[:10]})")
    print(f"  Worst Trade         {worst['pnl_pct']:.2f}%  "
          f"({worst['type']}  {str(worst['entry_date'])[:10]})")
    print(f"{'─'*58}")
    print(f"\n  TRADE LOG  (10% equity per trade | 0.01% commission)")
    print(f"  {'ENTRY DATE':>12}  {'TYPE':>6}  {'ENTRY':>8}  {'EXIT':>8}  "
          f"{'P&L %':>8}  {'P&L $':>10}  {'HOLD':>5}")
    for _, t in df.iterrows():
        sign = "+" if t["pnl_pct"] >= 0 else ""
        print(f"  {str(t['entry_date'])[:10]:>12}  {t['type']:>6}  "
              f"${t['entry']:>7.2f}  ${t['exit']:>7.2f}  "
              f"{sign}{t['pnl_pct']:>6.2f}%  "
              f"${t['pnl_usd']:>+9.0f}  {int(t['hold']):>4}d")
    print(f"{'═'*58}\n")

# ── Scenarios ─────────────────────────────────────────────────────
scenarios = [
    ("MEME BULL RUN  (high vol, strong uptrend)",
     make_price_series(N_BARS, 10.0,  daily_vol=0.055, drift=0.40)),
    ("MEME BEAR BLEED  (high vol, downtrend)",
     make_price_series(N_BARS, 25.0,  daily_vol=0.055, drift=-0.35)),
    ("CHOP / SIDEWAYS  (med vol, no trend)",
     make_price_series(N_BARS, 15.0,  daily_vol=0.030, drift=0.00)),
    ("LOW VOL TREND  (SPY-like, slow grind up)",
     make_price_series(N_BARS, 400.0, daily_vol=0.012, drift=0.12)),
]

for label, close in scenarios:
    final_equity, trades, equity_curve = backtest(close)
    print_stats(label, close, final_equity, trades, equity_curve)

# ── Signal frequency analysis ─────────────────────────────────────
print("SIGNAL FREQUENCY ANALYSIS (meme bull run scenario)")
close_sample = scenarios[0][1]
sl, ss, mb, mbe = build_signals(close_sample)
print(f"  Siphon Long  signals: {sl.sum()} / {len(sl)} bars  ({sl.mean()*100:.2f}%)")
print(f"  Siphon Short signals: {ss.sum()} / {len(ss)} bars  ({ss.mean()*100:.2f}%)")
print(f"  Micro Bull   active:  {mb.sum()} / {len(mb)} bars  ({mb.mean()*100:.1f}%)")
print(f"  Macro Bear   active:  {(~sl & ~ss & mb).sum()} bars macro-bear only")
print()
