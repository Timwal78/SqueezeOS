import requests
import base64
import json
import os

CLIENT_ID = os.environ.get("SCHWAB_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("SCHWAB_CLIENT_SECRET", "")
REDIRECT_URI = "https://127.0.0.1:8183/"
AUTH_CODE = os.environ.get("SCHWAB_AUTH_CODE", "")

def test_exchange():
    print("🚀 TESTING SCHWAB OAUTH EXCHANGE")

    # Validate credentials are configured
    if not CLIENT_ID or not CLIENT_SECRET or not AUTH_CODE:
        print("❌ ERROR: Missing required environment variables:")
        print(f"   SCHWAB_CLIENT_ID: {'✓ set' if CLIENT_ID else '✗ NOT SET'}")
        print(f"   SCHWAB_CLIENT_SECRET: {'✓ set' if CLIENT_SECRET else '✗ NOT SET'}")
        print(f"   SCHWAB_AUTH_CODE: {'✓ set' if AUTH_CODE else '✗ NOT SET'}")
        return

    url = "https://api.schwabapi.com/v1/oauth/token"

    auth_str = f"{CLIENT_ID}:{CLIENT_SECRET}"
    auth_header = base64.b64encode(auth_str.encode()).decode()

    headers = {
        'Authorization': f'Basic {auth_header}',
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    data = {
        'grant_type': 'authorization_code',
        'code': AUTH_CODE,
        'redirect_uri': REDIRECT_URI
    }

    print(f"URL: {url}")
    print(f"Data: {json.dumps(data)}")

    try:
        response = requests.post(url, headers=headers, data=data)
        print(f"Status: {response.status_code}")
        print(f"Headers: {json.dumps(dict(response.headers), indent=2)}")
        print(f"Body: {response.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_exchange()
