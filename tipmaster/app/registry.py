import aiosqlite
import os
import time
from typing import Optional, List, Dict

DB_PATH = os.getenv("TIPMASTER_DB_PATH", "tipmaster.db")

_DDL = """
CREATE TABLE IF NOT EXISTS fid_wallet (
    fid        INTEGER PRIMARY KEY,
    username   TEXT NOT NULL,
    wallet     TEXT NOT NULL,
    created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_fid_wallet_username ON fid_wallet(username);

CREATE TABLE IF NOT EXISTS fid_wallet_multi (
    fid        INTEGER,
    chain      TEXT NOT NULL,
    username   TEXT NOT NULL,
    wallet     TEXT NOT NULL,
    created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
    destination_tag INTEGER,
    paid_setup_fee INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(fid, chain)
);
CREATE INDEX IF NOT EXISTS idx_fid_wallet_multi_username ON fid_wallet_multi(username);

CREATE TABLE IF NOT EXISTS tips (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_fid    INTEGER NOT NULL,
    sender_user   TEXT NOT NULL,
    recipient_fid INTEGER,
    recipient_user TEXT NOT NULL,
    amount        REAL NOT NULL,
    currency      TEXT NOT NULL DEFAULT 'RLUSD',
    fee           REAL NOT NULL DEFAULT 0,
    boost         INTEGER NOT NULL DEFAULT 0,
    is_internal   INTEGER NOT NULL DEFAULT 1,
    tx_hash       TEXT,
    cast_hash     TEXT,
    ts            INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_tips_sender  ON tips(sender_fid, ts);
CREATE INDEX IF NOT EXISTS idx_tips_recipient ON tips(recipient_fid, ts);
CREATE INDEX IF NOT EXISTS idx_tips_ts      ON tips(ts);

CREATE TABLE IF NOT EXISTS deposits (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tx_hash       TEXT UNIQUE NOT NULL,
    sender_fid    INTEGER NOT NULL,
    amount        REAL NOT NULL,
    currency      TEXT NOT NULL DEFAULT 'RLUSD',
    ts            INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_deposits_fid ON deposits(sender_fid);

CREATE TABLE IF NOT EXISTS withdrawals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tx_hash       TEXT UNIQUE NOT NULL,
    fid           INTEGER NOT NULL,
    amount        REAL NOT NULL,
    currency      TEXT NOT NULL,
    ts            INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_withdrawals_fid ON withdrawals(fid);
"""


async def init_db(db_path: str = DB_PATH) -> None:
    parent = os.path.dirname(db_path)
    if parent and not os.path.exists(parent):
        try:
            os.makedirs(parent, exist_ok=True)
        except Exception as e:
            print(f"Warning: could not create {parent}: {e}")
            
    async with aiosqlite.connect(db_path) as db:
        for stmt in _DDL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                await db.execute(stmt)
        # Migrate old wallets to new multi-chain table
        await db.execute(
            "INSERT OR IGNORE INTO fid_wallet_multi (fid, chain, username, wallet, created_at) "
            "SELECT fid, 'XRPL', username, wallet, created_at FROM fid_wallet"
        )
        # Add columns to existing tables if they don't exist
        for table, col, default in [
            ("tips", "currency", "'RLUSD'"),
            ("tips", "is_internal", "0"),
            ("deposits", "currency", "'RLUSD'"),
            ("fid_wallet_multi", "destination_tag", "0"),
            ("fid_wallet_multi", "paid_setup_fee", "0")
        ]:
            try:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT NOT NULL DEFAULT {default}")
            except aiosqlite.OperationalError:
                pass
        await db.commit()


