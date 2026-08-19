"""Persistent SQLite storage for giveaways, entries, winners, and reroll history."""

import asyncio
import json
import os
from datetime import datetime, timezone

import aiosqlite

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bloop_giveaways.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS giveaways (
    giveaway_id TEXT PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER,
    host_id INTEGER NOT NULL,
    prize TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    winners_count INTEGER NOT NULL DEFAULT 1,
    start_time INTEGER NOT NULL,
    end_time INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','ending','ended','cancelled')),
    winner_ids TEXT NOT NULL DEFAULT '[]',
    requirements TEXT NOT NULL DEFAULT '{}',
    bonus_entries TEXT NOT NULL DEFAULT '{}',
    settings TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    ended_at INTEGER,
    cancelled_at INTEGER,
    message_dirty INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_giveaways_guild_status ON giveaways(guild_id, status);
CREATE INDEX IF NOT EXISTS idx_giveaways_expiry ON giveaways(status, end_time);
CREATE UNIQUE INDEX IF NOT EXISTS idx_giveaways_message ON giveaways(message_id) WHERE message_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS giveaway_entries (
    giveaway_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    base_entries INTEGER NOT NULL DEFAULT 1,
    bonus_entries INTEGER NOT NULL DEFAULT 0,
    entered_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (giveaway_id, user_id),
    FOREIGN KEY (giveaway_id) REFERENCES giveaways(giveaway_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_entries_giveaway ON giveaway_entries(giveaway_id);

CREATE TABLE IF NOT EXISTS giveaway_winners (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    giveaway_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    round INTEGER NOT NULL DEFAULT 0,
    selected_at INTEGER NOT NULL,
    FOREIGN KEY (giveaway_id) REFERENCES giveaways(giveaway_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_winners_giveaway ON giveaway_winners(giveaway_id, round);
"""

JSON_FIELDS = ("winner_ids", "requirements", "bonus_entries", "settings")


def utc_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


class GiveawaysDB:
    """Single-connection store with locks around multi-statement state changes."""

    def __init__(self, path: str = DB_PATH):
        self.path = path
        self.conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def setup(self):
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA foreign_keys=ON")
        await self.conn.execute("PRAGMA journal_mode=DELETE")
        await self.conn.execute("PRAGMA synchronous=NORMAL")
        await self.conn.execute("PRAGMA busy_timeout=5000")
        await self.conn.executescript(SCHEMA)
        # Lightweight forward migration for databases created before the
        # reliable message-reconciliation flag was introduced.
        columns = await self.conn.execute("PRAGMA table_info(giveaways)")
        names = {row[1] for row in await columns.fetchall()}
        if "message_dirty" not in names:
            await self.conn.execute(
                "ALTER TABLE giveaways ADD COLUMN message_dirty INTEGER NOT NULL DEFAULT 1"
            )
        await self.conn.commit()

    async def close(self):
        if self.conn:
            await self.conn.close()
            self.conn = None

    @staticmethod
    def _decode(row) -> dict | None:
        if row is None:
            return None
        result = dict(row)
        for field in JSON_FIELDS:
            try:
                result[field] = json.loads(result.get(field) or ("[]" if field == "winner_ids" else "{}"))
            except (TypeError, json.JSONDecodeError):
                result[field] = [] if field == "winner_ids" else {}
        return result

    async def create(self, data: dict) -> None:
        now = utc_ts()
        await self.conn.execute(
            """INSERT INTO giveaways
            (giveaway_id,guild_id,channel_id,message_id,host_id,prize,description,
             winners_count,start_time,end_time,status,winner_ids,requirements,
             bonus_entries,settings,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,'active','[]',?,?,?,?,?)""",
            (
                data["giveaway_id"], data["guild_id"], data["channel_id"],
                data.get("message_id"), data["host_id"], data["prize"],
                data.get("description", ""), data["winners_count"], data["start_time"],
                data["end_time"], json.dumps(data.get("requirements", {})),
                json.dumps(data.get("bonus_entries", {})), json.dumps(data.get("settings", {})),
                now, now,
            ),
        )
        await self.conn.commit()

    async def set_message_id(self, giveaway_id: str, message_id: int) -> None:
        await self.conn.execute(
            "UPDATE giveaways SET message_id=?, updated_at=? WHERE giveaway_id=?",
            (message_id, utc_ts(), giveaway_id),
        )
        await self.conn.commit()

    async def mark_message_synced(self, giveaway_id: str) -> None:
        await self.conn.execute(
            "UPDATE giveaways SET message_dirty=0 WHERE giveaway_id=?", (giveaway_id,)
        )
        await self.conn.commit()

    async def dirty_messages(self, limit: int = 50) -> list[dict]:
        cur = await self.conn.execute(
            "SELECT * FROM giveaways WHERE message_dirty=1 AND message_id IS NOT NULL ORDER BY updated_at LIMIT ?",
            (limit,),
        )
        return [self._decode(row) for row in await cur.fetchall()]

    async def get(self, giveaway_id: str, guild_id: int | None = None) -> dict | None:
        sql, params = "SELECT * FROM giveaways WHERE giveaway_id=?", [giveaway_id.upper()]
        if guild_id is not None:
            sql += " AND guild_id=?"
            params.append(guild_id)
        cur = await self.conn.execute(sql, tuple(params))
        return self._decode(await cur.fetchone())

    async def get_by_message(self, message_id: int, guild_id: int) -> dict | None:
        cur = await self.conn.execute(
            "SELECT * FROM giveaways WHERE message_id=? AND guild_id=?", (message_id, guild_id)
        )
        return self._decode(await cur.fetchone())

    async def list_guild(self, guild_id: int, status: str | None = None, limit: int = 1000, offset: int = 0) -> list[dict]:
        params: list = [guild_id]
        sql = "SELECT * FROM giveaways WHERE guild_id=?"
        if status:
            sql += " AND status=?"
            params.append(status)
        sql += " ORDER BY CASE WHEN status='active' THEN 0 ELSE 1 END, created_at DESC LIMIT ? OFFSET ?"
        params.extend((limit, offset))
        cur = await self.conn.execute(sql, tuple(params))
        return [self._decode(r) for r in await cur.fetchall()]

    async def expired(self, now: int, limit: int = 50) -> list[dict]:
        cur = await self.conn.execute(
            "SELECT * FROM giveaways WHERE status='active' AND end_time<=? ORDER BY end_time LIMIT ?",
            (now, limit),
        )
        return [self._decode(r) for r in await cur.fetchall()]

    async def update(self, giveaway_id: str, guild_id: int, changes: dict) -> bool:
        allowed = {"prize", "description", "winners_count", "end_time", "requirements", "bonus_entries", "settings", "channel_id"}
        values, params = [], []
        for key, value in changes.items():
            if key not in allowed:
                continue
            values.append(f"{key}=?")
            params.append(json.dumps(value) if key in JSON_FIELDS else value)
        if not values:
            return False
        values.extend(("updated_at=?", "message_dirty=1"))
        params.extend((utc_ts(), giveaway_id.upper(), guild_id))
        cur = await self.conn.execute(
            f"UPDATE giveaways SET {', '.join(values)} WHERE giveaway_id=? AND guild_id=? AND status='active'",
            tuple(params),
        )
        await self.conn.commit()
        return cur.rowcount > 0

    async def claim_for_end(self, giveaway_id: str, guild_id: int) -> dict | None:
        """Atomically move active -> ending; only one scheduler/command can win."""
        async with self._lock:
            cur = await self.conn.execute(
                "UPDATE giveaways SET status='ending',updated_at=? WHERE giveaway_id=? AND guild_id=? AND status='active'",
                (utc_ts(), giveaway_id.upper(), guild_id),
            )
            await self.conn.commit()
            if cur.rowcount == 0:
                return None
            return await self.get(giveaway_id, guild_id)

    async def finish_end(self, giveaway_id: str, winner_ids: list[int]) -> None:
        now = utc_ts()
        async with self._lock:
            cur = await self.conn.execute(
                "SELECT COALESCE(MAX(round),-1)+1 AS round FROM giveaway_winners WHERE giveaway_id=?",
                (giveaway_id,),
            )
            round_no = int((await cur.fetchone())["round"])
            await self.conn.executemany(
                "INSERT INTO giveaway_winners(giveaway_id,user_id,round,selected_at) VALUES(?,?,?,?)",
                [(giveaway_id, uid, round_no, now) for uid in winner_ids],
            )
            await self.conn.execute(
                "UPDATE giveaways SET status='ended',winner_ids=?,ended_at=?,updated_at=?,message_dirty=1 WHERE giveaway_id=? AND status='ending'",
                (json.dumps(winner_ids), now, now, giveaway_id),
            )
            await self.conn.commit()

    async def restore_active(self, giveaway_id: str) -> None:
        await self.conn.execute(
            "UPDATE giveaways SET status='active',updated_at=? WHERE giveaway_id=? AND status='ending'",
            (utc_ts(), giveaway_id),
        )
        await self.conn.commit()

    async def cancel(self, giveaway_id: str, guild_id: int) -> bool:
        now = utc_ts()
        cur = await self.conn.execute(
            "UPDATE giveaways SET status='cancelled',cancelled_at=?,updated_at=?,message_dirty=1 WHERE giveaway_id=? AND guild_id=? AND status='active'",
            (now, now, giveaway_id.upper(), guild_id),
        )
        await self.conn.commit()
        return cur.rowcount > 0

    async def add_entry(self, giveaway_id: str, user_id: int, bonus: int, allow_multiple: bool, maximum: int) -> tuple[str, dict | None]:
        """Atomically add/increment an entry. Bonus is recorded once, never per click."""
        now = utc_ts()
        async with self._lock:
            cur = await self.conn.execute(
                "SELECT status,end_time FROM giveaways WHERE giveaway_id=?", (giveaway_id,)
            )
            giveaway = await cur.fetchone()
            if giveaway is None or giveaway["status"] != "active" or int(giveaway["end_time"]) <= now:
                return "inactive", None
            cur = await self.conn.execute(
                "SELECT base_entries,bonus_entries FROM giveaway_entries WHERE giveaway_id=? AND user_id=?",
                (giveaway_id, user_id),
            )
            row = await cur.fetchone()
            if row:
                if not allow_multiple:
                    return "exists", dict(row)
                if int(row["base_entries"]) >= maximum:
                    return "maximum", dict(row)
                await self.conn.execute(
                    "UPDATE giveaway_entries SET base_entries=base_entries+1,updated_at=? WHERE giveaway_id=? AND user_id=?",
                    (now, giveaway_id, user_id),
                )
            else:
                await self.conn.execute(
                    "INSERT INTO giveaway_entries(giveaway_id,user_id,base_entries,bonus_entries,entered_at,updated_at) VALUES(?,?,1,?,?,?)",
                    (giveaway_id, user_id, max(0, bonus), now, now),
                )
            await self.conn.execute(
                "UPDATE giveaways SET message_dirty=1,updated_at=? WHERE giveaway_id=?",
                (now, giveaway_id),
            )
            await self.conn.commit()
            cur = await self.conn.execute(
                "SELECT * FROM giveaway_entries WHERE giveaway_id=? AND user_id=?", (giveaway_id, user_id)
            )
            return "added", dict(await cur.fetchone())

    async def entries(self, giveaway_id: str) -> list[dict]:
        cur = await self.conn.execute(
            "SELECT * FROM giveaway_entries WHERE giveaway_id=? ORDER BY entered_at", (giveaway_id,)
        )
        return [dict(r) for r in await cur.fetchall()]

    async def entry(self, giveaway_id: str, user_id: int) -> dict | None:
        cur = await self.conn.execute(
            "SELECT * FROM giveaway_entries WHERE giveaway_id=? AND user_id=?", (giveaway_id, user_id)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def counts(self, giveaway_id: str) -> dict:
        cur = await self.conn.execute(
            "SELECT COUNT(*) AS users,COALESCE(SUM(base_entries+bonus_entries),0) AS entries FROM giveaway_entries WHERE giveaway_id=?",
            (giveaway_id,),
        )
        row = await cur.fetchone()
        return {"users": int(row["users"]), "entries": int(row["entries"])}

    async def winner_history(self, giveaway_id: str) -> list[dict]:
        cur = await self.conn.execute(
            "SELECT * FROM giveaway_winners WHERE giveaway_id=? ORDER BY round,id", (giveaway_id,)
        )
        return [dict(r) for r in await cur.fetchall()]

    async def record_reroll(self, giveaway_id: str, winner_ids: list[int]) -> int:
        now = utc_ts()
        async with self._lock:
            cur = await self.conn.execute(
                "SELECT COALESCE(MAX(round),-1)+1 AS round FROM giveaway_winners WHERE giveaway_id=?",
                (giveaway_id,),
            )
            round_no = int((await cur.fetchone())["round"])
            await self.conn.executemany(
                "INSERT INTO giveaway_winners(giveaway_id,user_id,round,selected_at) VALUES(?,?,?,?)",
                [(giveaway_id, uid, round_no, now) for uid in winner_ids],
            )
            await self.conn.execute(
                "UPDATE giveaways SET winner_ids=?,updated_at=?,message_dirty=1 WHERE giveaway_id=?",
                (json.dumps(winner_ids), now, giveaway_id),
            )
            await self.conn.commit()
            return round_no

    async def statistics(self, guild_id: int) -> dict:
        cur = await self.conn.execute(
            """SELECT COUNT(*) total,
            SUM(status='active') active,SUM(status='ended') completed,SUM(status='cancelled') cancelled
            FROM giveaways WHERE guild_id=?""", (guild_id,)
        )
        base = dict(await cur.fetchone())
        cur = await self.conn.execute(
            "SELECT COUNT(*) participants FROM giveaway_entries e JOIN giveaways g USING(giveaway_id) WHERE g.guild_id=?",
            (guild_id,),
        )
        base.update(dict(await cur.fetchone()))
        cur = await self.conn.execute(
            "SELECT COUNT(*) winners FROM giveaway_winners w JOIN giveaways g USING(giveaway_id) WHERE g.guild_id=?",
            (guild_id,),
        )
        base.update(dict(await cur.fetchone()))
        cur = await self.conn.execute(
            """SELECT g.giveaway_id,g.prize,COUNT(e.user_id) participants FROM giveaways g
            LEFT JOIN giveaway_entries e USING(giveaway_id) WHERE g.guild_id=?
            GROUP BY g.giveaway_id ORDER BY participants DESC LIMIT 1""", (guild_id,)
        )
        popular = await cur.fetchone()
        base["most_successful"] = dict(popular) if popular else None
        cur = await self.conn.execute(
            "SELECT prize,COUNT(*) uses FROM giveaways WHERE guild_id=? GROUP BY lower(prize) ORDER BY uses DESC LIMIT 5",
            (guild_id,),
        )
        base["popular_prizes"] = [dict(r) for r in await cur.fetchall()]
        cur = await self.conn.execute(
            """SELECT strftime('%Y-%m-%d',entered_at,'unixepoch') day,COUNT(*) participants
            FROM giveaway_entries e JOIN giveaways g USING(giveaway_id) WHERE g.guild_id=?
            GROUP BY day ORDER BY day DESC LIMIT 14""", (guild_id,),
        )
        base["timeline"] = [dict(r) for r in await cur.fetchall()][::-1]
        return base
