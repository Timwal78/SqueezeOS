import logging
import sys

# Configure stdout logging to see the output
logging.basicConfig(level=logging.INFO, stream=sys.stdout, format='%(message)s')

from core.nexus402_bridge import notarize_execution

if __name__ == "__main__":
    print("\n--- INITIATING 402PROOF HANDSHAKE TEST ---")
    cert = notarize_execution("GME", "SELL", 1500, 24.50, "APEX_TERMINATED", 1.65)
    
    if cert:
        print("\n[SUCCESS] Handshake complete.")
        print(f"Cert ID: {cert['certificate_id']}")
        print(f"Signature: {cert['signature'][:32]}...")
    else:
        print("\n[FAILED] Handshake failed. Check listener.")
