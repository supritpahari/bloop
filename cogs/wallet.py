"""Wallet commands: balance, deposit, withdraw, pay, history, leaderboard."""

import discord
from discord import app_commands
from discord.ext import commands

from economy import config, db as dbm, utils as u


def _balance_embed(user: dict) -> discord.Embed:
    embed = discord.Embed(title=f"{u.GEM} Bloop Account", color=config.BASE_COLOR)
    embed.add_field(name="Wallet", value=f"{u.CURRENCY} **{u.fmt(user['wallet'])}**", inline=True)
    embed.add_field(name="Bank", value=f"{u.CURRENCY} **{u.fmt(user['bank'])}**", inline=True)
    embed.add_field(name="Gems", value=f"{u.GEM} **{u.fmt(user['gems'])}**", inline=True)
    embed.add_field(
        name="Net worth",
        value=f"{u.CURRENCY} **{u.fmt(user['wallet'] + user['bank'])}**",
        inline=False,
    )
    embed.set_footer(text="Keep your wallet light — the raccoons are watching.")
    return embed


class Wallet(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db: dbm.Database = bot.db

    # ------------------------------------------------------------- balance

    async def _balance(self, ctx):
        user = await self.db.get_user(u.user_id_of(ctx))
        await u.reply(ctx, embed=_balance_embed(user))

    @commands.command(name="balance", aliases=["bal", "money"], help="View your wallet, bank, gems and net worth.", usage="b.balance")
    async def balance(self, ctx):
        await self._balance(ctx)

    @app_commands.command(name="balance", description="View your wallet, bank, gems and net worth.")
    async def slash_balance(self, interaction: discord.Interaction):
        await self._balance(interaction)

    # ------------------------------------------------------------- deposit

    async def _deposit(self, ctx, amount: str):
        user_id = u.user_id_of(ctx)
        user = await self.db.get_user(user_id)
        if amount.lower() in ("all", "max"):
            amount = user["wallet"]
        else:
            try:
                amount = int(amount)
            except ValueError:
                await u.reply(ctx, embed=discord.Embed(title="🚫 Invalid amount", description="Use a number, or `all`.", color=0xE11D48))
                return
        if amount <= 0:
            await u.reply(ctx, embed=discord.Embed(title="🚫 Invalid amount", description="Deposit at least 1 coin.", color=0xE11D48))
            return
        try:
            await self.db.move_wallet_to_bank(user_id, amount)
        except dbm.InsufficientFunds:
            await u.reply(ctx, embed=discord.Embed(title="🚫 Not enough coins", description=f"Your wallet only holds {u.fmt(user['wallet'])} {u.CURRENCY}.", color=0xE11D48))
            return
        await u.reply(ctx, embed=discord.Embed(title="🏦 Deposit successful", description=f"Moved {u.CURRENCY} **{u.fmt(amount)}** into your bank.", color=0x22C55E))

    @commands.command(name="deposit", aliases=["dep"], help="Move coins from wallet to bank.", usage="b.deposit <amount|all>")
    async def deposit(self, ctx, amount: str):
        await self._deposit(ctx, amount)

    @app_commands.command(name="deposit", description="Move coins from your wallet into your bank.")
    @app_commands.describe(amount="Amount, or 'all'")
    async def slash_deposit(self, interaction: discord.Interaction, amount: str):
        await self._deposit(interaction, amount)

    # ------------------------------------------------------------- withdraw

    async def _withdraw(self, ctx, amount: str):
        user_id = u.user_id_of(ctx)
        user = await self.db.get_user(user_id)
        if amount.lower() in ("all", "max"):
            amount = user["bank"]
        else:
            try:
                amount = int(amount)
            except ValueError:
                await u.reply(ctx, embed=discord.Embed(title="🚫 Invalid amount", description="Use a number, or `all`.", color=0xE11D48))
                return
        if amount <= 0:
            await u.reply(ctx, embed=discord.Embed(title="🚫 Invalid amount", description="Withdraw at least 1 coin.", color=0xE11D48))
            return
        try:
            await self.db.move_bank_to_wallet(user_id, amount)
        except dbm.InsufficientFunds:
            await u.reply(ctx, embed=discord.Embed(title="🚫 Not enough coins", description=f"Your bank only holds {u.fmt(user['bank'])} {u.CURRENCY}.", color=0xE11D48))
            return
        await u.reply(ctx, embed=discord.Embed(title="🏦 Withdrawal successful", description=f"Moved {u.CURRENCY} **{u.fmt(amount)}** into your wallet.", color=0x22C55E))

    @commands.command(name="withdraw", aliases=["wd"], help="Move coins from bank to wallet.", usage="b.withdraw <amount|all>")
    async def withdraw(self, ctx, amount: str):
        await self._withdraw(ctx, amount)

    @app_commands.command(name="withdraw", description="Move coins from your bank into your wallet.")
    @app_commands.describe(amount="Amount, or 'all'")
    async def slash_withdraw(self, interaction: discord.Interaction, amount: str):
        await self._withdraw(interaction, amount)

    # ------------------------------------------------------------- pay

    async def _pay(self, ctx, member: discord.Member, amount: int):
        user_id = u.user_id_of(ctx)
        if member.id == user_id or member.bot:
            await u.reply(ctx, embed=discord.Embed(title="🚫 Nope", description="You can only pay other human players.", color=0xE11D48))
            return
        if amount <= 0:
            await u.reply(ctx, embed=discord.Embed(title="🚫 Invalid amount", description="Pay at least 1 coin.", color=0xE11D48))
            return
        try:
            await self.db.transfer_coins(user_id, member.id, amount, note="Player transfer")
        except dbm.InsufficientFunds:
            await u.reply(ctx, embed=discord.Embed(title="🚫 Not enough coins", description="Your wallet can't cover that transfer.", color=0xE11D48))
            return
        await u.reply(ctx, embed=discord.Embed(
            title="💸 Transfer complete",
            description=f"You sent {u.CURRENCY} **{u.fmt(amount)}** to {member.mention}.",
            color=0x22C55E,
        ))

    @commands.command(name="pay", aliases=["give"], help="Transfer coins to another user.", usage="b.pay <@user> <amount>")
    async def pay(self, ctx, member: discord.Member, amount: int):
        await self._pay(ctx, member, amount)

    @app_commands.command(name="pay", description="Transfer coins to another user.")
    @app_commands.describe(member="Who receives the coins", amount="How many coins")
    async def slash_pay(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        await self._pay(interaction, member, amount)

    # ------------------------------------------------------------- history

    async def _history(self, ctx):
        rows = await self.db.history(u.user_id_of(ctx), 15)
        if not rows:
            await u.reply(ctx, embed=discord.Embed(title="📜 Ledger", description="No transactions yet. Go earn some coins!", color=config.BASE_COLOR))
            return
        embed = discord.Embed(title="📜 Recent transactions", color=config.BASE_COLOR)
        icons = {"earn": "🟢", "spend": "🔴", "pay": "🔄", "deposit": "🏦", "withdraw": "🏦", "gems": "💎", "market": "🏪", "trade": "🤝"}
        for row in rows[:15]:
            sign = "+" if (row["amount"] or 0) >= 0 else "-"
            value = f"{sign}{u.CURRENCY} {u.fmt(abs(row['amount']))}" if row["amount"] else "—"
            note = row["note"] or row["type"]
            embed.add_field(name=f"{icons.get(row['type'], '📋')} {row['type'].title()}", value=f"{value} — {note}", inline=False)
        await u.reply(ctx, embed=embed)

    @commands.command(name="history", aliases=["ledger"], help="View your recent transactions.", usage="b.history")
    async def history(self, ctx):
        await self._history(ctx)

    @app_commands.command(name="history", description="View your recent transactions.")
    async def slash_history(self, interaction: discord.Interaction):
        await self._history(interaction)

    # ------------------------------------------------------------- leaderboard

    async def _leaderboard(self, ctx, sort: str):
        sort = (sort or "net").lower()
        col = {"wallet": "wallet", "bank": "bank", "net": "(wallet + bank)"}.get(sort, "(wallet + bank)")
        label = {"wallet": "Wallet", "bank": "Bank", "net": "Net worth"}.get(sort, "Net worth")
        rows = await self.db.fetchall(
            f"SELECT user_id, wallet, bank FROM users ORDER BY {col} DESC LIMIT 10"
        )
        if not rows:
            await u.reply(ctx, embed=discord.Embed(title="🏆 Leaderboard", description="Nobody has any coins yet. Be the first!", color=0xF59E0B))
            return
        medals = ["🥇", "🥈", "🥉"]
        embed = discord.Embed(title=f"🏆 Richest by {label}", color=0xF59E0B)
        lines = []
        guild = u.guild_of(ctx)
        for i, row in enumerate(rows):
            member = guild.get_member(row["user_id"]) if guild else None
            name = (member.display_name if member else f"<@{row['user_id']}>")[:24]
            value = (row["wallet"] + row["bank"]) if col == "(wallet + bank)" else row[col]
            lines.append(f"{medals[i] if i < 3 else f'**{i + 1}.**'} **{name}** — {u.CURRENCY} {u.fmt(value)}")
        embed.description = "\n".join(lines)
        my_row = await self.db.fetchone(
            f"SELECT COUNT(*) + 1 AS rank FROM users WHERE (wallet + bank) > (SELECT wallet + bank FROM users WHERE user_id = ?)",
            (u.user_id_of(ctx),),
        )
        embed.set_footer(text=f"Your rank: #{my_row['rank'] if my_row else '?'}")
        await u.reply(ctx, embed=embed)

    @commands.command(name="leaderboard", aliases=["lb", "top"], help="Display the richest users.", usage="b.leaderboard [wallet|bank|net]")
    async def leaderboard(self, ctx, sort: str = "net"):
        await self._leaderboard(ctx, sort)

    @app_commands.command(name="leaderboard", description="Display the richest users.")
    @app_commands.describe(sort="Sort by wallet, bank, or net worth")
    async def slash_leaderboard(self, interaction: discord.Interaction, sort: str = "net"):
        await self._leaderboard(interaction, sort)


async def setup(bot: commands.Bot):
    await bot.add_cog(Wallet(bot))
