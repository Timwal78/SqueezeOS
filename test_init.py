
import os
import sys
import json
import logging
from server_v5 import init_services, get_service, schwab_api

# Set up logging to console
logging.basicConfig(level=logging.INFO)

print("--- STANDALONE INIT TEST START ---")
try:
    init_services()
    exec_eng = get_service("exec")
    dm = get_service("dm")
    print(f"DM: {dm}")
    print(f"EXEC: {exec_eng}")
    if not exec_eng:
        print("!!! EXEC SERVICE IS NONE !!!")
except Exception as e:
    print(f"!!! CRITICAL FAILURE: {e}")
    import traceback
    traceback.print_exc()
