"""
Signal history ring buffer — newest-first, 200 signals per symbol, 500 global.
Thread-safe. Zero dependencies beyond stdlib.
"""
import time
import threading
from collections import deque

_lock = threading.Lock()
_buffers: dict = {}   # symbol -> deque(maxlen=200)
_global: deque = deque(maxlen=500)


def record(symbol: str, event_type: str, data: dict):
    sym = symbol.upper()
    entry = {
        "symbol":     sym,
        "event_type": event_type,
        "ts":         time.time(),
    }
    for k, v in data.items():
        if k not in entry:
            entry[k] = v
    with _lock:
        if sym not in _buffers:
            _buffers[sym] = deque(maxlen=200)
        _buffers[sym].appendleft(entry)
        _global.appendleft(entry)

    # Auto-settle Signal Futures when a council verdict is recorded
    if event_type == "COUNCIL_VERDICT":
        bias       = data.get("bias", "").upper()
        confidence = int(data.get("confidence", 0))
        if bias:
            try:
                from core.api.futures_bp import auto_settle_for_symbol
                auto_settle_for_symbol(sym, bias, confidence, entry)
            except Exception:
                pass


def get_history(symbol: str, limit: int = 50) -> list:
    with _lock:
        buf = _buffers.get(symbol.upper())
        return list(buf)[:limit] if buf else []


def get_all_recent(limit: int = 100) -> list:
    with _lock:
        return list(_global)[:limit]


def get_symbols() -> list:
    with _lock:
        return sorted(_buffers.keys())
