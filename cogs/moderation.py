import re
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

DURATION_RE = re.compile(r"(\d+)\s*([smhd])", re.IGNORECASE)
MAX_TIMEOUT_SECONDS = 2419200  # Discord's 28-day timeout cap


def parse_duration(text: str) -> int | None:
    """Parse durations like '10m', '2h', '1d 30m' into seconds. None if invalid."""
    if not text:
        return None
    total = 0
    for amount, unit in DURATION_RE.findall(text):
        total += int(amount) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit.lower()]
    return total if total > 0 else None


def hierarchy_problem(guild: discord.Guild, user: discord.Member, member: discord.Member) -> str | None:
    """Return an error message if `user` cannot moderate `member`, else None."""
    if member == user:
        return "You cannot moderate yourself."
    if member == guild.owner:
        return "You cannot moderate the server owner."
    if user != guild.owner and member.top_role >= user.top_role:
        return "That member has a role equal to or higher than yours."
    return None


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(
        name="kick",
        help="Kick a member from the server. Requires the Kick Members permission.",
        usage="b.kick <@user> [reason]",
    )
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    async def kick(self, ctx: commands.Context, member: discord.Member, *, reason: str = None):
        problem = hierarchy_problem(ctx.guild, ctx.author, member)
        if problem:
            await ctx.send(problem)
            return
        try:
            await member.kick(reason=reason)
        except discord.Forbidden:
            await ctx.send("I don't have permission to kick that member.")
            return
        await ctx.send(f"Kicked {member.mention}.")

    @commands.command(
        name="ban",
        help="Ban a member from the server. Requires the Ban Members permission.",
        usage="b.ban <@user> [reason]",
    )
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def ban(self, ctx: commands.Context, member: discord.Member, *, reason: str = None):
        problem = hierarchy_problem(ctx.guild, ctx.author, member)
        if problem:
            await ctx.send(problem)
            return
        try:
            await member.ban(reason=reason)
        except discord.Forbidden:
            await ctx.send("I don't have permission to ban that member.")
            return
        await ctx.send(f"Banned {member.mention}.")

    @commands.command(
        name="mute",
        help="Timeout a member for a duration such as 10m, 2h, 1d or 1h 30m. Requires the Moderate Members permission.",
        usage="b.mute <@user> <duration> [reason]",
    )
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def mute(self, ctx: commands.Context, member: discord.Member, duration: str, *, reason: str = None):
        seconds = parse_duration(duration)
        if seconds is None:
            await ctx.send("Invalid duration. Use formats like `10m`, `2h`, `1d`, or combine: `1h 30m`.")
            return
        seconds = min(seconds, MAX_TIMEOUT_SECONDS)
        problem = hierarchy_problem(ctx.guild, ctx.author, member)
        if problem:
            await ctx.send(problem)
            return
        try:
            await member.timeout(timedelta(seconds=seconds), reason=reason)
        except discord.Forbidden:
            await ctx.send("I don't have permission to mute that member.")
            return
        await ctx.send(f"Muted {member.mention} for {duration}.")

    @commands.command(
        name="unmute",
        help="Remove a timeout from a member. Requires the Moderate Members permission.",
        usage="b.unmute <@user>",
    )
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def unmute(self, ctx: commands.Context, member: discord.Member):
        problem = hierarchy_problem(ctx.guild, ctx.author, member)
        if problem:
            await ctx.send(problem)
            return
        try:
            await member.timeout(None, reason="Unmuted")
        except discord.Forbidden:
            await ctx.send("I don't have permission to unmute that member.")
            return
        await ctx.send(f"Unmuted {member.mention}.")

    @app_commands.command(name="kick", description="Kick a member from the server")
    @app_commands.default_permissions(kick_members=True)
    @app_commands.checks.has_permissions(kick_members=True)
    @app_commands.describe(member="The member to kick", reason="Reason for the kick")
    async def slash_kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = None):
        problem = hierarchy_problem(interaction.guild, interaction.user, member)
        if problem:
            await interaction.response.send_message(problem, ephemeral=True)
            return
        try:
            await member.kick(reason=reason)
        except discord.Forbidden:
            await interaction.response.send_message("I don't have permission to kick that member.", ephemeral=True)
            return
        await interaction.response.send_message(f"Kicked {member.mention}.")

    @app_commands.command(name="ban", description="Ban a member from the server")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.describe(member="The member to ban", reason="Reason for the ban")
    async def slash_ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = None):
        problem = hierarchy_problem(interaction.guild, interaction.user, member)
        if problem:
            await interaction.response.send_message(problem, ephemeral=True)
            return
        try:
            await member.ban(reason=reason)
        except discord.Forbidden:
            await interaction.response.send_message("I don't have permission to ban that member.", ephemeral=True)
            return
        await interaction.response.send_message(f"Banned {member.mention}.")

    @app_commands.command(name="mute", description="Timeout a member (mute them)")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(
        member="The member to mute",
        duration="Mute duration, e.g. 10m, 2h, 1d, or 1h 30m",
        reason="Reason for the mute",
    )
    async def slash_mute(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        duration: str,
        reason: str = None,
    ):
        seconds = parse_duration(duration)
        if seconds is None:
            await interaction.response.send_message(
                "Invalid duration. Use formats like `10m`, `2h`, `1d`, or combine: `1h 30m`.",
                ephemeral=True,
            )
            return
        seconds = min(seconds, MAX_TIMEOUT_SECONDS)
        problem = hierarchy_problem(interaction.guild, interaction.user, member)
        if problem:
            await interaction.response.send_message(problem, ephemeral=True)
            return
        try:
            await member.timeout(timedelta(seconds=seconds), reason=reason)
        except discord.Forbidden:
            await interaction.response.send_message("I don't have permission to mute that member.", ephemeral=True)
            return
        await interaction.response.send_message(f"Muted {member.mention} for {duration}.")

    @app_commands.command(name="unmute", description="Remove a timeout from a member")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(member="The member to unmute")
    async def slash_unmute(self, interaction: discord.Interaction, member: discord.Member):
        problem = hierarchy_problem(interaction.guild, interaction.user, member)
        if problem:
            await interaction.response.send_message(problem, ephemeral=True)
            return
        try:
            await member.timeout(None, reason="Unmuted")
        except discord.Forbidden:
            await interaction.response.send_message("I don't have permission to unmute that member.", ephemeral=True)
            return
        await interaction.response.send_message(f"Unmuted {member.mention}.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
