"""FastAPI application — Swarm Market Making 4-variant suite."""

from __future__ import annotations

import os
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pathlib import Path

from swarm_mm import __version__
from swarm_mm.billing.x402 import (
    PaymentRequired,
    get_pay_to,
    operator_authorized,
    payment_response,
    require_payment_or_operator,
    well_known_resources,
    x402_challenge,
)
from swarm_mm.core.config import (
    DISCLAIMER,
    PRICE_B2B_OPTIMIZE_USD,
    PRICE_B2B_REPORT_USD,
    PRICE_LEVELS_CALL_USD,
    PRICE_REBATE_TRACKER_USD,
    PRICE_SIGNAL_SUB_USD,
    PRICE_SIM_PREMIUM_USD,
    PRICE_VENUE_MAP_USD,
    SML_PAYMENT_RECEIVER,
    Side,
    Variant,
)
from swarm_mm.core.engine import engine_info
from swarm_mm.core.models import (
    B2BConfigureRequest,
    B2BOptimizeRequest,
    CryptoDepositRequest,
    HealthResponse,
    LevelRequest,
    SimJoinRequest,
    SimTradeRequest,
    UpgradeRequest,
)
from swarm_mm.mcp.tools import dispatch as mcp_dispatch
from swarm_mm.mcp.tools import manifest as mcp_manifest
from swarm_mm.api.ws import hub, router as ws_router
from swarm_mm.variants.a_signal import service as signal
from swarm_mm.variants.a_signal import brokers as broker_adapters
from swarm_mm.variants.b_crypto import service as crypto
from swarm_mm.variants.c_b2b import service as b2b
from swarm_mm.variants.d_sim import service as sim

