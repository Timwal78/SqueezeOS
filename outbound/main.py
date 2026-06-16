"""
Outbound Hunter — entry point for the Render worker service.
Runs the Registry Broadcaster and Agent-to-Agent Hustler in parallel threads.
"""

import os
import sys
import time
import logging
import threading

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("outbound-main")

# Add repo root to path so we can import dotenv / env helpers
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv(override=False)
except ImportError:
    pass


def _run_broadcaster():
    from outbound.broadcaster import run_broadcaster
    run_broadcaster()


def _run_hustler():
    # Stagger the hustler by 30 minutes so both workers don't hammer GitHub at the same time
    initial_delay = int(os.getenv("HUSTLE_INITIAL_DELAY_SECONDS", "1800"))
    logger.info(f"Hustler initial delay: {initial_delay}s")
    time.sleep(initial_delay)
    from outbound.hustler import run_hustler
    run_hustler()


if __name__ == "__main__":
    logger.info("SML Outbound Hunter starting")

    broadcaster_thread = threading.Thread(target=_run_broadcaster, name="broadcaster", daemon=False)
    hustler_thread     = threading.Thread(target=_run_hustler,     name="hustler",     daemon=False)

    broadcaster_thread.start()
    hustler_thread.start()

    broadcaster_thread.join()
    hustler_thread.join()
