import sys
import logging
logging.basicConfig(level=logging.DEBUG)
from core.app import app
from core.convergence_engine import scan_beastmode_universe
from core.legacy import get_service

def test_scan():
    with app.app_context():
        # Actually core/app.py might not start the services unless we call init.
        # But let's just see if get_service("dm") returns anything.
        dm = get_service("dm")
        if dm is None:
            # Maybe the services are attached to the app or we need to start the background scanner
            print("DM is None. The background thread handles dm.")
            return

if __name__ == "__main__":
    test_scan()