app = FastAPI(
    title="Swarm Market Making API",
    description=(
        "Script Master Labs — 4-variant swarm MM suite "
        "(A Signal / B Crypto / C B2B / D Simulated). "
        + DISCLAIMER
    ),
    version=__version__,
    contact={"name": "Script Master Labs", "email": "timothy.walton45@gmail.com"},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("SWARM_MM_CORS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ws_router)

_STATIC = Path(__file__).resolve().parent.parent / "static"


def _static_file(name: str, media_type: str | None = None):
    path = _STATIC / name
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{name} not found")
    kwargs = {"path": path}
    if media_type:
        kwargs["media_type"] = media_type
    return FileResponse(**kwargs)


@app.get("/landing", include_in_schema=False)
@app.get("/swarm-market-making", include_in_schema=False)
@app.get("/swarm-market-making.html", include_in_schema=False)
def landing_page():
    """SEO landing — same HTML as www.scriptmasterlabs.com/swarm-market-making.html."""
    return _static_file("index.html", media_type="text/html; charset=utf-8")


@app.get("/panel", include_in_schema=False)
@app.get("/desk-panel", include_in_schema=False)
def desk_panel():
    """Embeddable Swarm MM panel for Swarm Agents Intelligence (iframe)."""
    return _static_file("panel.html", media_type="text/html; charset=utf-8")


@app.get("/robots.txt", include_in_schema=False)
def robots_txt():
    return _static_file("robots.txt", media_type="text/plain; charset=utf-8")


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap_xml():
    return _static_file("sitemap.xml", media_type="application/xml")


@app.get("/llms.txt", include_in_schema=False)
def llms_txt():
    return _static_file("llms.txt", media_type="text/plain; charset=utf-8")


@app.get("/seo.json", include_in_schema=False)
def seo_json() -> dict[str, Any]:
    """Machine-readable SEO card for monitors / agent discovery."""
    return {
        "product": "Swarm Market Making",
        "canonical": "https://www.scriptmasterlabs.com/swarm-market-making.html",
        "www_only_gsc": True,
        "never_verify_onrender_dns": True,
        "title": "Swarm Market Making — Limit Order Signals Without Giving Up Your Broker | ScriptMasterLabs",
        "description": (
            "Swarm market making for retail: free paper swarm, $19/mo live limit-order levels + venue map, "
            "agents pay $0.001/call via x402. Keep your broker and capital."
        ),
        "primary_keywords": [
            "swarm market making",
            "limit order signals",
            "retail market making",
            "maker rebate venues",
            "paper trading swarm",
            "x402 trading API",
            "AI agent pay per call",
            "coordination without custody",
            "free paper trading leaderboard",
        ],
        "free": {"plan": "sim_free", "price_usd": 0},
        "monthly_usd": {"sim_premium": 9, "signal": 19, "b2b": 5000},
        "agent_ppc_floor_usd": 0.001,
        "structured_data": ["SoftwareApplication", "FAQPage", "HowTo", "BreadcrumbList", "Organization"],
        "assets": {
            "landing": "/landing",
            "robots": "/robots.txt",
            "sitemap": "/sitemap.xml",
            "llms": "/llms.txt",
            "pricing": "/v1/pricing",
            "x402": "/.well-known/x402",
            "openapi": "/openapi.json",
        },
        "portfolio_path": "/workspace/sml-portfolio-temp/swarm-market-making.html",
        "sitemap_entry": "https://www.scriptmasterlabs.com/swarm-market-making.html",
    }


@app.exception_handler(PaymentRequired)
async def _payment_required_handler(_req: Request, exc: PaymentRequired):
    return payment_response(exc.price_usd, exc.resource, exc.description)


@app.exception_handler(PermissionError)
async def _perm_handler(_req: Request, exc: PermissionError):
    return JSONResponse(status_code=403, content={"error": "forbidden", "detail": str(exc), "disclaimer": DISCLAIMER})


@app.exception_handler(ValueError)
async def _value_handler(_req: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"error": "bad_request", "detail": str(exc), "disclaimer": DISCLAIMER})


# ── Health / discovery ───────────────────────────────────────────────────────


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=__version__,
        variants=["A", "B", "C", "D"],
        pay_to=get_pay_to(),
        paper_default=True,
    )


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "product": "swarm-mm",
        "version": __version__,
        "company": "Script Master Labs",
        "variants": {
            "A": "Signal Swarm — $19/mo SaaS, user broker execution",
            "B": "Crypto-Only Swarm — DEX vault, US geofenced",
            "C": "B2B Swarm Engine — white-label for licensed entities",
            "D": "Simulated Swarm — paper POC (launch first)",
        },
        "docs": "/docs",
        "openapi": "/openapi.json",
        "well_known_x402": "/.well-known/x402",
        "mcp": "/mcp/tools",
        "websocket": "/ws/signals",
        "brokers": "/v1/signal/brokers",
        "pay_to": get_pay_to(),
        "disclaimer": DISCLAIMER,
        "build_sequence": ["D", "A", "C", "B"],
    }


@app.get("/.well-known/x402")
def well_known_x402() -> dict[str, Any]:
    return well_known_resources()


@app.get("/v1/engine")
def engine() -> dict[str, Any]:
    return engine_info()


# ── Variant D — Simulated ────────────────────────────────────────────────────


@app.post("/v1/sim/join")
def sim_join(body: SimJoinRequest) -> dict[str, Any]:
    acct = sim.join(body)
    return {"status": "ok", "account": acct.model_dump(mode="json"), "paper": True, "disclaimer": DISCLAIMER}


@app.post("/v1/sim/trade")
def sim_trade(body: SimTradeRequest) -> dict[str, Any]:
    return sim.trade(body)


@app.get("/v1/sim/account/{user_id}")
def sim_account(user_id: str) -> dict[str, Any]:
    acct = sim.get_account(user_id)
    if not acct:
        raise HTTPException(status_code=404, detail="user not found — join first")
    return {"account": acct.model_dump(mode="json"), "paper": True}


@app.get("/v1/sim/leaderboard")
def sim_leaderboard(timeframe: str = Query(default="all_time", pattern="^(daily|weekly|all_time)$")) -> dict[str, Any]:
    return sim.leaderboard(timeframe).model_dump(mode="json")


@app.post("/v1/sim/upgrade")
def sim_upgrade(body: UpgradeRequest) -> dict[str, Any]:
    return sim.upgrade(body)


