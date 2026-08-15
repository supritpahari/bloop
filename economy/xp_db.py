"""Async SQLite layer for XP and level tracking."""

import os

import aiosqlite

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bloop_xp.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS xp_users (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    xp INTEGER NOT NULL DEFAULT 0,
    level INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS guild_welcome (
    guild_id INTEGER PRIMARY KEY,
    channel_id INTEGER,
    message_template TEXT NOT NULL DEFAULT "Welcome {mention} to {guild}!"
);

CREATE TABLE IF NOT EXISTS guild_leave (
    guild_id INTEGER PRIMARY KEY,
    channel_id INTEGER,
    message_template TEXT NOT NULL DEFAULT "Goodbye {mention}! Thanks for being here."
);
"""


class XPDB:
    def __init__(self):
        self.path = DB_PATH
        self.conn = None

    async def setup(self):
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=DELETE")
        await self.conn.execute("PRAGMA synchronous=NORMAL")
        await self.conn.execute("PRAGMA temp_store=MEMORY")
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    async def close(self):
        if self.conn:
            await self.conn.close()

    async def get_user(self, guild_id: int, user_id: int):
        cur = await self.conn.execute(
            "SELECT * FROM xp_users WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        )
        row = await cur.fetchone()
        if row is None:
            await self.conn.execute(
                "INSERT INTO xp_users (guild_id, user_id, xp, level) VALUES (?, ?, 0, 1)",
                (guild_id, user_id)
            )
            await self.conn.commit()
            cur = await self.conn.execute(
                "SELECT * FROM xp_users WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
            )
            row = await cur.fetchone()
        return dict(row) if row else {"xp": 0, "level": 1}

    async def add_xp(self, guild_id: int, user_id: int, amount: int = 10) -> dict:
        await self.conn.execute(
            "INSERT OR IGNORE INTO xp_users (guild_id, user_id, xp, level) VALUES (?, ?, 0, 1)",
            (guild_id, user_id)
        )
        await self.conn.execute(
            "UPDATE xp_users SET xp = xp + ? WHERE guild_id = ? AND user_id = ?",
            (amount, guild_id, user_id)
        )
        await self.conn.commit()
        return await self.get_user(guild_id, user_id)

    async def set_level(self, guild_id: int, user_id: int, level: int):
        await self.conn.execute(
            "UPDATE xp_users SET level = ? WHERE guild_id = ? AND user_id = ?",
            (level, guild_id, user_id)
        )
        await self.conn.commit()

    async def get_welcome(self, guild_id: int):
        cur = await self.conn.execute(
            "SELECT * FROM guild_welcome WHERE guild_id = ?", (guild_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def set_welcome(self, guild_id: int, channel_id: int = None, message_template: str = ""):
        await self.conn.execute(
            "INSERT OR REPLACE INTO guild_welcome (guild_id, channel_id, message_template) VALUES (?, ?, ?)",
            (guild_id, channel_id, message_template or "Welcome {mention} to {guild}!")
        )
        await self.conn.commit()

    async def get_leave(self, guild_id: int):
        cur = await self.conn.execute(
            "SELECT * FROM guild_leave WHERE guild_id = ?", (guild_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def set_leave(self, guild_id: int, channel_id: int = None, message_template: str = ""):
        await self.conn.execute(
            "INSERT OR REPLACE INTO guild_leave (guild_id, channel_id, message_template) VALUES (?, ?, ?)",
            (guild_id, channel_id, message_template or "Goodbye {mention}! Thanks for being here.")
        )
        await self.conn.commit()
