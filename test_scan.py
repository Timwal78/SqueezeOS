import requests, json
r = requests.get('http://127.0.0.1:8182/api/market/scan', timeout=10)
d = r.json()
q = d.get('quotes', {})
o = d.get('options', [])
print(f"=== UNIVERSE: {d.get('universe_size',0)} symbols | {len(o)} options picks | Scan #{d.get('scan_count',0)} ===")
print(f"\n--- TOP MOVERS ---")
syms = sorted(q.keys(), key=lambda s: abs(q[s].get('changePct',0)), reverse=True)
for sym in syms[:25]:
    v = q[sym]
    print(f"  {sym:6s} ${v.get('price',0):8.2f}  {v.get('changePct',0):+6.2f}%  Vol:{v.get('volume',0):>12,}  Ratio:{v.get('volRatio',0):5.1f}x")
print(f"\n--- TOP OPTIONS PICKS ---")
for pick in o[:15]:
    print(f"  [{pick['grade']}] {pick['directive']:4s} {pick['symbol']:6s} ${pick['strike']:.1f} {pick['type']:4s} exp:{pick['expiration']} {pick['dte']}DTE  Mid:${pick['mid']:.2f}  Score:{pick['score']}")
    print(f"       >> {pick['explanation'][:120]}")
