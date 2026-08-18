"""Async SQLite layer for the ticket system: per-guild config and ticket state."""

import os

import aiosqlite

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bloop_tickets.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS ticket_config (
    guild_id INTEGER PRIMARY KEY,
    category_id INTEGER,
    support_role_id INTEGER,
    transcript_channel_id INTEGER,
    welcome_message TEXT NOT NULL DEFAULT '',
    counter INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tickets (
    guild_id INTEGER NOT NULL,
    ticket_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL UNIQUE,
    creator_id INTEGER NOT NULL,
    topic TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    claimed_by INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    closed_at TEXT,
    closed_by INTEGER,
    close_reason TEXT,
    PRIMARY KEY (guild_id, ticket_id)
);
"""


class TicketsDB:
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

    # ------------------------------------------------------------ config

    async def get_config(self, guild_id: int) -> dict | None:
        cur = await self.conn.execute(
            "SELECT * FROM ticket_config WHERE guild_id = ?", (guild_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def set_config(
        self,
        guild_id: int,
        *,
        category_id: int | None = None,
        support_role_id: int | None = None,
        transcript_channel_id: int | None = None,
        welcome_message: str | None = None,
    ) -> None:
        """Upsert config fields without clobbering ones that aren't provided."""
        current = await self.get_config(guild_id)
        if current is None:
            current = {"category_id": None, "support_role_id": None,
                       "transcript_channel_id": None, "welcome_message": ""}
        merged = {
            "category_id": category_id if category_id is not None else current["category_id"],
            "support_role_id": support_role_id if support_role_id is not None else current["support_role_id"],
            "transcript_channel_id": (
                transcript_channel_id if transcript_channel_id is not None
                else current["transcript_channel_id"]
            ),
            "welcome_message": welcome_message if welcome_message is not None else current["welcome_message"],
        }
        await self.conn.execute(
            """
            INSERT INTO ticket_config (guild_id, category_id, support_role_id,
                                       transcript_channel_id, welcome_message)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                category_id = excluded.category_id,
                support_role_id = excluded.support_role_id,
                transcript_channel_id = excluded.transcript_channel_id,
                welcome_message = excluded.welcome_message
            """,
            (
                guild_id,
                merged["category_id"],
                merged["support_role_id"],
                merged["transcript_channel_id"],
                merged["welcome_message"],
            ),
        )
        await self.conn.commit()

    # ------------------------------------------------------------ tickets

    async def next_ticket_number(self, guild_id: int) -> int:
        """Atomically reserve and return the next sequential ticket number."""
        await self.conn.execute(
            """
            INSERT INTO ticket_config (guild_id, counter) VALUES (?, 1)
            ON CONFLICT(guild_id) DO UPDATE SET counter = counter + 1
            """,
            (guild_id,),
        )
        await self.conn.commit()
        config = await self.get_config(guild_id)
        return config["counter"]

    async def create_ticket(
        self, guild_id: int, ticket_id: int, channel_id: int, creator_id: int, topic: str = ""
    ) -> None:
        await self.conn.execute(
            "INSERT INTO tickets (guild_id, ticket_id, channel_id, creator_id, topic) VALUES (?, ?, ?, ?, ?)",
            (guild_id, ticket_id, channel_id, creator_id, topic),
        )
        await self.conn.commit()

    async def get_ticket_by_channel(self, channel_id: int) -> dict | None:
        cur = await self.conn.execute(
            "SELECT * FROM tickets WHERE channel_id = ?", (channel_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_open_ticket_by_user(self, guild_id: int, user_id: int) -> dict | None:
        cur = await self.conn.execute(
            "SELECT * FROM tickets WHERE guild_id = ? AND creator_id = ? AND status = 'open'",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def open_tickets(self, guild_id: int) -> list[dict]:
        cur = await self.conn.execute(
            "SELECT * FROM tickets WHERE guild_id = ? AND status = 'open' ORDER BY ticket_id",
            (guild_id,),
        )
        return [dict(row) for row in await cur.fetchall()]

    async def set_claimed(self, channel_id: int, claimed_by: int) -> None:
        await self.conn.execute(
            "UPDATE tickets SET claimed_by = ? WHERE channel_id = ?", (claimed_by, channel_id)
        )
        await self.conn.commit()

    async def close_ticket(self, channel_id: int, closed_by: int, reason: str | None) -> None:
        await self.conn.execute(
            """
            UPDATE tickets
            SET status = 'closed', closed_by = ?, close_reason = ?,
                closed_at = datetime('now')
            WHERE channel_id = ?
            """,
            (closed_by, reason, channel_id),
        )
        await self.conn.commit()

    async def ticket_stats(self, guild_id: int) -> dict:
        cur = await self.conn.execute(
            """
            SELECT
                SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) AS open,
                COUNT(*) AS total
            FROM tickets WHERE guild_id = ?
            """,
            (guild_id,),
        )
        row = await cur.fetchone()
        return {"open": row["open"] or 0, "total": row["total"] or 0}
