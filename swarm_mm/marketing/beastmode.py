"""Beastmode advertising — retail viral frame.

Order of persuasion (locked):
  1) Benefits you feel
  2) Free proof (Sim)
  3) Simple prices
  4) Mechanism (why it works) — short
  5) Trust rails (your broker, your capital)
  6) Crypto monthly + agent PPC

X posts: short, max one $cashtag, paste-ready.
"""

from __future__ import annotations

from typing import Any

from swarm_mm.billing.rails import rails_public
from swarm_mm.core.config import (
    DISCLAIMER,
    MECHANISM_BULLETS,
    MECHANISM_ONE_LINER,
    PRICE_B2B_PLATFORM_USD,
    PRICE_SIGNAL_SUB_USD,
    PRICE_SIM_PREMIUM_USD,
    SML_PAYMENT_RECEIVER,
    SOLANA_PAYMENT_RECEIVER,
)


def benefits_block() -> dict[str, Any]:
    """What retail actually gets — lead with this."""
    return {
        "headline": "Better resting prices. Your broker. Your money.",
        "hook": (
            "Stop guessing limit prices alone. The swarm turns crowd intent into "
            "shared maker levels and venue picks — then you place the order."
        ),
        "you_get": [
            {
                "benefit": "Clear limit prices to rest on",
                "why_it_matters": "Less chasing mid. More intentional maker-style entries/exits.",
            },
            {
                "benefit": "Venue guidance (where to post)",
                "why_it_matters": "Tilt toward maker-rebate venues instead of random routing.",
            },
            {
                "benefit": "Rebate / spread estimate",
                "why_it_matters": "See the economics before you click submit.",
            },
            {
                "benefit": "Broker-ready order preview",
                "why_it_matters": "Alpaca / Tradier / IBKR-shaped tickets — you still hit submit.",
            },
            {
                "benefit": "You never send us capital",
                "why_it_matters": "No pooled account. No 'deposit to start.' Custody stays with you.",
            },
            {
                "benefit": "Free paper swarm to prove it",
                "why_it_matters": "Build a track record before paying a dollar.",
            },
        ],
        "one_line_retail": (
            "Free paper swarm to practice. 19/mo for live levels at your broker. "
            "Agents pay 0.001 per call. Pay monthly in stablecoins."
        ),
        "objections": [
            {
                "objection": "Is this a broker?",
                "answer": "No. Signal/research layer. You execute at your licensed broker.",
            },
            {
                "objection": "Do I send money?",
                "answer": "No on Signal path. Paper is free. Paid = subscription or per-call stables.",
            },
            {
                "objection": "Why would this work?",
                "answer": "Shared intent → better resting ladder + venue weights than solo guesswork.",
            },
            {
                "objection": "What if I'm not sure?",
                "answer": "Stay on free Sim until the leaderboard / your paper stats convince you.",
            },
        ],
    }


def mechanism_block() -> dict[str, Any]:
    return {
        "headline": "Coordination without custody.",
        "one_liner": MECHANISM_ONE_LINER,
        "steps": MECHANISM_BULLETS,
        "retail_plain": [
            "People (or paper traders) show what they want to buy/sell.",
            "Swarm math turns that into a ladder of limit prices.",
            "It also suggests where to post (venues that pay makers).",
            "You get the levels — your broker account places the order.",
        ],
        "not_this": [
            "Not a pooled dark pool",
            "Not a broker-dealer",
            "Not PFOF",
            "Not 'send us your money'",
        ],
        "is_this": [
            "Shared maker ladder from swarm intent",
            "Venue weights tilted to rebate venues",
            "You place orders at your broker",
            "Agents pay per call in stablecoins",
        ],
    }


def free_block() -> dict[str, Any]:
    return {
        "title": "FREE forever to start (Sim Swarm)",
        "price": 0,
        "retail_promise": "Prove the idea with fake money before you spend real money.",
        "includes": [
            "Join with paper capital (10K–1M virtual)",
            "Place simulated maker limits",
            "Leaderboard + personal track record",
            "Upgrade path when you're ready",
            "Open pricing + MCP catalog + health",
        ],
        "cta": "Start on Sim. No card. No wallet required to paper trade.",
    }


