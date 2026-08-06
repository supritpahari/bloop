"""Async SQLite layer for the Bloop economy. Single connection -> writes are serialized."""

import json
import os

import aiosqlite

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bloop_economy.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    wallet INTEGER NOT NULL DEFAULT 0,
    bank INTEGER NOT NULL DEFAULT 0,
    gems INTEGER NOT NULL DEFAULT 0,
    xp INTEGER NOT NULL DEFAULT 0,
    level INTEGER NOT NULL DEFAULT 1,
    prestige INTEGER NOT NULL DEFAULT 0,
    titles TEXT NOT NULL DEFAULT '[]',
    equipped_title TEXT,
    active_pet TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS inventory (
    user_id INTEGER NOT NULL,
    item_key TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, item_key)
);

CREATE TABLE IF NOT EXISTS tools (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    tool_key TEXT NOT NULL,
    durability INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS stats (
    user_id INTEGER NOT NULL,
    stat_key TEXT NOT NULL,
    value INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, stat_key)
);

CREATE TABLE IF NOT EXISTS cooldowns (
    user_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);

CREATE TABLE IF NOT EXISTS streaks (
    user_id INTEGER PRIMARY KEY,
    daily_streak INTEGER NOT NULL DEFAULT 0,
    last_daily TEXT,
    best_daily_streak INTEGER NOT NULL DEFAULT 0,
    weekly_streak INTEGER NOT NULL DEFAULT 0,
    last_weekly TEXT,
    best_weekly_streak INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS quests (
    user_id INTEGER NOT NULL,
    period TEXT NOT NULL,
    quest_key TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    claimed INTEGER NOT NULL DEFAULT 0,
    assigned TEXT NOT NULL,
    PRIMARY KEY (user_id, period, quest_key)
);

CREATE TABLE IF NOT EXISTS achievements (
    user_id INTEGER NOT NULL,
    achievement_key TEXT NOT NULL,
    unlocked_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, achievement_key)
);

CREATE TABLE IF NOT EXISTS pets (
    user_id INTEGER NOT NULL,
    pet_key TEXT NOT NULL,
    xp INTEGER NOT NULL DEFAULT 0,
    level INTEGER NOT NULL DEFAULT 1,
    adopted_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, pet_key)
);

CREATE TABLE IF NOT EXISTS farms (
    user_id INTEGER NOT NULL,
    plot INTEGER NOT NULL,
    crop_key TEXT NOT NULL,
    planted_at TEXT NOT NULL,
    PRIMARY KEY (user_id, plot)
);

CREATE TABLE IF NOT EXISTS market (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id INTEGER NOT NULL,
    item_key TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price_per INTEGER NOT NULL,
    listed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    other_id INTEGER,
    type TEXT NOT NULL,
    amount INTEGER,
    item_key TEXT,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS lottery_entries (
    user_id INTEGER NOT NULL,
    number INTEGER NOT NULL,
    tickets INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, number)
);

