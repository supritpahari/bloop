"""Shared helpers: reply abstraction, formatting, XP, multipliers, quests, achievements, events."""

import json
import random
import re
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from . import config
from .db import InsufficientFunds

CURRENCY = "🪙"
GEM = "💎"


# ------------------------------------------------------------------ reply abstraction

def author_of(ctx) -> discord.Member:
    return ctx.author if isinstance(ctx, commands.Context) else ctx.user


def guild_of(ctx) -> discord.Guild:
    return ctx.guild


def user_id_of(ctx) -> int:
    return author_of(ctx).id


async def reply(ctx, *, content: str = None, embed: discord.Embed = None, view=None, ephemeral: bool = False):
    if isinstance(ctx, commands.Context):
        await ctx.send(content=content, embed=embed, view=view)
    else:
        if not ctx.response.is_done():
            await ctx.response.send_message(content=content, embed=embed, view=view, ephemeral=ephemeral)
        else:
            await ctx.followup.send(content=content, embed=embed, view=view, ephemeral=ephemeral)


async def update_message(ctx, *, content: str = None, embed: discord.Embed = None, view=None):
    if isinstance(ctx, commands.Context):
        await ctx.send(content=content, embed=embed, view=view)
    else:
        if ctx.response.is_done():
            await ctx.edit_original_response(content=content, embed=embed, view=view)
        else:
            await ctx.response.send_message(content=content, embed=embed, view=view)


# ------------------------------------------------------------------ formatting

