"""
priority_router.py — x402-gated priority inference routing.

This is the REAL mechanism the "gravitational lensing" metaphor pointed at:
not deliberately slowing anyone down, but a quality-of-service queue where a
paying agent's loyalty tier buys higher scheduling priority. Higher tier =
served first under contention. That is a real, sellable product (priority API
tiers) — not synthetic latency theater.

Design:
  - A bounded priority queue ordered by (−priority, enqueue_seq) so higher
    loyalty priority is served first and ties break FIFO (no starvation within
    a tier).
  - The upstream model call is pluggable (`handler`): proxy to vLLM/TGI/an LLM
    API in production. The router owns scheduling, not inference.
  - Worker threads drain the queue. `submit` returns a Future-like Ticket the
    caller awaits.

It is honest about its limits: priority scheduling helps under contention. If
the upstream has spare capacity, everyone is fast regardless of tier — which is
correct behavior, not a bug.
"""

from __future__ import annotations

import heapq
import threading
import time
import itertools
from dataclasses import dataclass, field
from typing import Callable, Any, Optional


@dataclass(order=True)
class _QueueItem:
    sort_key: tuple = field(compare=True)
    ticket: "Ticket" = field(compare=False, default=None)


@dataclass
class Ticket:
    request_id: str
    priority: int
    enqueued_at: float
    _event: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: Optional[BaseException] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    def wait(self, timeout: Optional[float] = None) -> Any:
        if not self._event.wait(timeout):
            raise TimeoutError(f"request {self.request_id} timed out in queue")
        if self.error is not None:
            raise self.error
        return self.result

    @property
    def queue_wait_ms(self) -> Optional[float]:
        if self.started_at is None:
            return None
        return (self.started_at - self.enqueued_at) * 1000.0


class PriorityRouter:
    """Loyalty-tiered priority scheduler in front of a pluggable inference handler."""

    def __init__(self, handler: Callable[[dict], Any], workers: int = 2,
                 max_queue: int = 1000) -> None:
        self.handler = handler
        self.max_queue = max_queue
        self._heap: list[_QueueItem] = []
        self._cv = threading.Condition()
        self._counter = itertools.count()
        self._stop = False
        self._workers = [
            threading.Thread(target=self._run, name=f"router-{i}", daemon=True)
            for i in range(workers)
        ]
        for w in self._workers:
            w.start()

    def submit(self, request_id: str, payload: dict, priority: int) -> Ticket:
        """Enqueue a request at the given loyalty priority. Higher served first."""
        ticket = Ticket(request_id=request_id, priority=priority,
                        enqueued_at=time.time())
        with self._cv:
            if len(self._heap) >= self.max_queue:
                raise RuntimeError("router queue full — shed load or scale workers")
            seq = next(self._counter)
            # −priority so larger priority sorts first; seq breaks ties FIFO.
            item = _QueueItem(sort_key=(-priority, seq), ticket=ticket)
            item.ticket._payload = payload  # type: ignore[attr-defined]
            heapq.heappush(self._heap, item)
            self._cv.notify()
        return ticket

    def _run(self) -> None:
        while True:
            with self._cv:
                while not self._heap and not self._stop:
                    self._cv.wait()
                if self._stop and not self._heap:
                    return
                item = heapq.heappop(self._heap)
            ticket = item.ticket
            ticket.started_at = time.time()
            try:
                ticket.result = self.handler(ticket._payload)  # type: ignore[attr-defined]
            except BaseException as e:  # surface upstream errors to the caller
                ticket.error = e
            finally:
                ticket.finished_at = time.time()
                ticket._event.set()

    def pending(self) -> int:
        with self._cv:
            return len(self._heap)

    def shutdown(self) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify_all()
        for w in self._workers:
            w.join(timeout=2.0)
