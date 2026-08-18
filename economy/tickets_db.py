"""Async SQLite layer for the ticket system: setup config and ticket state."""

import json
import os

import aiosqlite

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bloop_tickets.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS ticket_setup (
    guild_id INTEGER PRIMARY KEY,
    panel_channel_id INTEGER,
    category_id INTEGER,
    role_ids TEXT NOT NULL DEFAULT '[]',
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

    # ------------------------------------------------------------ setup

    async def get_setup(self, guild_id: int) -> dict | None:
        """Guild ticket config; `role_ids` is returned as a parsed list of ints."""
        cur = await self.conn.execute(
            "SELECT * FROM ticket_setup WHERE guild_id = ?", (guild_id,)
        )
        row = await cur.fetchone()
        if row is None:
            return None
        cfg = dict(row)
        try:
            cfg["role_ids"] = [int(r) for r in json.loads(cfg.get("role_ids") or "[]")]
        except (TypeError, ValueError):
            cfg["role_ids"] = []
        return cfg

    async def set_setup(
        self,
        guild_id: int,
        *,
        panel_channel_id: int | None = None,
        category_id: int | None = None,
        role_ids: list[int] | None = None,
    ) -> None:
        """Upsert setup fields without clobbering ones that aren't provided."""
        current = await self.get_setup(guild_id)
        if current is None:
            current = {"panel_channel_id": None, "category_id": None, "role_ids": []}
        await self.conn.execute(
            """
            INSERT INTO ticket_setup (guild_id, panel_channel_id, category_id, role_ids)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                panel_channel_id = excluded.panel_channel_id,
                category_id = excluded.category_id,
                role_ids = excluded.role_ids
            """,
            (
                guild_id,
                panel_channel_id if panel_channel_id is not None else current["panel_channel_id"],
                category_id if category_id is not None else current["category_id"],
                json.dumps(role_ids if role_ids is not None else current["role_ids"]),
            ),
        )
        await self.conn.commit()

    async def next_ticket_number(self, guild_id: int) -> int:
        """Atomically reserve and return the next sequential ticket number."""
        await self.conn.execute(
            """
            INSERT INTO ticket_setup (guild_id, counter) VALUES (?, 1)
            ON CONFLICT(guild_id) DO UPDATE SET counter = counter + 1
            """,
            (guild_id,),
        )
        await self.conn.commit()
        cfg = await self.get_setup(guild_id)
        return cfg["counter"]

    # ------------------------------------------------------------ tickets

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

    async def close_ticket(self, channel_id: int, closed_by: int | None, reason: str | None) -> None:
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