async def register_wallet(fid: int, username: str, wallet: str, chain: str = "XRPL", db_path: str = DB_PATH) -> int:
    """Registers wallet and returns the generated destination tag for setup fee."""
    # Generate a unique destination tag based on fid
    dest_tag = fid % 4294967295  # Max 32-bit int for XRPL dest tags
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO fid_wallet_multi (fid, chain, username, wallet, destination_tag, paid_setup_fee)
            VALUES (?, ?, ?, ?, ?, 0)
            ON CONFLICT(fid, chain) DO UPDATE SET username = excluded.username, wallet = excluded.wallet
            """,
            (fid, chain.upper(), username.lower(), wallet, dest_tag),
        )
        await db.commit()
    return dest_tag

async def is_setup_fee_paid(fid: int, db_path: str = DB_PATH) -> bool:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute("SELECT paid_setup_fee FROM fid_wallet_multi WHERE fid = ? LIMIT 1", (fid,)) as cur:
            row = await cur.fetchone()
            return bool(row[0]) if row else False

async def mark_setup_fee_paid(fid: int, db_path: str = DB_PATH) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("UPDATE fid_wallet_multi SET paid_setup_fee = 1 WHERE fid = ?", (fid,))
        await db.commit()


async def get_wallet_by_fid(fid: int, chain: str = "XRPL", db_path: str = DB_PATH) -> Optional[str]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute("SELECT wallet FROM fid_wallet_multi WHERE fid = ? AND chain = ?", (fid, chain.upper())) as cur:
            row = await cur.fetchone()
            return row[0] if row else None

async def get_destination_tag(fid: int, db_path: str = DB_PATH) -> Optional[int]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute("SELECT destination_tag FROM fid_wallet_multi WHERE fid = ? LIMIT 1", (fid,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def get_wallet_by_username(username: str, chain: str = "XRPL", db_path: str = DB_PATH) -> Optional[str]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT wallet FROM fid_wallet_multi WHERE username = ? AND chain = ?", (username.lower(), chain.upper())
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def get_fid_by_username(username: str, db_path: str = DB_PATH) -> Optional[int]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT fid FROM fid_wallet_multi WHERE username = ? LIMIT 1", (username.lower(),)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def get_fid_by_wallet(wallet: str, db_path: str = DB_PATH) -> Optional[int]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT fid FROM fid_wallet_multi WHERE wallet = ? LIMIT 1", (wallet,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def record_tip(
    sender_fid: int,
    sender_user: str,
    recipient_user: str,
    amount: float,
    fee: float,
    boost: bool,
    tx_hash: str,
    cast_hash: str,
    recipient_fid: Optional[int] = None,
    currency: str = "RLUSD",
    is_internal: bool = True,
    db_path: str = DB_PATH,
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO tips
              (sender_fid, sender_user, recipient_fid, recipient_user,
               amount, currency, fee, boost, is_internal, tx_hash, cast_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (sender_fid, sender_user.lower(), recipient_fid, recipient_user.lower(),
             amount, currency.upper(), fee, int(boost), int(is_internal), tx_hash, cast_hash),
        )
        await db.commit()


async def get_tip_stats(fid: int, db_path: str = DB_PATH) -> Dict:
    """Total tips sent + received for a FID, all-time."""
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM tips WHERE sender_fid = ?", (fid,)
        ) as cur:
            sent_count, sent_vol = await cur.fetchone()
        async with db.execute(
            "SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM tips WHERE recipient_fid = ?", (fid,)
        ) as cur:
            recv_count, recv_vol = await cur.fetchone()
    return {
        "sent_count": sent_count,
        "sent_volume": round(float(sent_vol), 6),
        "received_count": recv_count,
        "received_volume": round(float(recv_vol), 6),
    }


async def get_weekly_leaderboard(limit: int = 10, db_path: str = DB_PATH) -> List[Dict]:
    """Top tippers by RLUSD volume in the current calendar week."""
    week_start = int(time.time()) - (7 * 86400)
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """
            SELECT sender_user, COUNT(*) as tip_count, SUM(amount) as volume
            FROM tips
            WHERE ts >= ?
            GROUP BY sender_fid
            ORDER BY volume DESC
            LIMIT ?
            """,
            (week_start, limit),
        ) as cur:
            rows = await cur.fetchall()
    return [
        {"rank": i + 1, "username": row[0], "tip_count": row[1], "volume": round(float(row[2]), 4)}
        for i, row in enumerate(rows)
    ]


async def get_all_time_leaderboard(limit: int = 10, db_path: str = DB_PATH) -> List[Dict]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """
            SELECT sender_user, COUNT(*) as tip_count, SUM(amount) as volume
            FROM tips
            GROUP BY sender_fid
            ORDER BY volume DESC
            LIMIT ?
            """,
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
    return [
        {"rank": i + 1, "username": row[0], "tip_count": row[1], "volume": round(float(row[2]), 4)}
        for i, row in enumerate(rows)
    ]


async def record_deposit(tx_hash: str, sender_fid: int, amount: float, currency: str = "RLUSD", db_path: str = DB_PATH) -> bool:
    """Returns True if inserted, False if duplicate tx_hash."""
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                """
                INSERT INTO deposits (tx_hash, sender_fid, amount, currency)
                VALUES (?, ?, ?, ?)
                """,
                (tx_hash, sender_fid, amount, currency.upper()),
            )
            await db.commit()
            return True
    except aiosqlite.IntegrityError:
        return False

async def record_withdrawal(tx_hash: str, fid: int, amount: float, currency: str = "RLUSD", db_path: str = DB_PATH) -> bool:
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                """
                INSERT INTO withdrawals (tx_hash, fid, amount, currency)
                VALUES (?, ?, ?, ?)
                """,
                (tx_hash, fid, amount, currency.upper()),
            )
            await db.commit()
            return True
    except aiosqlite.IntegrityError:
        return False