def fmt(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return f"{n:,}"


def fmt_time(seconds: int) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    if s or not parts:
        parts.append(f"{s}s")
    return " ".join(parts)


def rarity_color(rarity: str) -> int:
    return config.RARITY_COLORS.get(rarity, config.BASE_COLOR)


def rarity_emoji(rarity: str) -> str:
    return config.RARITY_EMOJI.get(rarity, "⚪")


def item_display(item_key: str, item: dict) -> str:
    return f"{rarity_emoji(item['rarity'])} {item['emoji']} **{item['name']}**"


def weighted_pick(choices: list) -> any:
    """choices: list of (value, weight)."""
    total = sum(w for _, w in choices)
    roll = random.uniform(0, total)
    acc = 0
    for value, weight in choices:
        acc += weight
        if roll <= acc:
            return value
    return choices[-1][0]


def roll_pool(pool: list, luck: float = 0.0) -> str:
    """Pick an item key from a rarity pool, with luck shifting odds toward rarer items."""
    picks = []
    for key, weight in pool:
        item = config.ITEMS.get(key, {})
        rarity = item.get("rarity", "Common")
        bonus = luck * config.RARITY_ORDER.index(rarity) * 0.35
        picks.append((key, max(weight + bonus, 0.0001)))
    return weighted_pick(picks)


# ------------------------------------------------------------------ XP & levels

def xp_needed(level: int) -> int:
    return int(100 * (level ** 1.35))


def level_from_xp(xp: int) -> int:
    level = 1
    remaining = xp
    while remaining >= xp_needed(level):
        remaining -= xp_needed(level)
        level += 1
    return level


async def grant_xp(db, user_id: int, amount: int) -> list:
    """Add XP, return list of levels gained."""
    user = await db.get_user(user_id)
    xp = user["xp"] + amount
    level = user["level"]
    gained = []
    while xp >= xp_needed(level):
        xp -= xp_needed(level)
        level += 1
        gained.append(level)
        await db.add_gems(user_id, 2, note="Level-up reward")
        await db.try_add_coins(user_id, 100 * level, note="Level-up reward")
    await db.execute(
        "UPDATE users SET xp = ?, level = ? WHERE user_id = ?", (xp, level, user_id)
    )
    return gained


# ------------------------------------------------------------------ multipliers

async def multipliers(db, user_id: int) -> dict:
    """Returns {'income': float, 'luck': float, 'daily': float, 'gamble': float}."""
    user = await db.get_user(user_id)
    income = 1.0 + config.PRESTIGE_BONUS_PER * user["prestige"]
    luck = 0.0
    daily = 1.0
    gamble = 1.0
    pets = await db.pets(user_id)
    active = user.get("active_pet")
    if active and active in pets:
        bonus = config.PETS[active]["bonus"]
        for activity in ("work", "fish", "mine", "hunt", "dig", "gamble", "daily", "luck"):
            income += bonus.get(activity, 0) if activity in ("work", "fish", "mine", "hunt", "dig") else 0
        income += bonus.get("all", 0)
        daily += bonus.get("daily", 0) + bonus.get("all", 0)
        gamble += bonus.get("gamble", 0) + bonus.get("all", 0)
        luck += bonus.get("luck", 0)
    if await db.boost_active(user_id, "coin_magnet"):
        income += 0.25
    if await db.boost_active(user_id, "luck_charm"):
        luck += 0.20
    return {"income": income, "luck": luck, "daily": daily, "gamble": gamble}


async def income_multiplier(db, user_id: int) -> float:
    return (await multipliers(db, user_id))["income"]


async def luck_multiplier(db, user_id: int) -> float:
    return (await multipliers(db, user_id))["luck"]


# ------------------------------------------------------------------ cooldown guard

async def cooldown_error(ctx, remaining: int, action: str) -> bool:
    await reply(ctx, embed=discord.Embed(
        title="⏳ Not so fast!",
        description=f"You can **{action}** again in `{fmt_time(remaining)}`.",
        color=0xE11D48,
    ))
    return True


async def check_cooldown(db, ctx, key: str, seconds: int, action: str) -> bool:
    """Returns True if user is still on cooldown (send error)."""
    remaining = await db.cooldown_remaining(user_id_of(ctx), key)
    if remaining > 0:
        await cooldown_error(ctx, remaining, action)
        return True
    await db.set_cooldown(user_id_of(ctx), key, seconds)
    return False


# ------------------------------------------------------------------ random events

EVENT_TEXT = {
    "meteor": "☄️ A meteorite streaks across the sky and lands near you! The debris scatters **{gems} gems**.",
    "windfall": "🎁 A stranger hands you an envelope 'for being so cheerful'. It contains **{coins} coins**.",
    "thief": "🦝 A raccoon pickpockets you mid-celebration and makes off with **{coins} coins**. You respect the hustle.",
    "item": "📦 You find a small parcel with a note: 'A gift for the hard worker.' Inside: {item}.",
    "lucky": "🌈 A double rainbow appears overhead. Your next catch sparkles just a little brighter.",
}


async def maybe_random_event(db, ctx, user_id: int, income: float) -> list:
    """Roll a random event; returns list of bonus text lines. Called from money commands."""
    if random.random() > config.EVENT_CHANCE:
        return []
    kind = weighted_pick([
        ("meteor", 15), ("windfall", 30), ("thief", 20), ("item", 20), ("lucky", 15),
    ])
    lines = []
    if kind == "meteor":
        gems = random.randint(1, 3)
        await db.add_gems(user_id, gems, note="Meteorite event")
        lines.append(EVENT_TEXT["meteor"].format(gems=gems))
    elif kind == "windfall":
        coins = int(income * random.uniform(0.5, 1.5))
        await db.try_add_coins(user_id, coins, note="Windfall event")
        lines.append(EVENT_TEXT["windfall"].format(coins=fmt(coins)))
    elif kind == "thief":
        coins = int(income * random.uniform(0.3, 0.6))
        try:
            await db.try_remove_coins(user_id, coins, note="Raccoon theft")
            lines.append(EVENT_TEXT["thief"].format(coins=fmt(coins)))
        except InsufficientFunds:
            lines.append("🦝 A raccoon tries to pickpocket you, finds nothing, and stares at you with disappointment.")
    elif kind == "item":
        item_key = random.choice(["comet_dust", "lucky_horseshoe", "gold_ticket", "ancient_tablet", "pet_treat"])
        await db.add_item(user_id, item_key, 1)
        lines.append(EVENT_TEXT["item"].format(item=item_display(item_key, config.ITEMS[item_key])))
    elif kind == "lucky":
        await db.set_boost(user_id, "lucky_moment", 300)
        lines.append(EVENT_TEXT["lucky"])
    return lines


# ------------------------------------------------------------------ quests & achievements

def period_assigned_id(now: datetime) -> tuple:
    """Return (period_id for daily, weekly, monthly)."""
    utc = now.astimezone(timezone.utc)
    daily = utc.strftime("%Y-%m-%d")
    iso = utc.isocalendar()
    weekly = f"{iso[0]}-W{iso[1]:02d}"
    monthly = utc.strftime("%Y-%m")
    return daily, weekly, monthly


async def ensure_quests(db, user_id: int) -> dict:
    """Make sure the player has assigned quests for the current periods. Returns (periods dict)."""
    now = datetime.now(timezone.utc)
    daily, weekly, monthly = period_assigned_id(now)
    db_now = now.strftime("%Y-%m-%d %H:%M:%S")
    for period, qid, pool, count in (
        ("daily", daily, config.DAILY_QUESTS, 3),
        ("weekly", weekly, config.WEEKLY_QUESTS, 2),
        ("monthly", monthly, config.MONTHLY_QUESTS, 1),
    ):
        rows = await db.quests(user_id, period)
        assigned = rows[0]["assigned"] if rows else None
        if assigned != qid:
            keys = random.sample([q["key"] for q in pool], k=min(count, len(pool)))
            await db.execute("DELETE FROM quests WHERE user_id = ? AND period = ?", (user_id, period))
            await db.assign_quests(user_id, period, keys, qid)
    return {"daily": daily, "weekly": weekly, "monthly": monthly}


QUEST_TRACK_MAP = {
    "earn": "earn",
    "work": "work",
    "fish": "fish",
    "mine": "mine",
    "hunt": "hunt",
    "dig": "dig",
    "harvest": "harvest",
    "gamble": "gamble",
    "win": "win",
    "craft": "craft",
    "sell": "sell",
    "legendary": "legendary",
}


async def track_activity(db, user_id: int, action: str, amount: int = 1, legendary: bool = False):
    """Track quest progress + stats. Call from activity commands."""
    await db.bump_stat(user_id, f"{action}_count", amount)
    periods = await ensure_quests(db, user_id)
    track_key = QUEST_TRACK_MAP.get(action)
    if track_key is None:
        return
    for period, qid in (("daily", periods["daily"]), ("weekly", periods["weekly"]), ("monthly", periods["monthly"])):
        await db.bump_quest(user_id, period, track_key, amount)
        if legendary:
            await db.bump_quest(user_id, period, "legendary", amount)


async def track_earn(db, user_id: int, amount: int):
    periods = await ensure_quests(db, user_id)
    for period, qid in (("daily", periods["daily"]), ("weekly", periods["weekly"]), ("monthly", periods["monthly"])):
        await db.bump_quest(user_id, period, "earn", amount)


async def track_gamble(db, user_id: int, won: bool, profit: int):
    await db.bump_stat(user_id, "gambles_placed", 1)
    periods = await ensure_quests(db, user_id)
    for period, qid in (("daily", periods["daily"]), ("weekly", periods["weekly"]), ("monthly", periods["monthly"])):
        await db.bump_quest(user_id, period, "gamble", 1)
        if won:
            await db.bump_quest(user_id, period, "win", 1)
    if won:
        await db.bump_stat(user_id, "gambles_won", 1)
        await db.bump_stat(user_id, "gamble_profit", profit)
        best = await db.get_stat(user_id, "best_gamble_win")
        if profit > best:
            await db.bump_stat(user_id, "best_gamble_win", profit - best)
    else:
        await db.bump_stat(user_id, "gambles_lost", 1)


async def check_achievements(db, user_id: int) -> list:
    """Return list of newly unlocked achievement dicts (with rewards granted)."""
    user = await db.get_user(user_id)
    stats = await db.get_stats(user_id)
    pets = await db.pets(user_id)
    inv = await db.inventory(user_id)
    unlocked = await db.achievements(user_id)
    inventory_count = len(inv) + len(await db.get_tools(user_id))
    streak = (await db.fetchone("SELECT best_daily_streak FROM streaks WHERE user_id = ?", (user_id,)))
    streak_best = streak["best_daily_streak"] if streak else 0
    stats["distinct_items"] = inventory_count
    stats["best_daily_streak"] = streak_best
    stats["pets_adopted"] = len(pets)
    newly = []
    for ach in config.ACHIEVEMENTS:
        if ach["key"] in unlocked:
            continue
        ok = False
        if "level" in ach and user["level"] >= ach["level"]:
            ok = True
        elif "prestige" in ach and user["prestige"] >= ach["prestige"]:
            ok = True
        elif "stat" in ach and stats.get(ach["stat"], 0) >= ach["need"]:
            ok = True
        if not ok:
            continue
        if await db.unlock_achievement(user_id, ach["key"]):
            newly.append(ach)
            if ach["coins"]:
                await db.try_add_coins(user_id, ach["coins"], note=f"Achievement: {ach['name']}")
            if ach["gems"]:
                await db.add_gems(user_id, ach["gems"], note=f"Achievement: {ach['name']}")
            if ach["xp"]:
                await grant_xp(db, user_id, ach["xp"])
            title = config.TITLE_BY_ACHIEVEMENT.get(ach["key"])
            if title and title not in user["titles"]:
                titles = user["titles"] + [title]
                await db.execute(
                    "UPDATE users SET titles = ? WHERE user_id = ?",
                    (json.dumps(titles), user_id),
                )
    return newly


async def add_title(db, user_id: int, title: str) -> None:
    user = await db.get_user(user_id)
    if title in user["titles"]:
        return
    titles = user["titles"] + [title]
    await db.execute(
        "UPDATE users SET titles = ? WHERE user_id = ?",
        (json.dumps(titles), user_id),
    )


async def equip_title(db, user_id: int, title: str) -> bool:
    user = await db.get_user(user_id)
    if title not in user["titles"]:
        return False
    await db.execute("UPDATE users SET equipped_title = ? WHERE user_id = ?", (title, user_id))
    return True


def sanitize_title(raw: str) -> str:
    return re.sub(r"[^\w \-']", "", raw.strip())[:32]