@app.post("/v1/sim/premium")
async def sim_premium(
    request: Request,
    user_id: str,
    x_operator_key: Optional[str] = Header(default=None, alias="X-Operator-Key"),
    x_payment: Optional[str] = Header(default=None, alias="X-PAYMENT"),
) -> dict[str, Any]:
    try:
        pay = await require_payment_or_operator(
            request,
            PRICE_SIM_PREMIUM_USD,
            "/v1/sim/premium",
            "Sim premium analytics $9/mo",
            x_operator_key=x_operator_key,
            x_payment=x_payment,
        )
    except PaymentRequired as e:
        raise e
    acct = sim.set_premium(user_id, True)
    return {"status": "premium_active", "payment": pay, "account": acct.model_dump(mode="json"), "price_usd_mo": PRICE_SIM_PREMIUM_USD}


# ── Variant A — Signal ───────────────────────────────────────────────────────


@app.get("/v1/signal/levels")
async def signal_levels(
    request: Request,
    ticker: str,
    side: str = "both",
    confidence_threshold: float = 0.75,
    notional_usd: Optional[float] = None,
    depth: int = 5,
    x_operator_key: Optional[str] = Header(default=None, alias="X-Operator-Key"),
    x_payment: Optional[str] = Header(default=None, alias="X-PAYMENT"),
) -> dict[str, Any]:
    await require_payment_or_operator(
        request, PRICE_LEVELS_CALL_USD, "/v1/signal/levels", "signal levels", x_operator_key=x_operator_key, x_payment=x_payment
    )
    res = signal.levels(ticker, side=side, confidence_threshold=confidence_threshold, notional_usd=notional_usd, depth=depth)
    return res.model_dump(mode="json")


@app.get("/v1/signal/venue-map")
async def signal_venue_map(
    request: Request,
    ticker: str,
    x_operator_key: Optional[str] = Header(default=None, alias="X-Operator-Key"),
    x_payment: Optional[str] = Header(default=None, alias="X-PAYMENT"),
) -> dict[str, Any]:
    await require_payment_or_operator(
        request, PRICE_VENUE_MAP_USD, "/v1/signal/venue-map", "venue map", x_operator_key=x_operator_key, x_payment=x_payment
    )
    return signal.venue_map_for(ticker).model_dump(mode="json")


@app.get("/v1/signal/rebate-tracker")
async def signal_rebate(
    request: Request,
    user_id: str,
    ticker: str,
    notional_usd: float = 100_000,
    x_operator_key: Optional[str] = Header(default=None, alias="X-Operator-Key"),
    x_payment: Optional[str] = Header(default=None, alias="X-PAYMENT"),
) -> dict[str, Any]:
    await require_payment_or_operator(
        request,
        PRICE_REBATE_TRACKER_USD,
        "/v1/signal/rebate-tracker",
        "rebate tracker",
        x_operator_key=x_operator_key,
        x_payment=x_payment,
    )
    return signal.rebate(user_id, ticker, notional_usd).model_dump(mode="json")


@app.post("/v1/signal/subscribe")
async def signal_subscribe(
    request: Request,
    user_id: str,
    broker: str = "alpaca",
    x_operator_key: Optional[str] = Header(default=None, alias="X-Operator-Key"),
    x_payment: Optional[str] = Header(default=None, alias="X-PAYMENT"),
) -> dict[str, Any]:
    await require_payment_or_operator(
        request,
        PRICE_SIGNAL_SUB_USD,
        "/v1/signal/subscribe",
        "Signal Swarm $19/mo",
        x_operator_key=x_operator_key,
        x_payment=x_payment,
    )
    return signal.subscribe(user_id, broker=broker)


@app.get("/v1/signal/subscription/{user_id}")
def signal_sub_status(user_id: str) -> dict[str, Any]:
    return signal.subscription_status(user_id)


@app.get("/v1/signal/brokers")
def signal_brokers() -> dict[str, Any]:
    return {
        "brokers": broker_adapters.list_brokers(),
        "execution": "user_broker_only",
        "note": "Swarm formats order payloads; user submits via their own brokerage credentials.",
        "disclaimer": DISCLAIMER,
    }