CREATE TABLE IF NOT EXISTS lottery_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    pool INTEGER NOT NULL DEFAULT 0,
    next_draw TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS boosts (
    user_id INTEGER NOT NULL,
    boost_key TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    PRIMARY KEY (user_id, boost_key)
);
"""


class InsufficientFunds(Exception):
    pass


class Database:
    def __init__(self, path: str = DB_PATH):
        self.path = path
        self.conn = None

    async def setup(self):
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        await self.conn.execute(
            "INSERT OR IGNORE INTO lottery_meta (id, pool, next_draw) VALUES (1, 0, '1970-01-01 00:00:00')"
        )
        await self.conn.commit()

    async def close(self):
        if self.conn:
            await self.conn.close()

    async def execute(self, sql: str, params: tuple = ()) -> int:
        cur = await self.conn.execute(sql, params)
        await self.conn.commit()
        return cur.lastrowid

    async def execute_many(self, sql: str, seq) -> None:
        await self.conn.executemany(sql, seq)
        await self.conn.commit()

    async def fetchone(self, sql: str, params: tuple = ()):
        cur = await self.conn.execute(sql, params)
        return await cur.fetchone()

    async def fetchall(self, sql: str, params: tuple = ()):
        cur = await self.conn.execute(sql, params)
        return await cur.fetchall()

    # ------------------------------------------------------------------ users

    async def get_user(self, user_id: int) -> dict:
        row = await self.fetchone("SELECT * FROM users WHERE user_id = ?", (user_id,))
        if not row:
            await self.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
            row = await self.fetchone("SELECT * FROM users WHERE user_id = ?", (user_id,))
        d = dict(row)
        d["titles"] = json.loads(d["titles"] or "[]")
        return d

    async def wallet(self, user_id: int) -> int:
        row = await self.fetchone("SELECT wallet FROM users WHERE user_id = ?", (user_id,))
        return row["wallet"] if row else 0

    async def gems(self, user_id: int) -> int:
        row = await self.fetchone("SELECT gems FROM users WHERE user_id = ?", (user_id,))
        return row["gems"] if row else 0

    async def add_gems(self, user_id: int, amount: int, note: str = "") -> None:
        await self.execute("UPDATE users SET gems = gems + ? WHERE user_id = ?", (amount, user_id))
        if note:
            await self.log_tx(user_id, "gems", amount, note=note)

    async def try_remove_gems(self, user_id: int, amount: int, note: str = "") -> None:
        cur = await self.conn.execute(
            "UPDATE users SET gems = gems - ? WHERE user_id = ? AND gems >= ?",
            (amount, user_id, amount),
        )
        await self.conn.commit()
        if cur.rowcount == 0:
            raise InsufficientFunds()
        if note:
            await self.log_tx(user_id, "gems", -amount, note=note)

    async def try_add_coins(self, user_id: int, amount: int, note: str = "") -> None:
        if amount < 0:
            raise ValueError("amount must be positive")
        await self.execute("UPDATE users SET wallet = wallet + ? WHERE user_id = ?", (amount, user_id))
        await self.bump_stat(user_id, "earned_total", amount)
        if note:
            await self.log_tx(user_id, "earn", amount, note=note)

    async def try_remove_coins(self, user_id: int, amount: int, note: str = "") -> None:
        if amount < 0:
            raise ValueError("amount must be positive")
        cur = await self.conn.execute(
            "UPDATE users SET wallet = wallet - ? WHERE user_id = ? AND wallet >= ?",
            (amount, user_id, amount),
        )
        await self.conn.commit()
        if cur.rowcount == 0:
            raise InsufficientFunds()
        await self.bump_stat(user_id, "spent_total", amount)
        if note:
            await self.log_tx(user_id, "spend", -amount, note=note)

    async def transfer_coins(self, from_id: int, to_id: int, amount: int, note: str = "") -> None:
        cur = await self.conn.execute(
            "UPDATE users SET wallet = wallet - ? WHERE user_id = ? AND wallet >= ?",
            (amount, from_id, amount),
        )
        await self.conn.commit()
        if cur.rowcount == 0:
            raise InsufficientFunds()
        await self.execute("UPDATE users SET wallet = wallet + ? WHERE user_id = ?", (amount, to_id))
        await self.log_tx(from_id, "pay", -amount, other_id=to_id, note=note)
        await self.log_tx(to_id, "pay", amount, other_id=from_id, note=note)

    async def move_wallet_to_bank(self, user_id: int, amount: int) -> None:
        cur = await self.conn.execute(
            "UPDATE users SET wallet = wallet - ?, bank = bank + ? "
            "WHERE user_id = ? AND wallet >= ?",
            (amount, amount, user_id, amount),
        )
        await self.conn.commit()
        if cur.rowcount == 0:
            raise InsufficientFunds()
        await self.bump_stat(user_id, "banked_total", amount)
        await self.log_tx(user_id, "deposit", -amount, note="Deposited to bank")

    async def move_bank_to_wallet(self, user_id: int, amount: int) -> None:
        cur = await self.conn.execute(
            "UPDATE users SET bank = bank - ?, wallet = wallet + ? "
            "WHERE user_id = ? AND bank >= ?",
            (amount, amount, user_id, amount),
        )
        await self.conn.commit()
        if cur.rowcount == 0:
            raise InsufficientFunds()
        await self.log_tx(user_id, "withdraw", amount, note="Withdrew from bank")

    async def set_wallet(self, user_id: int, amount: int) -> None:
        await self.execute("UPDATE users SET wallet = ? WHERE user_id = ?", (max(amount, 0), user_id))

    async def set_bank(self, user_id: int, amount: int) -> None:
        await self.execute("UPDATE users SET bank = ? WHERE user_id = ?", (max(amount, 0), user_id))

    # ------------------------------------------------------------------ items

    async def add_item(self, user_id: int, item_key: str, qty: int = 1) -> None:
        await self.execute(
            "INSERT INTO inventory (user_id, item_key, quantity) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, item_key) DO UPDATE SET quantity = quantity + excluded.quantity",
            (user_id, item_key, qty),
        )

    async def remove_item(self, user_id: int, item_key: str, qty: int = 1) -> bool:
        cur = await self.conn.execute(
            "UPDATE inventory SET quantity = quantity - ? "
            "WHERE user_id = ? AND item_key = ? AND quantity >= ?",
            (qty, user_id, item_key, qty),
        )
        await self.conn.commit()
        if cur.rowcount == 0:
            return False
        await self.conn.execute("DELETE FROM inventory WHERE quantity <= 0")
        await self.conn.commit()
        return True

    async def item_count(self, user_id: int, item_key: str) -> int:
        row = await self.fetchone(
            "SELECT quantity FROM inventory WHERE user_id = ? AND item_key = ?",
            (user_id, item_key),
        )
        return row["quantity"] if row else 0

    async def inventory(self, user_id: int) -> dict:
        rows = await self.fetchall(
            "SELECT item_key, quantity FROM inventory WHERE user_id = ? AND quantity > 0",
            (user_id,),
        )
        return {r["item_key"]: r["quantity"] for r in rows}

    async def add_tool(self, user_id: int, tool_key: str, durability: int) -> None:
        await self.execute(
            "INSERT INTO tools (user_id, tool_key, durability) VALUES (?, ?, ?)",
            (user_id, tool_key, durability),
        )

    async def get_tools(self, user_id: int) -> list:
        rows = await self.fetchall(
            "SELECT id, tool_key, durability FROM tools WHERE user_id = ? ORDER BY id", (user_id,)
        )
        return [dict(r) for r in rows]

    async def use_tool_durability(self, tool_id: int) -> int:
        """Decrement durability. Returns remaining durability."""
        cur = await self.conn.execute(
            "UPDATE tools SET durability = durability - 1 WHERE id = ? AND durability > 0",
            (tool_id,),
        )
        await self.conn.commit()
        if cur.rowcount == 0:
            return 0
        row = await self.fetchone("SELECT durability FROM tools WHERE id = ?", (tool_id,))
        return row["durability"] if row else 0

    async def repair_tools(self, user_id: int, amount: int, max_dur: int) -> None:
        await self.conn.execute(
            "UPDATE tools SET durability = MIN(durability + ?, ?) WHERE user_id = ?",
            (amount, max_dur, user_id),
        )
        await self.conn.commit()

    async def remove_tool(self, tool_id: int) -> None:
        await self.execute("DELETE FROM tools WHERE id = ?", (tool_id,))

    # ------------------------------------------------------------------ stats

    async def bump_stat(self, user_id: int, key: str, amount: int = 1) -> None:
        await self.execute(
            "INSERT INTO stats (user_id, stat_key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, stat_key) DO UPDATE SET value = value + excluded.value",
            (user_id, key, amount),
        )

    async def get_stats(self, user_id: int) -> dict:
        rows = await self.fetchall("SELECT stat_key, value FROM stats WHERE user_id = ?", (user_id,))
        return {r["stat_key"]: r["value"] for r in rows}

    async def get_stat(self, user_id: int, key: str) -> int:
        row = await self.fetchone(
            "SELECT value FROM stats WHERE user_id = ? AND stat_key = ?", (user_id, key)
        )
        return row["value"] if row else 0

    # ------------------------------------------------------------------ cooldowns

    async def set_cooldown(self, user_id: int, key: str, seconds: int) -> None:
        await self.execute(
            "INSERT INTO cooldowns (user_id, key, expires_at) VALUES (?, ?, datetime('now', ?)) "
            "ON CONFLICT(user_id, key) DO UPDATE SET expires_at = excluded.expires_at",
            (user_id, key, f"+{seconds} seconds"),
        )

    async def cooldown_remaining(self, user_id: int, key: str) -> int:
        row = await self.fetchone(
            "SELECT CAST((julianday(expires_at) - julianday('now')) * 86400 AS INTEGER) AS rem "
            "FROM cooldowns WHERE user_id = ? AND key = ? AND expires_at > datetime('now')",
            (user_id, key),
        )
        return row["rem"] if row else 0

    async def clear_cooldown(self, user_id: int, key: str) -> None:
        await self.execute("DELETE FROM cooldowns WHERE user_id = ? AND key = ?", (user_id, key))

    async def set_boost(self, user_id: int, boost_key: str, seconds: int) -> None:
        await self.execute(
            "INSERT INTO boosts (user_id, boost_key, expires_at) VALUES (?, ?, datetime('now', ?)) "
            "ON CONFLICT(user_id, boost_key) DO UPDATE SET expires_at = excluded.expires_at",
            (user_id, boost_key, f"+{seconds} seconds"),
        )

    async def boost_active(self, user_id: int, boost_key: str) -> bool:
        row = await self.fetchone(
            "SELECT 1 FROM boosts WHERE user_id = ? AND boost_key = ? AND expires_at > datetime('now')",
            (user_id, boost_key),
        )
        return row is not None

    # ------------------------------------------------------------------ transactions

    async def log_tx(self, user_id: int, tx_type: str, amount: int = 0, *,
                     item_key: str = None, other_id: int = None, note: str = "") -> None:
        await self.execute(
            "INSERT INTO transactions (user_id, other_id, type, amount, item_key, note) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, other_id, tx_type, amount, item_key, note),
        )

    async def history(self, user_id: int, limit: int = 15) -> list:
        rows = await self.fetchall(
            "SELECT * FROM transactions WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ quests

    async def assign_quests(self, user_id: int, period: str, quests: list, assigned: str) -> None:
        for q in quests:
            await self.execute(
                "INSERT OR IGNORE INTO quests (user_id, period, quest_key, assigned) VALUES (?, ?, ?, ?)",
                (user_id, period, q, assigned),
            )

    async def bump_quest(self, user_id: int, period: str, quest_key: str, amount: int = 1) -> None:
        await self.execute(
            "UPDATE quests SET progress = progress + ? "
            "WHERE user_id = ? AND period = ? AND quest_key = ? AND claimed = 0",
            (amount, user_id, period, quest_key),
        )

    async def quests(self, user_id: int, period: str) -> list:
        rows = await self.fetchall(
            "SELECT * FROM quests WHERE user_id = ? AND period = ?", (user_id, period)
        )
        return [dict(r) for r in rows]

    async def claim_quest(self, user_id: int, period: str, quest_key: str) -> bool:
        cur = await self.conn.execute(
            "UPDATE quests SET claimed = 1 WHERE user_id = ? AND period = ? AND quest_key = ? AND claimed = 0",
            (user_id, period, quest_key),
        )
        await self.conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------ achievements

    async def unlock_achievement(self, user_id: int, key: str) -> bool:
        cur = await self.conn.execute(
            "INSERT OR IGNORE INTO achievements (user_id, achievement_key) VALUES (?, ?)",
            (user_id, key),
        )
        await self.conn.commit()
        return cur.rowcount > 0

    async def achievements(self, user_id: int) -> set:
        rows = await self.fetchall(
            "SELECT achievement_key FROM achievements WHERE user_id = ?", (user_id,)
        )
        return {r["achievement_key"] for r in rows}

    # ------------------------------------------------------------------ pets

    async def add_pet(self, user_id: int, pet_key: str) -> bool:
        cur = await self.conn.execute(
            "INSERT OR IGNORE INTO pets (user_id, pet_key) VALUES (?, ?)",
            (user_id, pet_key),
        )
        await self.conn.commit()
        return cur.rowcount > 0

    async def pet_xp(self, user_id: int, pet_key: str, amount: int) -> int:
        await self.execute(
            "UPDATE pets SET xp = xp + ? WHERE user_id = ? AND pet_key = ?",
            (amount, user_id, pet_key),
        )
        row = await self.fetchone(
            "SELECT xp, level FROM pets WHERE user_id = ? AND pet_key = ?", (user_id, pet_key)
        )
        if not row:
            return 0
        need = 100 * (row["level"] ** 1.4)
        if row["xp"] >= need:
            await self.execute(
                "UPDATE pets SET level = level + 1, xp = xp - ? WHERE user_id = ? AND pet_key = ?",
                (int(need), user_id, pet_key),
            )
            return 1
        return 0

    async def pets(self, user_id: int) -> dict:
        rows = await self.fetchall("SELECT * FROM pets WHERE user_id = ?", (user_id,))
        return {r["pet_key"]: {"level": r["level"], "xp": r["xp"]} for r in rows}

    # ------------------------------------------------------------------ farms

    async def plant(self, user_id: int, plot: int, crop_key: str) -> bool:
        cur = await self.conn.execute(
            "INSERT INTO farms (user_id, plot, crop_key, planted_at) VALUES (?, ?, ?, datetime('now')) "
            "ON CONFLICT(user_id, plot) DO UPDATE SET crop_key = excluded.crop_key, planted_at = excluded.planted_at",
            (user_id, plot, crop_key),
        )
        await self.conn.commit()
        return cur.rowcount > 0

    async def harvest(self, user_id: int, plot: int) -> tuple:
        """Harvest a ready plot. Returns (crop_key, planted_at) or None if not ready."""
        row = await self.fetchone(
            "SELECT crop_key, planted_at FROM farms WHERE user_id = ? AND plot = ?",
            (user_id, plot),
        )
        if not row:
            return None
        crop_key, planted = row["crop_key"], row["planted_at"]
        grow = _CROP_GROW.get(crop_key, 0)
        elapsed = await self.fetchone(
            "SELECT CAST((julianday('now') - julianday(?)) * 86400 AS INTEGER) AS s", (planted,)
        )
        if not elapsed or elapsed["s"] < grow:
            return None
        await self.execute("DELETE FROM farms WHERE user_id = ? AND plot = ?", (user_id, plot))
        return (crop_key, elapsed["s"])

    async def farms(self, user_id: int) -> dict:
        rows = await self.fetchall("SELECT * FROM farms WHERE user_id = ?", (user_id,))
        return {r["plot"]: {"crop_key": r["crop_key"], "planted_at": r["planted_at"]} for r in rows}

    # ------------------------------------------------------------------ market

    async def list_item(self, seller_id: int, item_key: str, qty: int, price_per: int) -> None:
        await self.execute(
            "INSERT INTO market (seller_id, item_key, quantity, price_per) VALUES (?, ?, ?, ?)",
            (seller_id, item_key, qty, price_per),
        )

    async def market_listings(self) -> list:
        rows = await self.fetchall("SELECT * FROM market ORDER BY price_per ASC")
        return [dict(r) for r in rows]

    async def market_buy(self, listing_id: int, buyer_id: int, qty: int) -> tuple:
        row = await self.fetchone("SELECT * FROM market WHERE id = ?", (listing_id,))
        if not row:
            return ("gone",)
        if row["quantity"] < qty:
            return ("short",)
        total = row["price_per"] * qty
        cur = await self.conn.execute(
            "UPDATE users SET wallet = wallet - ? WHERE user_id = ? AND wallet >= ?",
            (total, buyer_id, total),
        )
        await self.conn.commit()
        if cur.rowcount == 0:
            return ("funds",)
        await self.conn.execute("UPDATE market SET quantity = quantity - ? WHERE id = ?", (qty, listing_id))
        await self.conn.execute("DELETE FROM market WHERE quantity <= 0")
        await self.conn.commit()
        await self.execute(
            "UPDATE users SET wallet = wallet + ? WHERE user_id = ?",
            (int(total * 0.97), row["seller_id"]),
        )
        await self.add_item(buyer_id, row["item_key"], qty)
        await self.log_tx(buyer_id, "market", -total, item_key=row["item_key"], note="Market purchase")
        await self.log_tx(row["seller_id"], "market", int(total * 0.97), item_key=row["item_key"], note="Market sale")
        return ("ok", row, total)

    async def market_cancel(self, listing_id: int, user_id: int) -> bool:
        row = await self.fetchone("SELECT * FROM market WHERE id = ?", (listing_id,))
        if not row or row["seller_id"] != user_id:
            return False
        await self.execute("DELETE FROM market WHERE id = ?", (listing_id,))
        await self.add_item(user_id, row["item_key"], row["quantity"])
        return True

    # ------------------------------------------------------------------ lottery

    async def lottery_buy(self, user_id: int, number: int, tickets: int) -> bool:
        cur = await self.conn.execute(
            "INSERT INTO lottery_entries (user_id, number, tickets) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, number) DO UPDATE SET tickets = tickets + excluded.tickets",
            (user_id, number, tickets),
        )
        await self.conn.commit()
        return cur.rowcount > 0

    async def lottery_entries(self) -> list:
        rows = await self.fetchall(
            "SELECT user_id, number, SUM(tickets) AS tickets FROM lottery_entries GROUP BY user_id, number"
        )
        return [dict(r) for r in rows]

    async def lottery_clear(self) -> None:
        await self.execute("DELETE FROM lottery_entries")

    async def lottery_pool(self) -> int:
        row = await self.fetchone("SELECT pool FROM lottery_meta WHERE id = 1")
        return row["pool"] if row else 0

    async def lottery_next_draw(self) -> str:
        row = await self.fetchone("SELECT next_draw FROM lottery_meta WHERE id = 1")
        return row["next_draw"] if row else "1970-01-01 00:00:00"

    async def lottery_update(self, pool: int, next_draw: str) -> None:
        await self.execute(
            "UPDATE lottery_meta SET pool = ?, next_draw = ? WHERE id = 1",
            (pool, next_draw),
        )


_CROP_GROW = {}


def init_crop_grow(config_crops: dict) -> None:
    global _CROP_GROW
    _CROP_GROW = {k: v["grow"] for k, v in config_crops.items()}
