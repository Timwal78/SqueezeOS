"""
Shadow Ingestion Latency Harness
=================================
Subscribes to Coinbase Exchange's public WebSocket ticker feed, pumps each
live tick into Engine7_Parabolic.analyze(), and records the CPU latency
(perf_counter_ns) from "tick parsed" to "signal computed".

This is a real, measured benchmark — no synthetic numbers. Output is the
empirical histogram for whatever the live market just gave us.

Usage:
    python tools/shadow_ingest.py                  # default: 100 ticks, BTC-USD
    python tools/shadow_ingest.py --ticks 500 --symbol ETH-USD
    python tools/shadow_ingest.py --json results.json
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
import time
from collections import deque
from pathlib import Path
from typing import Deque

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    import websocket  # websocket-client
except ImportError:
    print(
        "ERROR: websocket-client not installed. Run: pip install websocket-client",
        file=sys.stderr,
    )
    sys.exit(1)

from core.engine7_parabolic import Engine7_Parabolic

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("shadow")

COINBASE_WS = "wss://ws-feed.exchange.coinbase.com"
WARMUP_TICKS = 48  # Engine 7 needs >= 48 closes for full matrix


def run_benchmark(symbol: str, target_ticks: int, json_out: str | None) -> int:
    engine = Engine7_Parabolic()
    closes: Deque[float] = deque(maxlen=512)
    latencies_ns: list[int] = []
    exhaustion_events: list[dict] = []

    log.info(f"Connecting to {COINBASE_WS} for {symbol} …")
    ws = websocket.create_connection(COINBASE_WS, timeout=10)
    sub = {
        "type": "subscribe",
        "product_ids": [symbol],
        "channels": ["ticker"],
    }
    ws.send(json.dumps(sub))

    measured = 0
    received = 0
    start_wall = time.time()

    try:
        while measured < target_ticks:
            raw = ws.recv()
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if msg.get("type") != "ticker":
                continue
            price_str = msg.get("price")
            if not price_str:
                continue

            try:
                price = float(price_str)
            except (TypeError, ValueError):
                continue

            received += 1
            closes.append(price)

            if len(closes) < WARMUP_TICKS:
                continue

            t0 = time.perf_counter_ns()
            result = engine.analyze(list(closes), is_singularity=True)
            t1 = time.perf_counter_ns()
            dt = t1 - t0
            latencies_ns.append(dt)
            measured += 1

            sig = result.get("signal")
            if sig == "PARABOLIC_EXHAUSTION_EXIT":
                bands = result.get("_raw_bands", {})
                std_36 = bands.get("std_dev_36", price * 0.02)
                limit = round(price - 1.618 * std_36, 2)
                event = {
                    "tick": measured,
                    "price": price,
                    "limit": limit,
                    "latency_ms": dt / 1e6,
                }
                exhaustion_events.append(event)
                log.warning(
                    f"[SHADOW-EXECUTION] PARABOLIC_EXHAUSTION_EXIT | "
                    f"Price: {price:.2f} | Limit: {limit:.2f} | "
                    f"Latency: {dt/1e6:.4f} ms"
                )

            if measured % 25 == 0:
                log.info(
                    f"  {measured}/{target_ticks} ticks measured "
                    f"(received {received}, last {dt/1e6:.4f} ms)"
                )
    finally:
        try:
            ws.close()
        except Exception:
            pass

    elapsed = time.time() - start_wall

    if not latencies_ns:
        log.error("No ticks measured. Market may be closed or feed silent.")
        return 1

    lat_ms = [n / 1e6 for n in latencies_ns]
    lat_sorted = sorted(lat_ms)
    p99_idx = max(0, int(round(0.99 * (len(lat_sorted) - 1))))

    summary = {
        "symbol": symbol,
        "feed": COINBASE_WS,
        "engine": "Engine7_Parabolic",
        "ticks_measured": len(lat_ms),
        "ticks_received": received,
        "warmup_ticks": WARMUP_TICKS,
        "wall_seconds": round(elapsed, 2),
        "avg_ms": round(statistics.fmean(lat_ms), 4),
        "median_ms": round(statistics.median(lat_ms), 4),
        "min_ms": round(min(lat_ms), 4),
        "max_ms": round(max(lat_ms), 4),
        "p99_ms": round(lat_sorted[p99_idx], 4),
        "exhaustion_events": exhaustion_events,
    }

    log.info(f"--- LATENCY HISTOGRAM ({summary['ticks_measured']} ticks) ---")
    log.info(f"Avg Latency:     {summary['avg_ms']:.4f} ms")
    log.info(f"Median Latency:  {summary['median_ms']:.4f} ms")
    log.info(f"Min Latency:     {summary['min_ms']:.4f} ms")
    log.info(f"Max Latency:     {summary['max_ms']:.4f} ms")
    log.info(f"99th Percentile: {summary['p99_ms']:.4f} ms")
    log.info(f"Exhaustion exits triggered: {len(exhaustion_events)}")

    if json_out:
        Path(json_out).write_text(json.dumps(summary, indent=2))
        log.info(f"Results written to {json_out}")

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Shadow Ingestion Latency Harness")
    ap.add_argument("--symbol", default="BTC-USD", help="Coinbase product id")
    ap.add_argument("--ticks", type=int, default=100, help="ticks to measure after warmup")
    ap.add_argument("--json", dest="json_out", help="write summary JSON to this path")
    args = ap.parse_args()
    return run_benchmark(args.symbol, args.ticks, args.json_out)


if __name__ == "__main__":
    sys.exit(main())
