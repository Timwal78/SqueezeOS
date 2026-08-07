# SML Institutional Live Desk v6

Professional multi-module institutional chart system — **not** a 90-line toy.

Built for the capability class shown on 24/7 live crypto chart streams (structure,
liquidity, order blocks, FVGs, premium/discount, flow, adaptive bands, confluence
entries). **Original Script Master Labs implementation** — not a clone of BigBeluga
or any closed TradingView script.

## Deliverables

| File | Role |
|------|------|
| `indicators/SML_Institutional_Live_Desk_v6.pine` | Full Pine v6 overlay desk |
| `tools/institutional_live_desk/institutional_live_desk.py` | OHLCV multi-asset scanner (parity confluence) |
| `tools/institutional_live_desk/README.md` | This file |

## Modules (Pine)

1. **Market Structure** — swing pivots, BOS, CHoCH, protected high/low  
2. **Order Blocks** — impulse OB boxes with mitigation  
3. **Fair Value Gaps** — 3-candle imbalances, fill kill  
4. **Premium / Discount / EQ** — active swing range geometry  
5. **Liquidity Map** — equal H/L + sweep markers  
6. **Flow + Regime** — volume-weighted flow, ADX via `ta.dmi` (no `ta.adx`)  
7. **Adaptive Bands** — EMA basis ± ATR  
8. **Confluence Engine** — scored LONG/SHORT (0–10) + ATR stop/target rails  
9. **Operator HUD** — bright table (bias, zone, scores, levels)  
10. **Alerts** — `alertcondition` + JSON-ish `alert()` webhook strings  

## TradingView install

1. Open TradingView → Pine Editor  
2. New indicator → paste full `.pine` source  
3. Add to chart (BTCUSDT / ETHUSDT / SOLUSDT / ES / NQ / IWM …)  
4. Create alerts from ILD Long / ILD Short / structure / sweep  

### Recommended defaults

- Crypto 15m–1H or 4H swing  
- `Min confluence score` = 5–6 for cleaner signals (default 4)  
- `Swing pivot length` = 5 (tighten to 3 on fast scalps)  
- Paper only until you validate on your symbols  

## Python scanner

```bash
cd tools/institutional_live_desk
python3 institutional_live_desk.py demo
python3 institutional_live_desk.py scan --csv /path/to/ohlcv.csv --symbol BTCUSDT --min-score 5
```

CSV headers: `timestamp,open,high,low,close,volume`

## Disclosures

- Educational / research. **Not financial advice. Not auto-broker execution.**  
- OHLCV structure proxies ≠ true order book / footprint / tick delta.  
- Pine cannot stream a third-party vendor’s proprietary closed source — this is
  an original SML desk in the same *problem class* as live multi-indicator charts.  
- Confirm all signals on closed bars (`barstate.isconfirmed`).  

## Owner

Script Master Labs, LLC · SDVOSB  
https://www.scriptmasterlabs.com  
