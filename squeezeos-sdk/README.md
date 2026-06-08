# SqueezeOS Python SDK

The official Python client for SqueezeOS — Institutional Grade Options Flow, Gamma Regimes, and Base-4 Fractal Convergence API.

## Installation
```bash
pip install squeezeos
```

## Authentication

SqueezeOS supports two forms of authentication:
1. **API Keys (Humans)**: Purchase an API key at [https://squeezeos-api.onrender.com/pricing](https://squeezeos-api.onrender.com/pricing).
2. **ECHOLOCK-402 (Autonomous Agents)**: SqueezeOS natively supports L402 protocol payments via the XRPL for autonomous AI agents. No API key required.

### 1. Using an API Key

```python
from squeezeos import SqueezeOSClient
import os

os.environ["SQUEEZEOS_API_KEY"] = "sml_live_..."

client = SqueezeOSClient()
response = client.analyze(ticker="SPY")
print(response)
```

### 2. Autonomous Agent Mode (Pay-per-call)

If your agent is fully autonomous, simply provide an XRPL testnet wallet seed. When SqueezeOS challenges the request with a `402 Payment Required`, the SDK will automatically negotiate the transaction, pay the RLUSD fee on the XRPL ledger, and retrieve the data.

```python
from squeezeos import SqueezeOSClient
import os

# Provide your agent's XRPL wallet seed
os.environ["SQUEEZEOS_AGENT_WALLET"] = "sEd..."

client = SqueezeOSClient()
# Will automatically pay the microtransaction fee and return the data
response = client.options_flow(ticker="GME")
print(response)
```

## Available Endpoints
- `client.analyze("TICKER")`: Run the 5-engine proprietary convergence matrix.
- `client.options_flow("TICKER")`: Get institutional options anomalies and gamma squeeze setups.
- `client.convergence_scan()`: Scan the entire market for high-probability setups.
