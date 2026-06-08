import asyncio
import json
import time
import numpy as np
import websockets
from core.engine7_parabolic import Engine7_Parabolic

class ShadowIngestionEngine:
    def __init__(self, stream_url: str):
        self.stream_url = stream_url
        self.engine = Engine7_Parabolic()
        self.latency_records = []
        self.historical_closes = []

    async def start_ingestion(self):
        async with websockets.connect(self.stream_url) as ws:
            print(f"[SHADOW_INGEST] Connected to live feed: {self.stream_url}")
            
            # Coinbase WebSocket initialization (if fallback is used)
            if "coinbase" in self.stream_url:
                sub_payload = {
                    "type": "subscribe",
                    "product_ids": ["BTC-USD"],
                    "channels": ["ticker"]
                }
                await ws.send(json.dumps(sub_payload))

            while True:
                try:
                    message = await ws.recv()
                    t0 = time.perf_counter_ns()
                    
                    # Fast-parse JSON packet
                    data = json.loads(message)
                    
                    # Support both Binance ('p') and Coinbase ('price') gracefully
                    price_str = data.get('p') or data.get('price')
                    if not price_str:
                        continue
                        
                    price = float(price_str)
                    
                    if price > 0.0:
                        self.historical_closes.append(price)
                        # Keep window bound to avoid unbounded memory accumulation
                        if len(self.historical_closes) > 1000:
                            self.historical_closes.pop(0)
                        
                        # Process state update in Engine 7
                        self.engine.analyze(self.historical_closes, is_singularity=True)
                        
                    t1 = time.perf_counter_ns()
                    latency_ms = (t1 - t0) / 1_000_000.0
                    self.latency_records.append(latency_ms)
                    
                    # Batch calculate profile metrics every 100 ticks
                    if len(self.latency_records) >= 100:
                        self.log_performance_metrics()
                        
                except Exception as e:
                    print(f"[SHADOW_INGEST] Error processing live stream: {e}")
                    break

    def log_performance_metrics(self):
        metrics = np.array(self.latency_records)
        p99 = np.percentile(metrics, 99)
        avg_lat = np.mean(metrics)
        max_lat = np.max(metrics)
        min_lat = np.min(metrics)
        
        print(f"\n--- LATENCY PERFORMANCE METRICS (100 TICK BATCH) ---")
        print(f"P99 Latency:      {p99:.4f} ms")
        print(f"Average Latency:  {avg_lat:.4f} ms")
        print(f"Max Latency:      {max_lat:.4f} ms")
        print(f"Min Latency:      {min_lat:.4f} ms")
        print(f"----------------------------------------------------\n")
        
        # Reset sample array for next batch profiling
        self.latency_records = []
