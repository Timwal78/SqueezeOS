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

CREATE TABLE IF NOT EXISTS tips (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_fid    INTEGER NOT NULL,
    sender_user   TEXT NOT NULL,
    recipient_fid INTEGER,
    recipient_user TEXT NOT NULL,
    amount        REAL NOT NULL,
    fee           REAL NOT NULL DEFAULT 0,
    boost         INTEGER NOT NULL DEFAULT 0,
    tx_hash       TEXT,
    cast_hash     TEXT,
    ts            INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_tips_sender  ON tips(sender_fid, ts);
CREATE INDEX IF NOT EXISTS idx_tips_recipient ON tips(recipient_fid, ts);
CREATE INDEX IF NOT EXISTS idx_tips_ts      ON tips(ts);
"""


async def init_db(db_path: str = DB_PATH) -> None:
    async with aiosqlite.connect(db_path) as db:
        for stmt in _DDL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                await db.execute(stmt)
        await db.commit()


async def register_wallet(fid: int, username: str, wallet: str, db_path: str = DB_PATH) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO fid_wallet (fid, username, wallet)
            VALUES (?, ?, ?)
            ON CONFLICT(fid) DO UPDATE SET username = excluded.username, wallet = excluded.wallet
            """,
            (fid, username.lower(), wallet),
        )
        await db.commit()


async def get_wallet_by_fid(fid: int, db_path: str = DB_PATH) -> Optional[str]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute("SELECT wallet FROM fid_wallet WHERE fid = ?", (fid,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def get_wallet_by_username(username: str, db_path: str = DB_PATH) -> Optional[str]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT wallet FROM fid_wallet WHERE username = ?", (username.lower(),)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def get_fid_by_username(username: str, db_path: str = DB_PATH) -> Optional[int]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT fid FROM fid_wallet WHERE username = ?", (username.lower(),)
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
    db_path: str = DB_PATH,
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO tips
              (sender_fid, sender_user, recipient_fid, recipient_user,
               amount, fee, boost, tx_hash, cast_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (sender_fid, sender_user.lower(), recipient_fid, recipient_user.lower(),
             amount, fee, int(boost), tx_hash, cast_hash),
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
