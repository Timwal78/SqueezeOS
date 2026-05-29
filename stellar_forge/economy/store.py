"""
store.py — durable persistence for the Stellar Forge economy.

Real SQLite (stdlib, zero external deps, runs anywhere). Swap the DSN for
Postgres in production by setting STELLAR_FORGE_DB to a path; the schema is
plain SQL and portable. This replaces the in-memory MVP dicts so settlements,
referrals, and the rebate ledger survive restarts and are auditable.

Three tables:
  settlements  — every fusion/shard/routing settlement, with payer + referral
  agents       — referral graph (who referred whom) + referral code registry
  ledger       — append-only rebate/fee entries (double-entry-ish, auditable)

All money is stored in integer drops (1 RLUSD = 1_000_000 drops) to avoid
float rounding — the same discipline the rest of the platform should use.
"""

from __future__ import annotations

import os
import time
import sqlite3
import threading
from contextlib import contextmanager
from typing import Optional, Iterator

DROPS_PER_RLUSD = 1_000_000


def to_drops(rlusd: float) -> int:
    return int(round(rlusd * DROPS_PER_RLUSD))


def to_rlusd(drops: int) -> float:
    return drops / DROPS_PER_RLUSD


_SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    wallet         TEXT PRIMARY KEY,
    referral_code  TEXT UNIQUE NOT NULL,
    referred_by    TEXT,                       -- wallet of direct referrer (nullable)
    created_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agents_code ON agents(referral_code);
CREATE INDEX IF NOT EXISTS idx_agents_ref  ON agents(referred_by);

CREATE TABLE IF NOT EXISTS settlements (
    settlement_id  TEXT PRIMARY KEY,
    kind           TEXT NOT NULL,              -- fusion | shard | routing
    payer_wallet   TEXT NOT NULL,
    amount_drops   INTEGER NOT NULL,
    fee_drops      INTEGER NOT NULL,
    invoice_id     TEXT,                       -- 402Proof invoice id (dedup/replay key)
    state          TEXT NOT NULL,              -- OPEN | SETTLED | ABORTED
    created_at     REAL NOT NULL,
    settled_at     REAL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_settle_invoice
    ON settlements(invoice_id) WHERE invoice_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS ledger (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts             REAL NOT NULL,
    settlement_id  TEXT NOT NULL,
    account        TEXT NOT NULL,              -- wallet or 'PROTOCOL'
    entry_type     TEXT NOT NULL,              -- fee | referral_rebate_l1 | referral_rebate_l2
    amount_drops   INTEGER NOT NULL,
    FOREIGN KEY (settlement_id) REFERENCES settlements(settlement_id)
);
CREATE INDEX IF NOT EXISTS idx_ledger_account ON ledger(account);
"""


class Store:
    """Thread-safe SQLite store. One connection guarded by a lock (sufficient
    for a single-worker gunicorn deploy; use Postgres + a pool for multi-worker)."""

    def __init__(self, dsn: Optional[str] = None) -> None:
        self.dsn = dsn or os.environ.get("STELLAR_FORGE_DB", ":memory:")
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.dsn, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    # ----------------------------------------------------------- agents
    def upsert_agent(self, wallet: str, referral_code: str,
                     referred_by: Optional[str] = None) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT INTO agents(wallet, referral_code, referred_by, created_at) "
                "VALUES(?,?,?,?) ON CONFLICT(wallet) DO NOTHING",
                (wallet, referral_code, referred_by, time.time()),
            )

    def agent(self, wallet: str) -> Optional[sqlite3.Row]:
        cur = self._conn.execute("SELECT * FROM agents WHERE wallet=?", (wallet,))
        return cur.fetchone()

    def agent_by_code(self, code: str) -> Optional[sqlite3.Row]:
        cur = self._conn.execute("SELECT * FROM agents WHERE referral_code=?", (code,))
        return cur.fetchone()

    # ------------------------------------------------------- settlements
    def settlement_exists_for_invoice(self, invoice_id: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM settlements WHERE invoice_id=?", (invoice_id,))
        return cur.fetchone() is not None

    def create_settlement(self, settlement_id: str, kind: str, payer_wallet: str,
                          amount_drops: int, fee_drops: int,
                          invoice_id: Optional[str], state: str = "OPEN") -> None:
        with self._tx() as c:
            c.execute(
                "INSERT INTO settlements(settlement_id, kind, payer_wallet, "
                "amount_drops, fee_drops, invoice_id, state, created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (settlement_id, kind, payer_wallet, amount_drops, fee_drops,
                 invoice_id, state, time.time()),
            )

    def mark_settled(self, settlement_id: str) -> None:
        with self._tx() as c:
            c.execute(
                "UPDATE settlements SET state='SETTLED', settled_at=? WHERE settlement_id=?",
                (time.time(), settlement_id),
            )

    def settlement(self, settlement_id: str) -> Optional[sqlite3.Row]:
        cur = self._conn.execute(
            "SELECT * FROM settlements WHERE settlement_id=?", (settlement_id,))
        return cur.fetchone()

    # ------------------------------------------------------------ ledger
    def post_ledger(self, settlement_id: str, account: str,
                    entry_type: str, amount_drops: int) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT INTO ledger(ts, settlement_id, account, entry_type, amount_drops) "
                "VALUES(?,?,?,?,?)",
                (time.time(), settlement_id, account, entry_type, amount_drops),
            )

    def balance(self, account: str) -> int:
        """Sum of ledger credits for an account, in drops."""
        cur = self._conn.execute(
            "SELECT COALESCE(SUM(amount_drops),0) AS bal FROM ledger WHERE account=?",
            (account,))
        return int(cur.fetchone()["bal"])

    def ledger_for(self, account: str, limit: int = 100) -> list[sqlite3.Row]:
        cur = self._conn.execute(
            "SELECT * FROM ledger WHERE account=? ORDER BY id DESC LIMIT ?",
            (account, limit))
        return cur.fetchall()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
