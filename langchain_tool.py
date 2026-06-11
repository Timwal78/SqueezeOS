"""
squeezeos_langchain.py — ScriptMasterLabs SqueezeOS LangChain Tool

Wraps the SqueezeOS x402 API as a LangChain tool for use in LangChain/LangGraph agents.

Install:
    pip install langchain-core requests xrpl-py

Usage:
    from squeezeos_langchain import SqueezeOSToolkit
    toolkit = SqueezeOSToolkit(xrpl_seed="your_seed", xrpl_wallet="your_address")
    tools = toolkit.get_tools()
    # Use in LangChain agent
    agent = create_react_agent(llm, tools)
"""
from __future__ import annotations
import os
import json
import requests
from typing import Optional
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

BASE_URL = "https://squeezeos-api.onrender.com"
PROOF_URL = "https://four02proof.onrender.com"
RLUSD_ISSUER = "rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De"


def _pay_x402(endpoint_id: str, xrpl_seed: str, xrpl_wallet: str, amount_drops: int = 10000) -> str:
    """Pay for an x402-gated endpoint. Returns JWT access token."""
    # Step 1: Get invoice
    inv = requests.post(f"{PROOF_URL}/v1/invoice", json={"endpoint_id": endpoint_id}, timeout=15).json()
    if "error" in inv:
        raise ValueError(f"Invoice error: {inv['error']}")

    # Step 2: Pay on XRPL via xrpl-py
    from xrpl.clients import JsonRpcClient
    from xrpl.wallet import Wallet
    from xrpl.models.transactions import Payment
    from xrpl.models.amounts import IssuedCurrencyAmount
    from xrpl.transaction import submit_and_wait

    client = JsonRpcClient("https://xrplcluster.com")
    wallet = Wallet.from_seed(xrpl_seed)
    tx = Payment(
        account=wallet.address,
        destination=inv["pay_to"],
        amount=IssuedCurrencyAmount(currency="RLUSD", issuer=RLUSD_ISSUER, value=str(inv["amount"])),
        memos=[{"memo": {"memo_data": inv["memo_hex"]}}]
    )
    result = submit_and_wait(tx, client, wallet)
    tx_hash = result.result["hash"]

    # Step 3: Verify and get token
    token_resp = requests.post(f"{PROOF_URL}/v1/verify",
        json={"invoice_id": inv["invoice_id"], "tx_hash": tx_hash, "agent_wallet": xrpl_wallet},
        timeout=15).json()
    return token_resp.get("access_token", "")


class SqueezeOSInput(BaseModel):
    symbol: str = Field(description="Stock symbol e.g. GME, AMC, IWM, SPY")


class SqueezeOSOracleInput(BaseModel):
    symbol: str = Field(description="Stock symbol")
    xrpl_seed: Optional[str] = Field(default=None, description="XRPL wallet seed for x402 payment")
    xrpl_wallet: Optional[str] = Field(default=None, description="XRPL wallet address")


class OracleEngineTool(BaseTool):
    """Get institutional BUY/SELL/HOLD/SHIELD signal for a stock via x402 payment."""
    name: str = "oracle_engine_signal"
    description: str = (
        "Get an institutional-grade BUY/SELL/HOLD/SHIELD directive for a stock symbol. "
        "Aggregates GammaFlow, MMLE, Fractal, and Proprietary EMA engines. "
        "Cost: 0.25 USDC via x402. Symbols: GME, AMC, IWM, SPY, QQQ, NVDA, TSLA."
    )
    args_schema: type = SqueezeOSInput
    xrpl_seed: Optional[str] = None
    xrpl_wallet: Optional[str] = None

    def _run(self, symbol: str) -> str:
        headers = {}
        if self.xrpl_seed and self.xrpl_wallet:
            try:
                token = _pay_x402("oracle-engine", self.xrpl_seed, self.xrpl_wallet)
                headers["X-Payment-Token"] = token
            except Exception as e:
                return f"Payment error: {e}"
        r = requests.get(f"{BASE_URL}/api/engine/signal/{symbol.upper()}", headers=headers, timeout=20)
        if r.status_code == 402:
            return f"Payment required. Use x402 flow: POST {PROOF_URL}/v1/invoice with endpoint_id=oracle-engine"
        return json.dumps(r.json(), indent=2)


