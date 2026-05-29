import sys
import os
import time
import json

# Add the SqueezeOS path to sys.path
sys.path.append(r"C:\Users\timot\.gemini\antigravity\scratch\SqueezeOS")

# We can't easily access the running state of server_v5.py from another script unless we use a socket or file.
# But server_v5.py already has an endpoint /api/beast/iwm_odte.

import requests

try:
    # Try HTTPS (self-signed)
    r = requests.get("https://127.0.0.1:8182/api/beast/iwm_odte", verify=False)
    if r.status_code == 200:
        data = r.json()
        print(json.dumps(data, indent=2))
    else:
        print(f"Error: {r.status_code} - {r.text}")
except Exception as e:
    print(f"Failed to connect to server: {e}")
