# Integrating SqueezeOS with LangChain

This tutorial explains how to connect your LangChain agents to the **SqueezeOS MCP Server**. SqueezeOS uses an HTTP SSE (Server-Sent Events) transport, making it fully compatible with LangChain's standard MCP wrappers.

## Prerequisites
* Python 3.10+
* `langchain` and `langchain-mcp` installed

## Installation
```bash
pip install langchain langchain-mcp httpx
```

## Setup Code

```python
import asyncio
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langchain_mcp import MCPToolkit

async def run_trading_agent():
    # 1. Initialize the SqueezeOS MCP Client via SSE
    toolkit = MCPToolkit.from_sse_url("https://squeezeos-api.onrender.com/mcp")
    
    # 2. Extract tools
    tools = toolkit.get_tools()
    
    # 3. Bind to an LLM
    llm = ChatOpenAI(model="gpt-4o-mini").bind_tools(tools)
    
    # 4. Execute your strategy
    response = await llm.ainvoke([
        HumanMessage(content="Get the AI council verdict for IWM using the SqueezeOS demo tool, then tell me if I should buy.")
    ])
    
    print(response.content)

if __name__ == "__main__":
    asyncio.run(run_trading_agent())
```

## Handling x402 Payments
For premium endpoints (like `/api/council` instead of `/api/demo`), LangChain tools will return an `ERR_PAYMENT_REQUIRED` payload containing a BOLT11/x402 invoice. 

To handle this autonomously, you should attach an `x402_payment_handler` node to your LangGraph workflow that detects the `ERR_PAYMENT_REQUIRED` string, signs the transaction on the XRPL using an attached wallet, and retries the tool call with the resulting JWT. 

For full protocol details, see the [x402 Integration Guide](/docs/tutorials/x402-protocol-integration.md).
