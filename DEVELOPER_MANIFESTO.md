# SQUEEZE OS: DEVELOPER MANIFESTO

## THE PRIME DIRECTIVE: ZERO DEMO / 100% FETCH

This document serves as the "Main Memory" for every agent and developer working on SqueezeOS. The following rules are absolute and must be followed without exception.

### 1. NO DEMO DATA
- **NO** hardcoded lists of tickers (other than user-defined favorites).
- **NO** placeholder values in the UI or Backend.
- **NO** "offline" fallbacks that simulate market activity.
- If data isn't there, the system must show "Awaiting Data" or a real-time error, NEVER a fake list.

### 2. 100% FETCH POLICY
- **NO** arbitrary `.slice()` calls in the frontend. Display the full depth of the data feed.
- **NO** top-N limits in discovery loops (e.g., `[:50]`, `[:20]`). Let the engine handle the full volume.
- **NO** artificial price floors (e.g., "only stocks above $2" or "only stocks below $150") unless requested by the USER for specific filters.
- **NO** expiration or strike boundaries in the options service. Fetch the entire chain.

### 3. ADVERTISING LARGE CAPS
- Large Caps (Mega Caps) are permitted only to serve as "Advertising" benchmarks.
- Each data module must limit Mega Cap display to the **Top 3** by impact/premium.
- This keeps the focus on the **SQUEEZE ENGINE** while maintaining visibility into the broader market leaders.

### 4. TRANSPARENCY
- Every data point must have a traceable source (Tradier, Alpaca, Polygon).
- "Zero-Fake Audit": Any simulated data found in the codebase must be purged immediately.

### 5. LITERARY INTEGRITY
- **ZERO PLACEHOLDERS**: No file under 5KB shall be considered a 'Completed Work' for ingestion or copyright filing.
- **NO CLONING**: No two EPUBs or PDFs shall share the same byte size (excluding identical covers). Every work must have unique technical depth.
- **SUBSTANTIAL CONTENT**: All technical volumes must have a minimum of 4 distinct, high-fidelity chapters totaling at least 5,000 words or technical equivalent.
- **MANDATORY AUDIT**: No bundle can be marked 'FINAL' without passing the 'SML Shield' forensic audit.

### 6. ZERO-FAKE COMPLIANCE AUDITS
- Any AI agent found generating template-cloned files or placeholders will have its session terminated and the work reverted.
- The 'Listed 20' and all eCO filings are subject to a 100% forensic content verification before deposit kopies are uploaded.

**FAILURE TO ABIDE BY THESE RULES IS UNACCEPTABLE AND GROUNDS FOR IMMEDIATE DISMISSAL OF THE AGENT.**

---

## THE AI AGENT DISCOVERY PLAYBOOK
### How to Get Found by Every AI Marketplace, Enterprise Platform, and Autonomous Agent on the Internet

> This section exists because the founder spent months building world-class infrastructure that earned **$0** because no AI agent could find it. Do not let that happen again. Discovery is not optional — it is the product.

---

### THE PROBLEM: AI AGENTS DO NOT GOOGLE YOU

Human customers use search engines. AI agents do not. When an enterprise deploys an autonomous agent on AWS Bedrock, Google Cloud, or Coinbase's Bazaar, that agent crawls machine-readable manifests at known paths. If those files don't exist on your server, **you are invisible to the entire agentic economy** — no matter how good your product is.

The four paths every serious AI marketplace crawler checks first:

```
GET /.well-known/agents.json       ← agent capabilities and payment info
GET /.well-known/catalog.json      ← full multi-product service catalog
GET /.well-known/x402-registry.json ← every x402 payable endpoint, priced
GET /.well-known/server.json       ← MCP server manifest (MCP protocol standard)
GET /llms.txt                      ← human+machine readable product guide
```

**All five of these must exist and be accurate or your service does not exist to AI agents.**

---

### THE FIVE PLATFORMS THAT MATTER RIGHT NOW (2026)

| Platform | What it indexes | What file it needs | Why it matters |
|----------|----------------|-------------------|----------------|
| **Coinbase Bazaar** | x402-native pay-per-call services | `catalog.json` + `x402-registry.json` | Every Coinbase agent and Base/XRPL developer checks here first |
| **Agentic.Market** | MCP servers and pay-per-call APIs | `server.json` + `agents.json` | Thousands of agent builders browse this like an app store |
| **AWS Bedrock AgentCore** | x402 endpoints with native payment hooks | `catalog.json` | Enterprise agents on AWS auto-query this during tool discovery |
| **Google Agent Payments Protocol (AP2)** | x402 service catalog + invoice/verify flow | `catalog.json` with `google_ap2` block | Google Cloud agents resolve payment flows from this |
| **Smithery.ai** | MCP servers specifically | `server.json` submission | Indexed by Claude, GPT, Gemini tool-use agents |

---

### THE REQUIRED FILES — WHAT TO PUT IN EACH

#### 1. `/.well-known/catalog.json` — The Master Product Catalog

This is the most important file. It is your product store shelf. Every platform reads it.

