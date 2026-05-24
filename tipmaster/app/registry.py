import aiosqlite
import os
from typing import Optional

DB_PATH = os.getenv("TIPMASTER_DB_PATH", "tipmaster.db")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS fid_wallet (
    fid       INTEGER PRIMARY KEY,
    username  TEXT NOT NULL,
    wallet    TEXT NOT NULL,
    created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
)
"""

_CREATE_USERNAME_INDEX = """
CREATE INDEX IF NOT EXISTS idx_fid_wallet_username ON fid_wallet(username)
"""


async def init_db(db_path: str = DB_PATH) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(_CREATE_TABLE)
        await db.execute(_CREATE_USERNAME_INDEX)
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
        async with db.execute(
            "SELECT wallet FROM fid_wallet WHERE fid = ?", (fid,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def get_wallet_by_username(username: str, db_path: str = DB_PATH) -> Optional[str]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT wallet FROM fid_wallet WHERE username = ?", (username.lower(),)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def get_fid_by_username(username: str, db_path: str = DB_PATH) -> Optional[int]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT fid FROM fid_wallet WHERE username = ?", (username.lower(),)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None
