"""Welcome and Leave message setup with embeds."""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from economy.xp_db import XPDB

logger = logging.getLogger(__name__)


class WelcomeLeave(commands.Cog):
    """Configure welcome/leave messages and send embeds on member events."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _db(self) -> XPDB:
        return getattr(self.bot, "xp_db", None)

    async def _get_config(self, guild_id: int, kind: str):
        db = self._db()
        if db is None:
            return None
        if kind == "welcome":
            return await db.get_welcome(guild_id)
        return await db.get_leave(guild_id)

    # ------------------ Welcome command ------------------

    @commands.command(name="welcome", help="Set welcome message (server owner / admin)")
    @commands.has_permissions(administrator=True)
    async def welcome_prefix(self, ctx: commands.Context, channel: discord.TextChannel = None, *, message_template: str = ""):
        await self._set_welcome(ctx, channel or ctx.channel, message_template or "Welcome {mention} to {guild}!")

    @app_commands.command(name="welcome", description="Set welcome message (server owner / admin)")
    @app_commands.describe(
        channel="Channel to send welcome messages",
        message_template="Message template (use {mention} and {guild})",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def welcome_slash(self, interaction: discord.Interaction, channel: discord.TextChannel = None, message_template: str = ""):
        await interaction.response.defer(ephemeral=False)
        await self._set_welcome(interaction, channel or interaction.channel, message_template or "Welcome {mention} to {guild}!")

    async def _set_welcome(self, ctx, channel: discord.TextChannel, message_template: str):
        db = self._db()
        if db is None:
            await self._reply(ctx, "❌ Database not ready.")
            return
        await db.set_welcome(ctx.guild.id, channel.id, message_template)
        embed = discord.Embed(
            title="👋 Welcome Configured",
            description=f"Channel: {channel.mention}\nTemplate: `{message_template}`",
            color=0x22C55E,
        )
        await self._reply(ctx, embed=embed)

    # ------------------ Leave command ------------------

    @commands.command(name="setleave", aliases=["leavemessage"], help="Set leave message (server owner / admin)", usage="b.setleave [#channel] [message]")
    @commands.has_permissions(administrator=True)
    async def leave_prefix(self, ctx: commands.Context, channel: discord.TextChannel = None, *, message_template: str = ""):
        await self._set_leave(ctx, channel or ctx.channel, message_template or "Goodbye {mention}! Thanks for being here.")

    @app_commands.command(name="setleave", description="Set leave message (server owner / admin)")
    @app_commands.describe(
        channel="Channel to send leave messages",
        message_template="Message template (use {mention} and {guild})",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def leave_slash(self, interaction: discord.Interaction, channel: discord.TextChannel = None, message_template: str = ""):
        await interaction.response.defer(ephemeral=False)
        await self._set_leave(interaction, channel or interaction.channel, message_template or "Goodbye {mention}! Thanks for being here.")

    async def _set_leave(self, ctx, channel: discord.TextChannel, message_template: str):
        db = self._db()
        if db is None:
            await self._reply(ctx, "❌ Database not ready.")
            return
        await db.set_leave(ctx.guild.id, channel.id, message_template)
        embed = discord.Embed(
            title="👋 Leave Configured",
            description=f"Channel: {channel.mention}\nTemplate: `{message_template}`",
            color=0xE11D48,
        )
        await self._reply(ctx, embed=embed)

    # ------------------ Event listeners ------------------

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        db = self._db()
        if db is None:
            return
        cfg = await db.get_welcome(member.guild.id)
        if not cfg or not cfg.get("channel_id"):
            return
        channel = member.guild.get_channel(cfg["channel_id"])
        if not channel or not isinstance(channel, discord.TextChannel):
            return
        msg = cfg.get("message_template", "Welcome {mention} to {guild}!")
        text = msg.format(mention=member.mention, guild=member.guild.name, user=member.display_name)
        embed = discord.Embed(
            title="👋 Welcome!",
            description=text,
            color=0x22C55E,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"Member #{member.guild.member_count}")
        try:
            await channel.send(embed=embed)
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        db = self._db()
        if db is None:
            return
        cfg = await db.get_leave(member.guild.id)
        if not cfg or not cfg.get("channel_id"):
            return
        channel = member.guild.get_channel(cfg["channel_id"])
        if not channel or not isinstance(channel, discord.TextChannel):
            return
        msg = cfg.get("message_template", "Goodbye {mention}! Thanks for being here.")
        text = msg.format(mention=member.mention, guild=member.guild.name, user=member.display_name)
        embed = discord.Embed(
            title="👋 Goodbye!",
            description=text,
            color=0xE11D48,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text="We hope to see you again!")
        try:
            await channel.send(embed=embed)
        except Exception:
            pass

    # ------------------ Helper ------------------

    async def _reply(self, ctx, content=None, embed=None):
        if isinstance(ctx, discord.Interaction):
            if ctx.response.is_done():
                await ctx.followup.send(content=content, embed=embed)
            else:
                await ctx.response.send_message(content=content, embed=embed)
        else:
            await ctx.send(content=content, embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(WelcomeLeave(bot))
