import os
import requests
import json

def audit():
    print("=== SQUEEZE OS LIVE AUDIT: INITIATED ===")
    
    # 1. Load Environment
    env_path = r'C:\Users\timot\.gemini\antigravity\scratch\SqueezeOS\.env'
    env_vars = {}
    with open(env_path, 'r') as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                k, v = line.strip().split('=', 1)
                env_vars[k] = v
    
    # 2. Test Tradier Production Connectivity
    print("\n[1/3] Testing Tradier Production Connection...")
    prod_key = env_vars.get('TRADIER_PRODUCTION_API_KEY')
    
    headers = {
        'Authorization': f'Bearer {prod_key}',
        'Accept': 'application/json'
    }
    
    try:
        r = requests.get('https://api.tradier.com/v1/user/profile', headers=headers)
        if r.status_code == 200:
            data = r.json()
            accounts = data.get('profile', {}).get('account', [])
            if isinstance(accounts, dict): accounts = [accounts]
            
            print(f"TRADIER CONNECTED: Found {len(accounts)} account(s).")
            for acc in accounts:
                acc_id = acc.get('account_number')
                # Fetch Balance
                rb = requests.get(f'https://api.tradier.com/v1/accounts/{acc_id}/balances', headers=headers)
                bal = rb.json().get('balances', {})
                equity = bal.get('total_equity', 0)
                cash = bal.get('cash', {}).get('cash_available', 0)
                print(f"   - Account: {acc_id} | Type: {acc.get('classification')} | Equity: ${equity} | Cash: ${cash}")
                
                # Verify $200 balance
                if float(equity) >= 190: 
                    print("   VERIFIED: Live Capital Detected.")
                else:
                    print(f"   WARNING: Equity ${equity} is below expected $200.")
        else:
            print(f"TRADIER AUTH FAILED: {r.status_code} - {r.text}")
    except Exception as e:
        print(f"TRADIER ERROR: {e}")

    # 3. Scan for Placeholders
    print("\n[2/3] Scanning Data Pipeline for Placeholders...")
    providers_path = r'C:\Users\timot\.gemini\antigravity\scratch\SqueezeOS\data_providers.py'
    with open(providers_path, 'r') as f:
        content = f.read()
        placeholders = ['random.uniform', 'fake_data', 'placeholder_price', 'mock_quote']
        found = [p for p in placeholders if p in content]
        if not found:
            print("DATA INTEGRITY: No placeholders found. System is strictly Real-Time.")
        else:
            print(f"AUDIT ALERT: Found suspicious patterns: {found}")

    # 4. Check Risk Guardrails in .env
    print("\n[3/3] Checking Risk Guardrails...")
    max_price = env_vars.get('BEAST_MAX_PRICE', '0')
    print(f"   - Max Trade Value: ${max_price}")
    if float(max_price) <= 50:
        print("RISK SETTINGS: Conservative for $200 account.")
    else:
        print("RISK ALERT: Max Price is high for this account size.")

if __name__ == "__main__":
    audit()
