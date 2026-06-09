import asyncio
import time
from core.shadow_ingestion import ShadowIngestionEngine

async def run_trial(duration_seconds: int):
    # Attempting Binance first (will fall back to Coinbase if HTTP 451 Geo-Block occurs)
    url = "wss://stream.binance.com:9443/ws/btcusdt@aggTrade"
    
    print(f"[TRIAL] Attempting to connect to Binance stream for {duration_seconds // 60} minutes...")
    engine = ShadowIngestionEngine(stream_url=url)
    task = asyncio.create_task(engine.start_ingestion())
    
    # Let it attempt to connect
    await asyncio.sleep(2)
    
    if task.done():
        # Connection failed (most likely HTTP 451 Unavailable for Legal Reasons)
        print("[TRIAL] Binance connection rejected. Falling back to Coinbase Pro...")
        fallback_url = "wss://ws-feed.exchange.coinbase.com"
        engine = ShadowIngestionEngine(stream_url=fallback_url)
        task = asyncio.create_task(engine.start_ingestion())

    await asyncio.sleep(duration_seconds)
    task.cancel()
    print(f"[TRIAL] {duration_seconds // 60}-minute benchmark completed successfully.")

if __name__ == "__main__":
    try:
        # Run the continuous 10-minute trial
        asyncio.run(run_trial(600))
    except KeyboardInterrupt:
        print("\n[TRIAL] Aborted by user.")
