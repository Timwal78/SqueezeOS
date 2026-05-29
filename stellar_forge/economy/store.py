"""
store.py — durable persistence for the Stellar Forge economy.

Dual backend, one API:
  - SQLite (stdlib) for dev/test and single-node deploys.
  - PostgreSQL (via psycopg, imported lazily) for production — because the
    rebate ledger records REAL RLUSD the protocol owes, and Render's disk is
    ephemeral. Point STELLAR_FORGE_DB at a managed Postgres and the ledger
    survives redeploys. SQLite-on-ephemeral-disk would silently lose who you
    owe; that is the one thing this store exists to prevent.

Backend is chosen from the DSN:
  - "postgres://..." / "postgresql://..."  → Postgres
  - anything else (path or ":memory:")     → SQLite

Money is stored in integer drops (1 RLUSD = 1_000_000 drops) — never floats.

Concurrency: one connection guarded by a lock, which is correct for the
platform's gunicorn profile (1 worker / N threads). For multi-worker Postgres,
swap in a connection pool — the SQL itself is pool-safe.
"""

from __future__ import annotations

import os
import time
import sqlite3
import threading
from contextlib import contextmanager
from typing import Optional, Iterator, Any

DROPS_PER_RLUSD = 1_000_000


def to_drops(rlusd: float) -> int:
    return int(round(rlusd * DROPS_PER_RLUSD))


def to_rlusd(drops: int) -> float:
    return drops / DROPS_PER_RLUSD


def _is_postgres(dsn: str) -> bool:
    return dsn.startswith("postgres://") or dsn.startswith("postgresql://")


# DDL is parameterised over the two dialect differences we actually hit:
# auto-increment primary keys and the float column type.
def _schema(pg: bool) -> str:
    autoinc = "BIGSERIAL PRIMARY KEY" if pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    f64 = "DOUBLE PRECISION" if pg else "REAL"
    return f"""
CREATE TABLE IF NOT EXISTS agents (
    wallet         TEXT PRIMARY KEY,
    referral_code  TEXT UNIQUE NOT NULL,
    referred_by    TEXT,
    created_at     {f64} NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agents_code ON agents(referral_code);
CREATE INDEX IF NOT EXISTS idx_agents_ref  ON agents(referred_by);

CREATE TABLE IF NOT EXISTS settlements (
    settlement_id  TEXT PRIMARY KEY,
    kind           TEXT NOT NULL,
    payer_wallet   TEXT NOT NULL,
    amount_drops   BIGINT NOT NULL,
    fee_drops      BIGINT NOT NULL,
    invoice_id     TEXT,
    state          TEXT NOT NULL,
    created_at     {f64} NOT NULL,
    settled_at     {f64}
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_settle_invoice
    ON settlements(invoice_id) WHERE invoice_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS ledger (
    id             {autoinc},
    ts             {f64} NOT NULL,
    settlement_id  TEXT NOT NULL,
    account        TEXT NOT NULL,
    entry_type     TEXT NOT NULL,
    amount_drops   BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ledger_account ON ledger(account);

-- Idempotent payout tracking (step 2): records RLUSD actually sent on-chain.
CREATE TABLE IF NOT EXISTS payouts (
    id             {autoinc},
    account        TEXT NOT NULL,
    amount_drops   BIGINT NOT NULL,
    paid_through   BIGINT NOT NULL,     -- max ledger.id included in this payout
    state          TEXT NOT NULL,       -- PENDING | SUBMITTED | CONFIRMED | FAILED
    tx_hash        TEXT,
    created_at     {f64} NOT NULL,
    updated_at     {f64} NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_payouts_account ON payouts(account);

-- Sybil control (step 3): registration-rate accounting per source key.
CREATE TABLE IF NOT EXISTS registrations (
    id             {autoinc},
    source         TEXT NOT NULL,       -- ip / fingerprint bucket
    ts             {f64} NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reg_source ON registrations(source);
"""


