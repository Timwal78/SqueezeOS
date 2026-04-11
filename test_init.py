import sys
import os
import logging

# Add current directory to path
sys.path.append(os.getcwd())

from server_v5 import init_services, _services

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    print("Testing SqueezeOS Service Initialization...")
    try:
        init_services()
        print("Services initialized successfully.")
        for name, service in _services.items():
            print(f"Service '{name}' is active: {service is not None}")
    except Exception as e:
        print(f"FAILED to initialize services: {e}")
        import traceback
        traceback.print_exc()