@app.get("/v1/signal/broker-orders")
async def signal_broker_orders(
    request: Request,
    ticker: str,
    broker: str = "alpaca",
    side: str = "both",
    confidence_threshold: float = 0.75,
    max_levels: int = 3,
    x_operator_key: Optional[str] = Header(default=None, alias="X-Operator-Key"),
    x_payment: Optional[str] = Header(default=None, alias="X-PAYMENT"),
) -> dict[str, Any]:
    """Preview broker-native limit orders from swarm levels. Does NOT submit."""
    await require_payment_or_operator(
        request,
        PRICE_LEVELS_CALL_USD,
        "/v1/signal/broker-orders",
        "broker order preview",
        x_operator_key=x_operator_key,
        x_payment=x_payment,
    )
    return broker_adapters.preview_orders(
        broker=broker,
        ticker=ticker,
        side=side,
        confidence_threshold=confidence_threshold,
        max_levels=max_levels,
    )


@app.get("/v1/ws/stats")
def ws_stats() -> dict[str, Any]:
    return {"clients": hub.client_count, "path": "/ws/signals"}


# ── Variant C — B2B ──────────────────────────────────────────────────────────


@app.post("/v1/b2b/configure")
def b2b_configure(body: B2BConfigureRequest) -> dict[str, Any]:
    return b2b.configure(body)


@app.post("/v1/b2b/optimize")
async def b2b_optimize(
    request: Request,
    body: B2BOptimizeRequest,
    x_operator_key: Optional[str] = Header(default=None, alias="X-Operator-Key"),
    x_payment: Optional[str] = Header(default=None, alias="X-PAYMENT"),
) -> dict[str, Any]:
    await require_payment_or_operator(
        request, PRICE_B2B_OPTIMIZE_USD, "/v1/b2b/optimize", "b2b optimize", x_operator_key=x_operator_key, x_payment=x_payment
    )
    return b2b.optimize(body)


@app.get("/v1/b2b/report")
async def b2b_report(
    request: Request,
    customer_id: str,
    period: str = "30d",
    x_operator_key: Optional[str] = Header(default=None, alias="X-Operator-Key"),
    x_payment: Optional[str] = Header(default=None, alias="X-PAYMENT"),
) -> dict[str, Any]:
    await require_payment_or_operator(
        request, PRICE_B2B_REPORT_USD, "/v1/b2b/report", "b2b report", x_operator_key=x_operator_key, x_payment=x_payment
    )
    return b2b.report(customer_id, period)


# ── Variant B — Crypto ───────────────────────────────────────────────────────


@app.post("/v1/crypto/deposit")
def crypto_deposit(body: CryptoDepositRequest, user_id: str = "anonymous") -> dict[str, Any]:
    return crypto.deposit(body, user_id=user_id)


@app.get("/v1/crypto/positions")
async def crypto_positions(
    request: Request,
    user_id: str,
    x_operator_key: Optional[str] = Header(default=None, alias="X-Operator-Key"),
    x_payment: Optional[str] = Header(default=None, alias="X-PAYMENT"),
) -> dict[str, Any]:
    await require_payment_or_operator(
        request, PRICE_LEVELS_CALL_USD, "/v1/crypto/positions", "crypto positions", x_operator_key=x_operator_key, x_payment=x_payment
    )
    return crypto.positions(user_id)


@app.post("/v1/crypto/withdraw")
def crypto_withdraw(
    vault_id: str,
    asset: str,
    amount: float,
    user_id: str = "anonymous",
    non_us_attestation: bool = False,
) -> dict[str, Any]:
    return crypto.withdraw(vault_id, asset, amount, user_id, non_us_attestation)


@app.post("/v1/crypto/rebalance")
def crypto_rebalance(
    vault_id: str,
    target_dex_weights: dict[str, float],
    non_us_attestation: bool = False,
) -> dict[str, Any]:
    return crypto.rebalance(vault_id, target_dex_weights, non_us_attestation)


# ── MCP ──────────────────────────────────────────────────────────────────────


@app.get("/mcp/tools")
def mcp_tools() -> dict[str, Any]:
    return mcp_manifest()


@app.post("/mcp/call")
async def mcp_call(
    request: Request,
    body: dict[str, Any],
    x_operator_key: Optional[str] = Header(default=None, alias="X-Operator-Key"),
) -> dict[str, Any]:
    tool = body.get("tool") or body.get("name")
    params = body.get("params") or body.get("arguments") or {}
    if not tool:
        raise HTTPException(status_code=400, detail="tool required")
    # Free tools always; paid tools need operator or soft payment handled inside variants
    try:
        result = mcp_dispatch(tool, params)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"tool": tool, "result": result}


