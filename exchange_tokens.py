import os
import json
import base64
import requests
import time
from datetime import datetime

CLIENT_ID = "cOb3GLiEmhfxGyfWUsDVaqqYayNUTVuCexRIzRbSumWvz5I6"
CLIENT_SECRET = "Uyn7D7MRvYE2TQ88jHNLLiC79p9RH3qB73OJaAEw1A3ElDm5QtgBwSR5Ei1uNX6I"
REDIRECT_URI = "https://127.0.0.1:8182/"
AUTH_CODE = "C0.b2F1dGgyLmJkYy5zY2h3YWIuY29t.w5YDXN_Jx6QIk5SJctBBlokctJFQl1_W-Gn9OaGH_gU%40"

def exchange():
    print(f"📡 Attempting manual exchange for code: {AUTH_CODE[:10]}...")
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
    
    response = requests.post(url, headers=headers, data=data)
    if response.status_code == 200:
        token_data = response.json()
        
        # Save to schwab_tokens.json
        token_file = 'schwab_tokens.json'
        expires_in = token_data.get('expires_in', 1800)
        tokens = {
            'access_token': token_data.get('access_token'),
            'refresh_token': token_data.get('refresh_token'),
            'expires_at': time.time() + expires_in,
            'updated_at': datetime.now().isoformat()
        }
        
        with open(token_file, 'w') as f:
            json.dump(tokens, f, indent=4)
        
        print("✅ SUCCESS: Tokens saved to schwab_tokens.json")
        return True
    else:
        print(f"❌ ERROR: {response.status_code} - {response.text}")
        return False

if __name__ == "__main__":
    exchange()
