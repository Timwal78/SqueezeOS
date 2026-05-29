import sys
import os

print("Testing data_providers...")
try:
    from data_providers import load_env_file, DataManager
    print("OK")
except Exception as e:
    print(f"FAIL: {e}")

print("Testing schwab_api...")
try:
    from schwab_api import schwab_api
    print("OK")
except Exception as e:
    print(f"FAIL: {e}")

print("Testing discord_alerts...")
try:
    from discord_alerts import DiscordAlerts
    print("OK")
except Exception as e:
    print(f"FAIL: {e}")

print("Testing options_intelligence...")
try:
    from options_intelligence import OptionsIntelligence
    print("OK")
except Exception as e:
    print(f"FAIL: {e}")

print("Testing forced_move_engine...")
try:
    from forced_move_engine import ForcedMoveEngine
    print("OK")
except Exception as e:
    print(f"FAIL: {e}")

print("Testing iwm_odte_engine...")
try:
    from iwm_odte_engine import IwmOdteEngine
    print("OK")
except Exception as e:
    print(f"FAIL: {e}")

print("Testing sml_engine...")
try:
    from sml_engine import SMLEngine
    print("OK")
except Exception as e:
    print(f"FAIL: {e}")

print("Testing kdp_sentinel_engine...")
try:
    from kdp_sentinel_engine import KdpSentinelEngine
    print("OK")
except Exception as e:
    print(f"FAIL: {e}")