@app.get("/v1/pricing")
def pricing() -> dict[str, Any]:
    from swarm_mm.billing.subscriptions import pricing_card

    card = pricing_card()
    card["sample_402_ppc"] = x402_challenge(0.001, "/v1/signal/levels")
    card["sample_402_monthly_signal"] = x402_challenge(PRICE_SIGNAL_SUB_USD, "/v1/billing/subscribe/signal", "Signal Swarm monthly")
    return card


@app.get("/v1/billing/plans")
def billing_plans() -> dict[str, Any]:
    from swarm_mm.billing.subscriptions import list_plans

    return list_plans()


@app.get("/v1/billing/subscription/{user_id}")
def billing_subscription(user_id: str) -> dict[str, Any]:
    from swarm_mm.billing.subscriptions import get_subscription

    return get_subscription(user_id)


@app.post("/v1/billing/subscribe/{plan}")
async def billing_subscribe(
    plan: str,
    request: Request,
    user_id: str,
    rail: str = "base_usdc",
    x_operator_key: Optional[str] = Header(default=None, alias="X-Operator-Key"),
    x_payment: Optional[str] = Header(default=None, alias="X-PAYMENT"),
    x_payment_hash: Optional[str] = Header(default=None, alias="X-Payment-Hash"),
) -> dict[str, Any]:
    """Start monthly crypto plan. Free plans activate immediately. Paid → 402 multi-rail or proof."""
    from swarm_mm.billing.subscriptions import PLANS, start_subscription
    from swarm_mm.billing.x402 import operator_authorized

    plan_l = plan.strip().lower()
    if plan_l not in PLANS:
        raise HTTPException(status_code=404, detail=f"unknown plan {plan}")

    meta = PLANS[plan_l]
    proof = (x_payment or x_payment_hash or "").strip() or None
    # Monthly: only treat as operator force when a key header is actually present.
    # SWARM_MM_DEV_OPEN must NOT silently activate paid plans without proof.
    force = bool(x_operator_key) and operator_authorized(x_operator_key)

    if meta.get("free"):
        return start_subscription(user_id, plan_l, rail=rail, payment_proof=None, force=True)

    if not proof and not force:
        # Return 402 challenge via PaymentRequired
        from swarm_mm.billing.x402 import PaymentRequired

        raise PaymentRequired(
            price_usd=float(meta["price_usd_mo"]),
            resource=meta.get("resource") or f"/v1/billing/subscribe/{plan_l}",
            description=f"Swarm MM {meta['name']} monthly",
        )

    return start_subscription(
        user_id,
        plan_l,
        rail=rail,
        payment_proof=proof or "operator",
        force=force,
    )


@app.post("/v1/billing/cancel")
def billing_cancel(user_id: str) -> dict[str, Any]:
    from swarm_mm.billing.subscriptions import cancel_subscription

    return cancel_subscription(user_id)


@app.get("/v1/ads/beastmode")
def ads_beastmode() -> dict[str, Any]:
    from swarm_mm.marketing.beastmode import full_pack

    return full_pack()


@app.get("/v1/ads/x")
def ads_x() -> dict[str, Any]:
    from swarm_mm.marketing.beastmode import x_posts

    return {"platform": "x", "posts": x_posts(), "rule": "1 cashtag max, paste-ready"}


@app.get("/v1/ads/linkedin")
def ads_linkedin() -> dict[str, Any]:
    from swarm_mm.marketing.beastmode import linkedin_posts

    return {"platform": "linkedin", "posts": linkedin_posts()}


def main() -> None:
    import uvicorn

    host = os.environ.get("SWARM_MM_HOST", "0.0.0.0")
    port = int(os.environ.get("SWARM_MM_PORT", "8088"))
    uvicorn.run("swarm_mm.api.app:app", host=host, port=port, reload=os.environ.get("SWARM_MM_RELOAD") == "1")


if __name__ == "__main__":
    main()
