import os
import sys
import logging
from schwab_api import schwab_api

logging.basicConfig(level=logging.INFO)

def test_refresh():
    print("=== SCHWAB REFRESH TEST ===")
    is_auth = schwab_api._ensure_authenticated()
    print(f"Authenticated: {is_auth}")
    print(f"Access Token Present: {bool(schwab_api.access_token)}")
    print(f"Refresh Token Present: {bool(schwab_api.refresh_token)}")
    if is_auth:
        print("SUCCESS: Schwab session is ONLINE")
        print(f"Token expires at: {schwab_api.token_expires_at}")
    else:
        print("FAILED: Session could not be restored/refreshed.")
        print("Check schwab_tokens.json and .env")

if __name__ == "__main__":
    test_refresh()