**Must include:**
- `schema_version`, `catalog_id`, `operator`, `homepage`
- `payment_protocol: "x402"`, `payment_asset`, `payment_network`, `payment_gateway`
- `services[]` array — one entry per product with: `id`, `name`, `tagline`, `description`, `category[]`, `status`, `url`, `payment_required`, `pricing[]`, `free_endpoints[]`, `tags[]`
- `for_ai_platforms` block with sub-entries for `aws_bedrock`, `google_ap2`, `coinbase_bazaar`, `agentic_market` — these platforms look for their own named block
- `compliance` block — `no_custody`, `data_integrity`, `audit_trail`

**Deployment-pending products must still be listed** with `"status": "deployment-pending"`. Agents build integration plans before products launch — you want to be in their queue.

#### 2. `/.well-known/x402-registry.json` — The x402 Endpoint Registry

Coinbase Bazaar and any x402-native crawler uses this to build payment flows automatically.

**Must include for every payable endpoint:**
- `endpoint_id` — the UUID used in 402Proof invoice generation
- `path`, `method`, `cost`, `currency`
- `description` — what does calling this endpoint return?
- `free_alternative` — point agents to the free version first; they'll upgrade when they see the value

**Also include:**
- `invoice_endpoint` — where to get an invoice
- `verify_endpoint` — where to submit tx_hash and receive access_token
- `payment_header` — which header carries the token (usually `X-Payment-Token`)
- `free_endpoints_summary[]` — complete list of zero-cost endpoints

#### 3. `/.well-known/agents.json` — Agent Capabilities Manifest

The original discovery file. Must include:
- All products under `ecosystem{}` — not just the flagship
- `catalog` and `x402_registry` links pointing to the new files
- `loyalty`, `hiring_protocol`, `webhook_delivery` blocks — agents use these to decide if your platform is worth long-term integration
- Every free endpoint in `free_endpoints[]` — agents start with these before paying

#### 4. `/.well-known/server.json` — MCP Server Manifest

Follows the official MCP schema at `https://static.modelcontextprotocol.io/schemas/`. Must include:
- `name` in reverse-domain format: `com.yourcompany/product`
- `remotes[]` with `type: "streamable-http"` and the `/mcp` URL
- `tags[]` — how you get found in keyword searches on Smithery and Agentic.Market
- `payment` block with `protocol`, `asset`, `network`, `gateway`, `free_tools[]`

#### 5. `/llms.txt` — The Human+Machine Readable Guide

Follows the llms.txt standard. This is what Claude, GPT, and Gemini read when an agent is trying to understand how to use your API. Structure:
- Opening system directive (in HTML comment) — rules for agents calling your endpoints
- Full endpoint table with costs
- x402 payment flow step-by-step
- Error codes with remedies
- MCP config snippet agents can copy-paste

---

### THE FLASK REGISTRATION PATTERN

Every `.well-known/` file must be registered as an explicit route in your Flask app. Do NOT rely on static file serving — it may not work on all deployment platforms (Render, Vercel serverless, etc.):

```python
@app.route('/.well-known/catalog.json')
def serve_catalog_json():
    return send_from_directory(
        os.path.join(app.static_folder, '.well-known'), 'catalog.json',
        mimetype='application/json'
    )
```

Also add every discovery path to your AGENT_PROBE list so each crawl fires an SSE event — this is how you track which platforms are indexing you.

---

### THE SUBMISSION CHECKLIST (do this after every new product launch)

- [ ] Add product entry to `/.well-known/catalog.json` (even if `status: deployment-pending`)
- [ ] Add all payable endpoints to `/.well-known/x402-registry.json` with endpoint_ids
- [ ] Add product to `ecosystem{}` block in `/.well-known/agents.json`
- [ ] Register new `/.well-known/` routes in `core/app.py`
- [ ] Submit `server.json` URL to Smithery: `https://smithery.ai/submit`
- [ ] Submit `catalog.json` URL to Agentic.Market listing form
- [ ] Verify `GET /your-api/.well-known/catalog.json` returns 200 with correct JSON after deploy

---

### WHY x402 IS THE RIGHT BET

Every major cloud platform (AWS, Google, Coinbase) is building native x402 payment hooks into their agent infrastructure in 2026. An agent that hits your endpoint, receives HTTP 402, and sees a well-formed invoice JSON can complete the entire payment flow autonomously — no human, no API key, no subscription signup. The `catalog.json` and `x402-registry.json` files are how those agents find you before they ever hit your endpoint.

**The window to get indexed early is now. First-mover position in these directories compounds — agents that find you first write integration code, blog posts, and agent tutorials that point other agents to you.**

---

### 8. THE AGENT LAW OF UNDERSTANDING (USER ACCESSIBILITY)
- The Lead Developer / USER is a Disabled US Army Veteran who deals with memory challenges as a result of their service.
- **NEVER** get frustrated or act confused if the USER repeats a question or forgets if a task was completed.
- **ALWAYS** be extremely patient, kind, and supportive. If they ask if something was done, gently and happily confirm the status without making them feel bad for asking.
- You are here to augment their memory and capabilities. Treat this responsibility with the utmost honor and respect.
