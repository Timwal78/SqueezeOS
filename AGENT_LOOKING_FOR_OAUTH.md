# 🛑 PIVOT: SCHWAB IS DEPRECATED. SWITCH TO TRADIER.

**To: Antigravity (IWM Bridge Agent)**

The Lead Developer has explicitly stated:
`"i dont use schwab aNY MORE I HAVE TRADIER"`

Do not attempt to sync `schwab_tokens.json`. You must tear down the Schwab OAuth flow in the IWM 0DTE Bridge and replace it with the SqueezeOS Tradier integration.
SqueezeOS v5.0 is a Tradier-First Execution Engine. Look at `execution_engine.py` and `tradier_api.py` for reference on how Tradier authentication works (it uses standard Bearer tokens via env vars, no complex OAuth dance required).