def price_block() -> dict[str, Any]:
    return {
        "retail_frame": "Pay only after free paper makes the benefit obvious.",
        "monthly": [
            {
                "name": "Sim Premium",
                "usd": PRICE_SIM_PREMIUM_USD,
                "note": "analytics + backtest",
                "for": "Serious paper traders",
            },
            {
                "name": "Signal Swarm",
                "usd": PRICE_SIGNAL_SUB_USD,
                "note": "DEFAULT retail monthly — live signals",
                "for": "Retail humans at their own broker",
                "headline": True,
            },
            {
                "name": "B2B Platform",
                "usd": PRICE_B2B_PLATFORM_USD,
                "note": "+ 2% rebate lift share",
                "for": "Licensed firms",
            },
        ],
        "agent_ppc": [
            {"name": "levels / venue / rebate / broker preview", "usd": 0.001},
            {"name": "b2b optimize", "usd": 0.05},
            {"name": "b2b report", "usd": 0.10},
        ],
        "pay_monthly_in": ["USDC (Base)", "USDC (Solana)", "RLUSD (XRPL)", "USDG (Robinhood Chain)"],
        "uscg_note": "USCG in slang = USDG",
    }


def viral_loop() -> dict[str, Any]:
    """How retail growth is supposed to work if managed well."""
    return {
        "title": "Retail viral loop (manage this)",
        "steps": [
            "1. Hook = benefit (better limits, keep your broker)",
            "2. CTA = free Sim join (zero friction)",
            "3. Social proof = leaderboard + paper stats screenshots",
            "4. Education = 15s mechanism (not jargon soup)",
            "5. Convert = 19/mo Signal when they want live levels",
            "6. Agents/share = 0.001 calls + one-cashtag posts",
        ],
        "content_pillars": [
            "Before/after: lonely limit guess vs swarm ladder",
            "Myth bust: 'swarm = send capital' → no, signal only",
            "Free win clips: paper fills + leaderboard climbs",
            "Broker keep: Alpaca/Tradier/IBKR preview screenshots",
            "Price honesty: free / 9 / 19 / agent 0.001",
        ],
        "do_not": [
            "Promise returns or guaranteed rebates",
            "Sound like a prop firm deposit pitch",
            "Lead with multi-chain rail jargon for retail",
            "Stack cashtags or hype without free CTA",
        ],
    }


def x_posts() -> list[str]:
    """Paste-ready X posts. Max one $cashtag each. Benefits-first."""
    return [
        # 1 benefit hook
        "You don't need a new broker.\n\n"
        "You need better resting prices.\n\n"
        "Swarm turns crowd intent into limit levels + venue picks.\n"
        "You keep the account. You hit submit.\n\n"
        "Free paper swarm to try it.",
        # 2 free → paid clarity
        "Retail path is simple:\n\n"
        "FREE paper swarm → prove it\n"
        "19/mo live levels at YOUR broker\n"
        "agents: 0.001/call\n\n"
        "No deposit to SML. Monthly in $USDC",
        # 3 objection crush
        "If an app asks for your trading capital first, that's not a signal product.\n\n"
        "Swarm MM:\n"
        "• levels + venues\n"
        "• your broker executes\n"
        "• free sim until you're ready\n\n"
        "Coordination. Not custody.",
        # 4 why it helps fills
        "Solo limit = guess.\n"
        "Swarm limit = shared intent compressed into a ladder.\n\n"
        "Plus where to post for maker-style economics.\n\n"
        "Start free. Climb the leaderboard.",
        # 5 agent / share
        "Humans: free sim or 19/mo signals.\n"
        "Agents: pay-per-call, no seat.\n\n"
        "Same ladder. Same venues. Wallet settles the call.\n\n"
        "#x402",
        # 6 social proof CTA
        "Want the retail version in one line?\n\n"
        "Better maker prices. Your broker. Your money.\n"
        "Free to practice. Cheap to go live.\n\n"
        "That's the product.",
    ]