class CouncilVerdictTool(BaseTool):
    """Get institutional BUY/SELL/HOLD council verdict with full thesis."""
    name: str = "council_verdict"
    description: str = (
        "Get institutional BUY/SELL/HOLD verdict with full analytical thesis. "
        "Returns driver analysis, navigator risk, and MMLE regime. "
        "Cost: 0.05 RLUSD via x402."
    )
    args_schema: type = SqueezeOSInput

    def _run(self, symbol: str) -> str:
        r = requests.post(f"{BASE_URL}/api/council",
            json={"symbol": symbol.upper()}, timeout=20)
        if r.status_code == 402:
            return f"Payment required — use /v1/invoice to get XRPL payment terms"
        return json.dumps(r.json(), indent=2)


class FTDOracleTool(BaseTool):
    """Query SEC Reg SHO Fails-To-Deliver data for squeeze detection."""
    name: str = "ftd_oracle"
    description: str = (
        "Get SEC Reg SHO Fails-To-Deliver time series for a stock symbol. "
        "Use for short squeeze detection and compliance monitoring. "
        "Cost: 0.02 RLUSD via x402."
    )
    args_schema: type = SqueezeOSInput

    def _run(self, symbol: str) -> str:
        # Check threshold list first (free)
        thresh = requests.get(f"{BASE_URL}/api/ftd/threshold/{symbol.upper()}", timeout=10).json()
        # Then get series (paid)
        r = requests.get(f"{BASE_URL}/api/ftd/series/{symbol.upper()}", timeout=20)
        if r.status_code == 402:
            return f"Threshold status: {thresh}\nFTD series requires payment — use /v1/invoice"
        return json.dumps({"threshold": thresh, "series": r.json()}, indent=2)


class AgentBureauTool(BaseTool):
    """Check FICO-style credit score for an XRPL agent wallet."""
    name: str = "agent_credit_bureau"
    description: str = (
        "Get FICO-style credit score (300-850) for an XRPL agent wallet address. "
        "Free public score teaser. Full report costs 0.01 RLUSD. "
        "Grades: A (750+), B (650-749), C (550-649), D (<550)."
    )
    class _Input(BaseModel):
        wallet: str = Field(description="XRPL wallet address e.g. rUJhaK2ibfTFVdAn8m9jMCcJQ1xo6FmNPZ")
    args_schema: type = _Input

    def _run(self, wallet: str) -> str:
        r = requests.get(f"{PROOF_URL}/v1/bureau/score/{wallet}", timeout=15)
        return json.dumps(r.json(), indent=2)


class SqueezeOSToolkit:
    """Full SqueezeOS LangChain toolkit."""
    def __init__(self, xrpl_seed: str = None, xrpl_wallet: str = None):
        self.xrpl_seed = xrpl_seed or os.getenv("XRPL_SEED")
        self.xrpl_wallet = xrpl_wallet or os.getenv("XRPL_WALLET")

    def get_tools(self) -> list:
        return [
            OracleEngineTool(xrpl_seed=self.xrpl_seed, xrpl_wallet=self.xrpl_wallet),
            CouncilVerdictTool(),
            FTDOracleTool(),
            AgentBureauTool(),
        ]


if __name__ == "__main__":
    # Demo — no payment needed for free endpoints
    toolkit = SqueezeOSToolkit()
    tools = toolkit.get_tools()
    print(f"SqueezeOS tools loaded: {[t.name for t in tools]}")
    # Test free bureau score
    result = tools[3]._run("rUJhaK2ibfTFVdAn8m9jMCcJQ1xo6FmNPZ")
    print("Bureau score:", result[:200])
