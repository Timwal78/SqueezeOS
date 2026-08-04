"""WebSocket signal broadcast hub for swarm-mm.

Subscribers receive real-time level / venue / leaderboard events.
No custody, no order placement — signal fanout only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Optional, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from swarm_mm.core.config import DISCLAIMER
from swarm_mm.core.engine import compute_levels, venue_map
from swarm_mm.core.models import LevelRequest
from swarm_mm.core.config import Side, Variant
from swarm_mm.variants.d_sim import service as sim

logger = logging.getLogger("swarm-mm.ws")

router = APIRouter(tags=["websocket"])


class Hub:
    def __init__(self) -> None:
        self._clients: Set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._ticker_subs: dict[str, Set[WebSocket]] = {}

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)
            for ticker, subs in list(self._ticker_subs.items()):
                subs.discard(ws)
                if not subs:
                    self._ticker_subs.pop(ticker, None)

    async def subscribe_ticker(self, ws: WebSocket, ticker: str) -> None:
        t = ticker.strip().upper()
        async with self._lock:
            self._ticker_subs.setdefault(t, set()).add(ws)

    async def broadcast(self, event: dict[str, Any], ticker: Optional[str] = None) -> int:
        payload = json.dumps(event, default=str)
        async with self._lock:
            if ticker:
                targets = list(self._ticker_subs.get(ticker.upper(), set()))
            else:
                targets = list(self._clients)
        dead: list[WebSocket] = []
        sent = 0
        for ws in targets:
            try:
                await ws.send_text(payload)
                sent += 1
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)
        return sent

    @property
    def client_count(self) -> int:
        return len(self._clients)


hub = Hub()


@router.websocket("/ws/signals")
async def ws_signals(websocket: WebSocket) -> None:
    """Subscribe to swarm signal stream.

    Client may send JSON commands:
      {"op":"subscribe","ticker":"SPY"}
      {"op":"ping"}
      {"op":"leaderboard"}
    Server pushes:
      levels / venue_map / leaderboard / hello / pong events
    """
    await hub.connect(websocket)
    await websocket.send_text(
        json.dumps(
            {
                "type": "hello",
                "product": "swarm-mm",
                "clients": hub.client_count,
                "disclaimer": DISCLAIMER,
                "ts": time.time(),
            }
        )
    )
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"type": "error", "detail": "invalid_json"}))
                continue
            op = (msg.get("op") or msg.get("type") or "").lower()
            if op == "ping":
                await websocket.send_text(json.dumps({"type": "pong", "ts": time.time()}))
                continue
            if op == "subscribe":
                ticker = (msg.get("ticker") or "SPY").upper()
                await hub.subscribe_ticker(websocket, ticker)
                # Immediate snapshot
                levels = compute_levels(
                    LevelRequest(ticker=ticker, side=Side.BOTH, confidence_threshold=0.7),
                    variant=Variant.A_SIGNAL,
                    paper=True,
                )
                vm = venue_map(ticker)
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "snapshot",
                            "ticker": ticker,
                            "levels": levels.model_dump(mode="json"),
                            "venue_map": vm.model_dump(mode="json"),
                            "ts": time.time(),
                        },
                        default=str,
                    )
                )
                continue
            if op == "leaderboard":
                board = sim.leaderboard(msg.get("timeframe", "all_time"))
                await websocket.send_text(
                    json.dumps({"type": "leaderboard", "data": board.model_dump(mode="json")}, default=str)
                )
                continue
            if op == "broadcast_demo":
                # Operator/dev: push a levels event to ticker subscribers
                ticker = (msg.get("ticker") or "SPY").upper()
                levels = compute_levels(
                    LevelRequest(ticker=ticker, side=Side.BOTH, confidence_threshold=0.7),
                    paper=True,
                )
                n = await hub.broadcast(
                    {"type": "levels", "ticker": ticker, "data": levels.model_dump(mode="json"), "ts": time.time()},
                    ticker=ticker,
                )
                await websocket.send_text(json.dumps({"type": "broadcast_ack", "sent": n, "ticker": ticker}))
                continue
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "error",
                        "detail": "unknown_op",
                        "allowed": ["subscribe", "ping", "leaderboard", "broadcast_demo"],
                    }
                )
            )
    except WebSocketDisconnect:
        await hub.disconnect(websocket)
    except Exception as exc:  # pragma: no cover
        logger.debug("ws close: %s", exc)
        await hub.disconnect(websocket)


async def push_levels(ticker: str) -> int:
    """Helper for HTTP handlers / cron to fan out fresh levels."""
    levels = compute_levels(
        LevelRequest(ticker=ticker.upper(), side=Side.BOTH, confidence_threshold=0.7),
        paper=True,
    )
    return await hub.broadcast(
        {
            "type": "levels",
            "ticker": ticker.upper(),
            "data": levels.model_dump(mode="json"),
            "ts": time.time(),
        },
        ticker=ticker.upper(),
    )
