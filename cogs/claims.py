"""Claims: daily, weekly, monthly, quests, achievements, prestige, pets, title."""

import json
import random
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from economy import config, db as dbm, utils as u


def _utcnow_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class Claims(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db: dbm.Database = bot.db

    # ------------------------------------------------------------- daily/weekly/monthly

    async def _streak_info(self, user_id: int) -> dict:
        row = await self.db.fetchone("SELECT * FROM streaks WHERE user_id = ?", (user_id,))
        if not row:
            await self.db.execute("INSERT OR IGNORE INTO streaks (user_id) VALUES (?)", (user_id,))
            row = await self.db.fetchone("SELECT * FROM streaks WHERE user_id = ?", (user_id,))
        return dict(row)

    async def _claim_reward(self, ctx, period: str):
        user_id = u.user_id_of(ctx)
        cooldown_key = f"claim:{period}"
        remaining = await self.db.cooldown_remaining(user_id, cooldown_key)
        if remaining > 0:
            await u.cooldown_error(ctx, remaining, f"claim your {period} reward again")
            return
        streak = await self._streak_info(user_id)
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        streak_name = f"{period}_streak"
        last_name = f"last_{period}"
        best_name = f"best_{period}_streak"
        if streak.get(last_name) != today:
            last_date = streak.get(last_name)
            if last_date:
                prev = datetime.strptime(last_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                broken = (now - prev).days > 2 if period == "daily" else (now - prev).days > 9
                if broken:
                    streak[streak_name] = 0
            streak[streak_name] = streak.get(streak_name, 0) + 1
        else:
            streak[streak_name] = streak.get(streak_name, 0)
        streak[best_name] = max(streak.get(best_name, 0), streak[streak_name])
        streak[last_name] = today
        await self.db.execute(
            "UPDATE streaks SET daily_streak = ?, last_daily = ?, best_daily_streak = ?, "
            "weekly_streak = ?, last_weekly = ?, best_weekly_streak = ? WHERE user_id = ?",
            (streak["daily_streak"], streak["last_daily"], streak["best_daily_streak"],
             streak["weekly_streak"], streak["last_weekly"], streak["best_weekly_streak"], user_id),
        )
        mult = await u.multipliers(self.db, user_id)
        daily_mult = mult["daily"]
        if period == "daily":
            base = config.DAILY_BASE + min((streak["daily_streak"] - 1) * config.DAILY_STREAK_BONUS_PER_DAY, config.DAILY_STREAK_CAP)
            coins = int(base * daily_mult * mult["income"])
            xp = 40
            gems = 1 if streak["daily_streak"] % 7 == 0 else 0
            wait = 24 * 3600
        elif period == "weekly":
            coins = int((config.WEEKLY_BASE + (streak["weekly_streak"] - 1) * config.WEEKLY_STREAK_BONUS) * mult["income"])
            xp = 300
            gems = 3
            wait = 7 * 24 * 3600
        else:
            coins = int(config.MONTHLY_BASE * mult["income"])
            xp = 1200
            gems = config.MONTHLY_GEMS
            wait = 30 * 24 * 3600
        await self.db.set_cooldown(user_id, cooldown_key, wait)
        await self.db.try_add_coins(user_id, coins, note=f"{period.title()} reward")
        if gems:
            await self.db.add_gems(user_id, gems, note=f"{period.title()} reward")
        await u.track_earn(self.db, user_id, coins)
        levels = await u.grant_xp(self.db, user_id, xp)
        embed = discord.Embed(
            title={"daily": "☀️ Daily reward claimed!", "weekly": "🗓️ Weekly reward claimed!", "monthly": "🌙 Monthly reward claimed!"}[period],
            color=0x22C55E,
        )
        embed.description = f"You received {u.CURRENCY} **{u.fmt(coins)}**" + (f" and {u.GEM} **{gems}** gems" if gems else "") + "."
        embed.add_field(name="Streak", value=f"**{streak[streak_name]}** day(s) in a row", inline=True)
        if levels:
            embed.add_field(name="🎉 Level up!", value=f"Level **{levels[-1]}**!", inline=True)
        embed.add_field(name="Best streak", value=f"{streak[best_name]}", inline=True)
        achievements = await u.check_achievements(self.db, user_id)
        for ach in achievements:
            embed.add_field(name=f"🏅 Achievement: {ach['name']}", value=ach["desc"], inline=False)
        await u.reply(ctx, embed=embed)

    async def _daily(self, ctx):
        await self._claim_reward(ctx, "daily")

    async def _weekly(self, ctx):
        await self._claim_reward(ctx, "weekly")

    async def _monthly(self, ctx):
        await self._claim_reward(ctx, "monthly")

    @commands.command(name="daily", help="Claim your daily reward with a streak bonus.", usage="b.daily")
    async def daily(self, ctx):
        await self._daily(ctx)

    @commands.command(name="weekly", help="Claim your weekly reward.", usage="b.weekly")
    async def weekly(self, ctx):
        await self._weekly(ctx)

    @commands.command(name="monthly", help="Claim your major monthly reward.", usage="b.monthly")
    async def monthly(self, ctx):
        await self._monthly(ctx)

    @app_commands.command(name="daily", description="Claim your daily reward with a streak bonus.")
    async def slash_daily(self, interaction: discord.Interaction):
        await self._daily(interaction)

    @app_commands.command(name="weekly", description="Claim your weekly reward.")
    async def slash_weekly(self, interaction: discord.Interaction):
        await self._weekly(interaction)

    @app_commands.command(name="monthly", description="Claim your major monthly reward.")
    async def slash_monthly(self, interaction: discord.Interaction):
        await self._monthly(interaction)

    # ------------------------------------------------------------- quests

    def _quest_pool(self, period: str) -> list:
        return {"daily": config.DAILY_QUESTS, "weekly": config.WEEKLY_QUESTS, "monthly": config.MONTHLY_QUESTS}[period]

    def _quest_label(self, q: dict, progress: int) -> str:
        name = q["name"].replace("{target}", str(q["target"]))
        done = progress >= q["target"]
        return f"{'✅' if done else '⏳'} **{name}** — {min(progress, q['target'])}/{q['target']}"

    async def _quests(self, ctx):
        user_id = u.user_id_of(ctx)
        await u.ensure_quests(self.db, user_id)
        embed = discord.Embed(title="🗺️ Quest Board", color=config.BASE_COLOR)
        for period in ("daily", "weekly", "monthly"):
            rows = await self.db.quests(user_id, period)
            pool = self._quest_pool(period)
            pool_map = {q["key"]: q for q in pool}
            lines = []
            for row in rows:
                q = pool_map.get(row["quest_key"])
                if not q:
                    continue
                if row["claimed"]:
                    lines.append(f"✅ ~~{self._quest_label(q, row['progress'])}~~ *(claimed)*")
                else:
                    lines.append(self._quest_label(q, row["progress"]))
            embed.add_field(name=period.title(), value="\n".join(lines) if lines else "No quests.", inline=False)
        embed.set_footer(text="Quests reset: daily at midnight UTC, weekly Monday, monthly on the 1st.")
        await u.reply(ctx, embed=embed)

    async def _claim_quest(self, ctx, period: str, quest_key: str):
        user_id = u.user_id_of(ctx)
        pool = self._quest_pool(period)
        q = next((x for x in pool if x["key"] == quest_key), None)
        if not q:
            await u.reply(ctx, embed=discord.Embed(title="🚫 Unknown quest", color=0xE11D48))
            return
        row = await self.db.fetchone(
            "SELECT progress, claimed FROM quests WHERE user_id = ? AND period = ? AND quest_key = ?",
            (user_id, period, quest_key),
        )
        if not row or row["claimed"]:
            await u.reply(ctx, embed=discord.Embed(title="🚫 Already claimed", color=0xE11D48))
            return
        if row["progress"] < q["target"]:
            await u.reply(ctx, embed=discord.Embed(title="🚫 Not complete yet", description=f"Progress: {row['progress']}/{q['target']}", color=0xE11D48))
            return
        if not await self.db.claim_quest(user_id, period, quest_key):
            await u.reply(ctx, embed=discord.Embed(title="🚫 Already claimed", color=0xE11D48))
            return
        rewards = []
        if q.get("reward_coins"):
            await self.db.try_add_coins(user_id, q["reward_coins"], note=f"Quest: {q['name']}")
            await u.track_earn(self.db, user_id, q["reward_coins"])
            rewards.append(f"{u.CURRENCY} {u.fmt(q['reward_coins'])}")
        if q.get("reward_xp"):
            await u.grant_xp(self.db, user_id, q["reward_xp"])
            rewards.append(f"{u.fmt(q['reward_xp'])} XP")
        if q.get("gems"):
            await self.db.add_gems(user_id, q["gems"], note=f"Quest: {q['name']}")
            rewards.append(f"{u.GEM} {q['gems']}")
        embed = discord.Embed(title=f"🎉 Quest complete!", color=0x22C55E)
        embed.description = f"**{q['name'].replace('{target}', str(q['target']))}**\n\nRewards: " + ", ".join(rewards)
        await u.reply(ctx, embed=embed)

    @commands.command(name="quests", help="Show your active daily, weekly and monthly quests.", usage="b.quests")
    async def quests(self, ctx):
        await self._quests(ctx)

    @commands.command(name="claimquest", help="Claim a completed quest reward.", usage="b.claimquest <daily|weekly|monthly> <quest_key>")
    async def claimquest(self, ctx, period: str, quest_key: str):
        await self._claim_quest(ctx, period, quest_key)

    @app_commands.command(name="quests", description="Show your active daily, weekly and monthly quests.")
    async def slash_quests(self, interaction: discord.Interaction):
        await self._quests(interaction)

    @app_commands.command(name="claimquest", description="Claim a completed quest reward.")
    @app_commands.describe(period="daily, weekly, or monthly", quest_key="The quest key to claim")
    async def slash_claimquest(self, interaction: discord.Interaction, period: str, quest_key: str):
        await self._claim_quest(interaction, period, quest_key)

    # ------------------------------------------------------------- achievements

    async def _achievements(self, ctx):
        user_id = u.user_id_of(ctx)
        unlocked = await self.db.achievements(user_id)
        embed = discord.Embed(title=f"🏅 Achievements ({len(unlocked)}/{len(config.ACHIEVEMENTS)})", color=0xF59E0B)
        for ach in config.ACHIEVEMENTS:
            if ach["key"] in unlocked:
                embed.add_field(name=f"✅ {ach['name']}", value=ach["desc"], inline=True)
            else:
                embed.add_field(name=f"🔒 {ach['name']}", value=ach["desc"], inline=True)
        await u.reply(ctx, embed=embed)

    @commands.command(name="achievements", aliases=["ach"], help="Display your unlocked achievements.", usage="b.achievements")
    async def achievements(self, ctx):
        await self._achievements(ctx)

    @app_commands.command(name="achievements", description="Display your unlocked achievements.")
    async def slash_achievements(self, interaction: discord.Interaction):
        await self._achievements(interaction)

    # ------------------------------------------------------------- pets

    async def _pets(self, ctx):
        user_id = u.user_id_of(ctx)
        owned = await self.db.pets(user_id)
        user = await self.db.get_user(user_id)
        embed = discord.Embed(title="🐾 Pet Stable", color=config.BASE_COLOR)
        if not owned:
            embed.description = "No pets yet! Buy a **Pet Egg** from the shop (`/shop egg`) and hatch it with `/use`."
        for key, info in owned.items():
            pet = config.PETS[key]
            bonus = ", ".join(f"{k}+{v:.0%}" for k, v in pet["bonus"].items() if k != "luck") + (f", luck+{pet['bonus']['luck']:.0%}" if pet["bonus"].get("luck") else "")
            active = "🌟 **equipped**" if user.get("active_pet") == key else ""
            embed.add_field(
                name=f"{pet['emoji']} {pet['name']} (Lv {info['level']}) {active}",
                value=f"{u.rarity_emoji(pet['rarity'])} {pet['rarity']} — bonuses: {bonus}",
                inline=False,
            )
        view = PetView(self.db, user_id, list(owned.keys()), user.get("active_pet"))
        await u.reply(ctx, embed=embed, view=view if owned else None)

    @commands.command(name="pets", help="Manage your pets and equip one for passive bonuses.", usage="b.pets")
    async def pets(self, ctx):
        await self._pets(ctx)

    @app_commands.command(name="pets", description="Manage your pets and equip one for passive bonuses.")
    async def slash_pets(self, interaction: discord.Interaction):
        await self._pets(interaction)

    # ------------------------------------------------------------- title

    async def _title(self, ctx, title: str = None):
        user_id = u.user_id_of(ctx)
        user = await self.db.get_user(user_id)
        if not title:
            embed = discord.Embed(title="👑 Your titles", color=config.BASE_COLOR)
            embed.description = "\n".join(f"- **{t}**" for t in user["titles"]) if user["titles"] else "No titles yet. Earn achievements or buy titles with gems!"
            embed.add_field(name="Equipped", value=user["equipped_title"] or "None")
            embed.set_footer(text="Equip one with: /title <name>")
            await u.reply(ctx, embed=embed)
            return
        if not await u.equip_title(self.db, user_id, title):
            await u.reply(ctx, embed=discord.Embed(title="🚫 Unknown title", description=f"You don't own `{title}`. Check with `/title`.", color=0xE11D48))
            return
        await u.reply(ctx, embed=discord.Embed(title="👑 Title equipped", description=f"You are now known as **{title}**!", color=0x22C55E))

    @commands.command(name="title", help="View your titles or equip one.", usage="b.title [name]")
    async def title(self, ctx, *, title: str = None):
        await self._title(ctx, title)

    @app_commands.command(name="title", description="View your titles or equip one.")
    @app_commands.describe(title="Title to equip (leave empty to list)")
    async def slash_title(self, interaction: discord.Interaction, title: str = None):
        await self._title(interaction, title)

    # ------------------------------------------------------------- prestige

    async def _prestige(self, ctx):
        user_id = u.user_id_of(ctx)
        user = await self.db.get_user(user_id)
        net = user["wallet"] + user["bank"]
        if user["level"] < config.PRESTIGE_LEVEL:
            await u.reply(ctx, embed=discord.Embed(
                title="🚫 Not yet",
                description=f"You must be level **{config.PRESTIGE_LEVEL}** to prestige. You're level {user['level']}.",
                color=0xE11D48,
            ))
            return
        if net < config.PRESTIGE_REQUIRED_NET:
            await u.reply(ctx, embed=discord.Embed(
                title="🚫 Not yet",
                description=f"You need a net worth of {u.CURRENCY} **{u.fmt(config.PRESTIGE_REQUIRED_NET)}** to prestige. You have {u.fmt(net)}.",
                color=0xE11D48,
            ))
            return
        view = PrestigeConfirm(self.db, user_id)
        embed = discord.Embed(title="🔄 Prestige", color=0xEC4899)
        embed.description = (
            "Prestige burns your **coins** and **level** to forge a permanent soul-bonus.\n\n"
            "**You lose:**\n"
            f"• All coins ({u.fmt(net)} {u.CURRENCY})\n"
            "• Level and XP\n"
            "• Quests and farm plots\n\n"
            "**You keep:**\n"
            "• Gems, items, pets, achievements, stats\n\n"
            "**You gain:**\n"
            f"• **+{config.PRESTIGE_BONUS_PER:.0%}** permanent income (stacking per prestige)\n"
            f"• **{config.MONTHLY_GEMS} gems**\n"
            "• Title **The Phoenix** and a Prestige Medallion\n"
            f"• Next prestige requires level {config.PRESTIGE_LEVEL} again — but the climb feels richer."
        )
        await u.reply(ctx, embed=embed, view=view)

    @commands.command(name="prestige", help="Reset progression for permanent bonuses.", usage="b.prestige")
    async def prestige(self, ctx):
        await self._prestige(ctx)

    @app_commands.command(name="prestige", description="Reset progression for permanent bonuses.")
    async def slash_prestige(self, interaction: discord.Interaction):
        await self._prestige(interaction)


class PetView(discord.ui.View):
    def __init__(self, db, user_id: int, pet_keys: list, active: str):
        super().__init__(timeout=90)
        self.db = db
        self.user_id = user_id
        options = [
            discord.SelectOption(label=config.PETS[k]["name"], value=k, emoji=config.PETS[k]["emoji"],
                                 default=(k == active))
            for k in pet_keys
        ]
        select = discord.ui.Select(placeholder="🌟 Equip a pet...", options=options, custom_id="equip_pet")
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not your stable!", ephemeral=True)
            return
        pet_key = interaction.data["values"][0]
        await self.db.execute("UPDATE users SET active_pet = ? WHERE user_id = ?", (pet_key, self.user_id))
        pet = config.PETS[pet_key]
        embed = discord.Embed(title=f"{pet['emoji']} Pet equipped", description=f"**{pet['name']}** now follows you around.", color=0x22C55E)
        await interaction.response.edit_message(embed=embed, view=None)


class PrestigeConfirm(discord.ui.View):
    def __init__(self, db, user_id: int):
        super().__init__(timeout=60)
        self.db = db
        self.user_id = user_id
        yes = discord.ui.Button(label="Burn it all", style=discord.ButtonStyle.danger, emoji="🔥", custom_id="prestige_yes")
        yes.callback = self._yes
        no = discord.ui.Button(label="Not yet", style=discord.ButtonStyle.secondary, emoji="🙈", custom_id="prestige_no")
        no.callback = self._no
        self.add_item(yes)
        self.add_item(no)

    async def _yes(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your prestige!", ephemeral=True)
            return
        user = await self.db.get_user(self.user_id)
        prestige = user["prestige"] + 1
        await self.db.execute("UPDATE users SET level = 1, xp = 0, prestige = ?, wallet = 0, bank = 0 WHERE user_id = ?",
                              (prestige, self.user_id))
        await self.db.add_gems(self.user_id, config.MONTHLY_GEMS, note="Prestige reward")
        await self.db.add_item(self.user_id, "prestige_medallion", 1)
        await u.add_title(self.db, self.user_id, "The Phoenix")
        await self.db.execute("UPDATE users SET equipped_title = 'The Phoenix' WHERE user_id = ?", (self.user_id,))
        await self.db.execute("DELETE FROM quests WHERE user_id = ?", (self.user_id,))
        await self.db.execute("DELETE FROM farms WHERE user_id = ?", (self.user_id,))
        await self.db.execute("DELETE FROM cooldowns WHERE user_id = ?", (self.user_id,))
        embed = discord.Embed(title="🔥 Prestige achieved!", color=0xEC4899)
        embed.description = (
            f"You burn away {u.CURRENCY} **{u.fmt(user['wallet'] + user['bank'])}** and rise again as a **Prestige {prestige}**!\n\n"
            f"• Permanent income bonus: **{config.PRESTIGE_BONUS_PER * prestige:.0%}**\n"
            f"• Gained {u.GEM} **{config.MONTHLY_GEMS}** gems and a Prestige Medallion\n"
            "• Title equipped: **The Phoenix**"
        )
        await interaction.response.edit_message(embed=embed, view=None)

    async def _no(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your prestige!", ephemeral=True)
            return
        await interaction.response.edit_message(content="Prestige cancelled.", embed=None, view=None)


async def setup(bot: commands.Bot):
    await bot.add_cog(Claims(bot))