class Store:
    def __init__(self, dsn: Optional[str] = None) -> None:
        self.dsn = dsn or os.environ.get("STELLAR_FORGE_DB", ":memory:")
        self.is_pg = _is_postgres(self.dsn)
        self._ph = "%s" if self.is_pg else "?"
        self._lock = threading.Lock()

        if self.is_pg:
            import psycopg                     # lazy — only needed for Postgres
            from psycopg.rows import dict_row
            # Pin UTF8 so TEXT columns decode to str (a SQL_ASCII server would
            # otherwise hand back bytes). Render/managed Postgres is UTF8 already.
            self._conn = psycopg.connect(self.dsn, autocommit=False,
                                         row_factory=dict_row, client_encoding="UTF8")
        else:
            self._conn = sqlite3.connect(self.dsn, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")

        self._init_schema()

    # ---- dialect helpers ---------------------------------------------------
    def _q(self, sql: str) -> str:
        """Translate the neutral '?' placeholder to the backend's style."""
        return sql.replace("?", self._ph) if self.is_pg else sql

    def _init_schema(self) -> None:
        ddl = _schema(self.is_pg)
        with self._lock:
            if self.is_pg:
                with self._conn.cursor() as cur:
                    cur.execute(ddl)
            else:
                self._conn.executescript(ddl)
            self._conn.commit()

    @contextmanager
    def _tx(self):
        with self._lock:
            try:
                cur = self._conn.cursor()
                yield cur
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                if self.is_pg:
                    cur.close()

    def _one(self, sql: str, params: tuple = ()) -> Optional[dict]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(self._q(sql), params)
            row = cur.fetchone()
            if self.is_pg:
                cur.close()
            return dict(row) if row is not None else None

    def _all(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(self._q(sql), params)
            rows = cur.fetchall()
            if self.is_pg:
                cur.close()
            return [dict(r) for r in rows]

    # ---- agents ------------------------------------------------------------
    def upsert_agent(self, wallet: str, referral_code: str,
                     referred_by: Optional[str] = None) -> None:
        with self._tx() as cur:
            cur.execute(self._q(
                "INSERT INTO agents(wallet, referral_code, referred_by, created_at) "
                "VALUES(?,?,?,?) ON CONFLICT(wallet) DO NOTHING"),
                (wallet, referral_code, referred_by, time.time()))

    def agent(self, wallet: str) -> Optional[dict]:
        return self._one("SELECT * FROM agents WHERE wallet=?", (wallet,))

    def agent_by_code(self, code: str) -> Optional[dict]:
        return self._one("SELECT * FROM agents WHERE referral_code=?", (code,))

    # ---- settlements -------------------------------------------------------
    def settlement_exists_for_invoice(self, invoice_id: str) -> bool:
        return self._one("SELECT 1 AS x FROM settlements WHERE invoice_id=?",
                         (invoice_id,)) is not None

    def create_settlement(self, settlement_id: str, kind: str, payer_wallet: str,
                          amount_drops: int, fee_drops: int,
                          invoice_id: Optional[str], state: str = "OPEN") -> None:
        with self._tx() as cur:
            cur.execute(self._q(
                "INSERT INTO settlements(settlement_id, kind, payer_wallet, "
                "amount_drops, fee_drops, invoice_id, state, created_at) "
                "VALUES(?,?,?,?,?,?,?,?)"),
                (settlement_id, kind, payer_wallet, amount_drops, fee_drops,
                 invoice_id, state, time.time()))

    def mark_settled(self, settlement_id: str) -> None:
        with self._tx() as cur:
            cur.execute(self._q(
                "UPDATE settlements SET state='SETTLED', settled_at=? WHERE settlement_id=?"),
                (time.time(), settlement_id))

    def settlement(self, settlement_id: str) -> Optional[dict]:
        return self._one("SELECT * FROM settlements WHERE settlement_id=?", (settlement_id,))

    def lifetime_spend(self, wallet: str) -> int:
        """Total settled amount (drops) a wallet has paid — used for sybil gating."""
        row = self._one(
            "SELECT COALESCE(SUM(amount_drops),0) AS s FROM settlements "
            "WHERE payer_wallet=? AND state='SETTLED'", (wallet,))
        return int(row["s"]) if row else 0

    # ---- ledger ------------------------------------------------------------
    def post_ledger(self, settlement_id: str, account: str,
                    entry_type: str, amount_drops: int) -> None:
        with self._tx() as cur:
            cur.execute(self._q(
                "INSERT INTO ledger(ts, settlement_id, account, entry_type, amount_drops) "
                "VALUES(?,?,?,?,?)"),
                (time.time(), settlement_id, account, entry_type, amount_drops))

    def balance(self, account: str) -> int:
        row = self._one(
            "SELECT COALESCE(SUM(amount_drops),0) AS bal FROM ledger WHERE account=?",
            (account,))
        return int(row["bal"]) if row else 0

    def ledger_for(self, account: str, limit: int = 100) -> list[dict]:
        return self._all(
            "SELECT * FROM ledger WHERE account=? ORDER BY id DESC LIMIT ?",
            (account, limit))

    def unpaid_balance(self, account: str, paid_through: int) -> tuple[int, int]:
        """Sum of ledger credits with id > paid_through, plus the new max id.
        This is the basis for an idempotent payout (step 2)."""
        row = self._one(
            "SELECT COALESCE(SUM(amount_drops),0) AS bal, COALESCE(MAX(id),?) AS maxid "
            "FROM ledger WHERE account=? AND id>?",
            (paid_through, account, paid_through))
        return int(row["bal"]), int(row["maxid"])

    # ---- registrations (sybil rate accounting) -----------------------------
    def record_registration(self, source: str) -> None:
        with self._tx() as cur:
            cur.execute(self._q(
                "INSERT INTO registrations(source, ts) VALUES(?,?)"),
                (source, time.time()))

    def registrations_since(self, source: str, since_ts: float) -> int:
        row = self._one(
            "SELECT COUNT(*) AS c FROM registrations WHERE source=? AND ts>=?",
            (source, since_ts))
        return int(row["c"]) if row else 0

    def _truncate_all_for_tests(self) -> None:
        """Clear all rows — TEST ONLY (used to reset a shared Postgres between cases)."""
        with self._tx() as cur:
            for tbl in ("ledger", "payouts", "settlements", "registrations", "agents"):
                cur.execute(f"DELETE FROM {tbl}")

    def close(self) -> None:
        with self._lock:
            self._conn.close()
