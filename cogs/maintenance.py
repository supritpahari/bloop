"""Database health and maintenance commands."""

import discord
from discord import app_commands
from discord.ext import commands

from economy import config, utils as u


class Maintenance(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    async def _dbinfo(self, ctx):
        info = await self.db.info()
        disk = await self.db.disk_usage()
        embed = discord.Embed(title="🗄️ Database health", color=config.BASE_COLOR)
        embed.add_field(name="File", value=f"`{info['path']}`", inline=False)
        embed.add_field(name="Database size", value=f"**{info['size'] / 1024 / 1024:.2f} MB**", inline=True)
        embed.add_field(name="WAL/journal size", value=f"**{info['wal_size'] / 1024 / 1024:.2f} MB**", inline=True)
        embed.add_field(
            name="Disk (DB filesystem)",
            value=f"**{disk['free'] / 1024 / 1024 / 1024:.1f} GB free** of {disk['total'] / 1024 / 1024 / 1024:.1f} GB ({disk['percent']}% used)",
            inline=True,
        )
        biggest = sorted(info["tables"].items(), key=lambda kv: kv[1], reverse=True)[:5]
        embed.add_field(
            name="Largest tables",
            value="\n".join(f"`{k}` — {v:,} rows" for k, v in biggest),
            inline=False,
        )
        embed.set_footer(text="Disk errors? Run /dbprune (admin) to trim and compact the database.")
        await u.reply(ctx, embed=embed)

    async def _dbprune(self, ctx):
        member = u.author_of(ctx)
        if u.guild_of(ctx) and not member.guild_permissions.administrator:
            await u.reply(ctx, embed=discord.Embed(title="🚫 Admins only", color=0xE11D48))
            return
        before = (await self.db.info())["size"]
        await self.db.prune()
        after = (await self.db.info())["size"]
        embed = discord.Embed(title="🧹 Database pruned", color=0x22C55E)
        embed.description = f"Freed **{(before - after) / 1024 / 1024:.2f} MB** (old transactions trimmed, WAL compacted)."
        await u.reply(ctx, embed=embed)

    @commands.command(name="dbinfo", help="Show database size and row counts.", usage="b.dbinfo")
    async def dbinfo(self, ctx):
        await self._dbinfo(ctx)

    @commands.command(name="dbprune", help="Trim old transactions and compact the database.", usage="b.dbprune")
    async def dbprune(self, ctx):
        await self._dbprune(ctx)

    @app_commands.command(name="dbinfo", description="Show database size and row counts.")
    async def slash_dbinfo(self, interaction: discord.Interaction):
        await self._dbinfo(interaction)

    @app_commands.command(name="dbprune", description="Trim old transactions and compact the database (admins only).")
    async def slash_dbprune(self, interaction: discord.Interaction):
        await self._dbprune(interaction)


async def setup(bot: commands.Bot):
    await bot.add_cog(Maintenance(bot))