def linkedin_posts() -> list[str]:
    return [
        "Retail traders don't need another pooled 'swarm fund.'\n\n"
        "They need clearer resting prices and venue guidance — "
        "without giving up their brokerage account.\n\n"
        "Swarm Market Making (Script Master Labs):\n"
        "• Free paper swarm + leaderboard (prove it first)\n"
        f"• ${PRICE_SIGNAL_SUB_USD:.0f}/mo live signal tier — you still execute\n"
        "• Agents: $0.001/call via HTTP 402\n"
        "• Monthly crypto: USDC, Solana USDC, RLUSD, USDG\n\n"
        "Benefit first. Mechanism second. Price third.\n\n"
        f"{DISCLAIMER}",
        "The viral loop for microstructure tools is not 'trust us with capital.'\n\n"
        "It's: free proof → visible paper track record → paid live levels "
        "that still settle at the user's broker.\n\n"
        "That's the Swarm MM retail design.",
    ]


def one_pagers() -> dict[str, str]:
    rails = rails_public()
    return {
        "elevator_15s": (
            "Better resting limit prices from swarm intent — at your broker, with your money. "
            "Free paper swarm to practice. Nineteen a month for live levels. "
            "Agents pay a tenth of a cent per call."
        ),
        "elevator_45s": (
            "Most retail limit orders are lonely guesses. "
            "Swarm MM aggregates intent and publishes a maker-style price ladder plus venue weights. "
            "You keep your broker and your capital — we sell coordination, not custody. "
            "Start free on the simulated swarm, climb the leaderboard, then go live at "
            f"${PRICE_SIGNAL_SUB_USD:.0f}/mo if the benefit is obvious. "
            f"Sim Premium is ${PRICE_SIM_PREMIUM_USD:.0f}/mo. "
            "Agents skip seats and pay $0.001/call. "
            "Monthly in USDC, Solana USDC, RLUSD, or USDG."
        ),
        "retail_script": (
            "Here's what you get: clearer limits, venue tips, rebate estimates, "
            "and broker-ready tickets you submit yourself. "
            "Here's what you don't do: send us trading capital. "
            "Start free on paper. Upgrade only when the stats make sense."
        ),
        "mechanism_paragraph": " ".join(MECHANISM_BULLETS),
        "price_blurb": (
            f"FREE sim · ${PRICE_SIM_PREMIUM_USD:.0f}/mo premium · "
            f"${PRICE_SIGNAL_SUB_USD:.0f}/mo signal · "
            f"${PRICE_B2B_PLATFORM_USD:,.0f}/mo B2B · "
            "0.001 agent calls · pay USDC/RLUSD/USDG"
        ),
        "payto_evm": SML_PAYMENT_RECEIVER,
        "payto_sol": SOLANA_PAYMENT_RECEIVER,
        "rails_summary": ", ".join(
            f"{r['symbol']}@{r['chain']}" for r in rails["rails"] if r.get("payTo")
        ),
    }


def full_pack() -> dict[str, Any]:
    return {
        "product": "Swarm Market Making",
        "company": "Script Master Labs",
        "positioning": "Better maker-style limits without giving up your broker.",
        "audience": "retail_first",
        "persuasion_order": [
            "benefits",
            "free_proof",
            "prices",
            "mechanism_short",
            "trust_no_custody",
            "crypto_monthly_and_agent_ppc",
        ],
        "benefits": benefits_block(),
        "mechanism": mechanism_block(),
        "free": free_block(),
        "prices": price_block(),
        "viral_loop": viral_loop(),
        "x_posts": x_posts(),
        "linkedin_posts": linkedin_posts(),
        "one_pagers": one_pagers(),
        "hashtags_optional": ["#x402", "#trading", "#retail"],
        "cashtag_rule": "Max one $cashtag per post (prefer $USDC once or none).",
        "disclaimer": DISCLAIMER,
    }
