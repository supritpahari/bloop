import re
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

DURATION_RE = re.compile(r"(\d+)\s*([smhd])", re.IGNORECASE)
MAX_TIMEOUT_SECONDS = 2419200  # Discord's 28-day timeout cap
CLEAR_BATCH_SIZE = 100  # Discord's bulk-delete cap per request
BULK_DELETE_MAX_AGE = timedelta(days=14)  # Discord won't bulk-delete older messages
LOCKABLE_CHANNELS = (discord.TextChannel, discord.VoiceChannel, discord.StageChannel, discord.ForumChannel)


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


async def clear_channel_messages(channel: discord.abc.Messageable, actor: str) -> tuple[int, bool]:
    """Bulk-delete every message Discord allows from a channel.

    Discord's bulk-delete endpoint rejects messages older than 14 days, so we
    only purge newer ones (with a small clock-skew margin). Returns the number
    of messages deleted and whether older messages were left behind.
    """
    cutoff = discord.utils.utcnow() - BULK_DELETE_MAX_AGE - timedelta(minutes=1)
    total = 0
    while True:
        deleted = await channel.purge(limit=CLEAR_BATCH_SIZE, after=cutoff, reason=f"Channel cleared by {actor}")
        total += len(deleted)
        if len(deleted) < CLEAR_BATCH_SIZE:
            break
    older_left = False
    async for _ in channel.history(limit=1):
        older_left = True
    return total, older_left


async def lock_channel(channel, guild: discord.Guild, actor: str) -> None:
    """Deny @everyone permission to talk or react in a channel."""
    overwrites = channel.overwrites_for(guild.default_role)
    overwrites.send_messages = False
    overwrites.send_messages_in_threads = False
    overwrites.add_reactions = False
    await channel.set_permissions(guild.default_role, overwrite=overwrites, reason=f"Channel locked by {actor}")


async def unlock_channel(channel, guild: discord.Guild, actor: str) -> None:
    """Restore @everyone's ability to talk and react in a channel.

    Resets the permissions lock_channel denied back to None (inherit from
    roles) instead of forcing them to True, so the channel returns to whatever
    permissions it had before it was locked.
    """
    overwrites = channel.overwrites_for(guild.default_role)
    overwrites.send_messages = None
    overwrites.send_messages_in_threads = None
    overwrites.add_reactions = None
    await channel.set_permissions(guild.default_role, overwrite=overwrites, reason=f"Channel unlocked by {actor}")


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

    @commands.command(
        name="clear",
        help="Delete all recent messages in this channel. Administrator only. Messages older than 14 days can't be bulk-deleted (Discord limit).",
        usage="b.clear",
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def clear(self, ctx: commands.Context):
        deleted, older_left = await clear_channel_messages(ctx.channel, str(ctx.author))
        message = f"🧹 Cleared {deleted} message(s) from this channel."
        if older_left:
            message += "\nMessages older than 14 days can't be bulk-deleted (Discord limit), so they were left alone."
        await ctx.send(message)

    @commands.command(
        name="lock",
        help="Lock this channel so only admins can send messages. Administrator only.",
        usage="b.lock",
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def lock(self, ctx: commands.Context):
        if not isinstance(ctx.channel, LOCKABLE_CHANNELS):
            await ctx.send("I can only lock regular channels, not threads.")
            return
        if ctx.channel.overwrites_for(ctx.guild.default_role).send_messages is False:
            await ctx.send("This channel is already locked.")
            return
        try:
            await lock_channel(ctx.channel, ctx.guild, str(ctx.author))
        except discord.Forbidden:
            await ctx.send("I don't have permission to lock this channel.")
            return
        await ctx.send(f"🔒 Locked {ctx.channel.mention}. Only admins can send messages here now.")

    @commands.command(
        name="unlock",
        help="Unlock a channel locked with b.lock so members can talk again. Administrator only.",
        usage="b.unlock",
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def unlock(self, ctx: commands.Context):
        if not isinstance(ctx.channel, LOCKABLE_CHANNELS):
            await ctx.send("I can only unlock regular channels, not threads.")
            return
        if ctx.channel.overwrites_for(ctx.guild.default_role).send_messages is not False:
            await ctx.send("This channel isn't locked.")
            return
        try:
            await unlock_channel(ctx.channel, ctx.guild, str(ctx.author))
        except discord.Forbidden:
            await ctx.send("I don't have permission to unlock this channel.")
            return
        await ctx.send(f"🔓 Unlocked {ctx.channel.mention}. Everyone can send messages here again.")

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

    @app_commands.command(name="clear", description="Delete all recent messages in this channel (admins only)")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.checks.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def slash_clear(self, interaction: discord.Interaction):
        # Purging a busy channel can take longer than the 3-second interaction
        # window, so defer first and reply via followup.
        await interaction.response.defer()
        deleted, older_left = await clear_channel_messages(interaction.channel, str(interaction.user))
        message = f"🧹 Cleared {deleted} message(s) from this channel."
        if older_left:
            message += "\nMessages older than 14 days can't be bulk-deleted (Discord limit), so they were left alone."
        await interaction.followup.send(message)

    @app_commands.command(name="lock", description="Lock this channel so only admins can send messages (admins only)")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.checks.bot_has_permissions(manage_channels=True)
    async def slash_lock(self, interaction: discord.Interaction):
        channel = interaction.channel
        if not isinstance(channel, LOCKABLE_CHANNELS):
            await interaction.response.send_message("I can only lock regular channels, not threads.", ephemeral=True)
            return
        if channel.overwrites_for(interaction.guild.default_role).send_messages is False:
            await interaction.response.send_message("This channel is already locked.", ephemeral=True)
            return
        try:
            await lock_channel(channel, interaction.guild, str(interaction.user))
        except discord.Forbidden:
            await interaction.response.send_message("I don't have permission to lock this channel.", ephemeral=True)
            return
        await interaction.response.send_message(f"🔒 Locked {channel.mention}. Only admins can send messages here now.")

    @app_commands.command(name="unlock", description="Unlock a channel locked with /lock (admins only)")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.checks.bot_has_permissions(manage_channels=True)
    async def slash_unlock(self, interaction: discord.Interaction):
        channel = interaction.channel
        if not isinstance(channel, LOCKABLE_CHANNELS):
            await interaction.response.send_message("I can only unlock regular channels, not threads.", ephemeral=True)
            return
        if channel.overwrites_for(interaction.guild.default_role).send_messages is not False:
            await interaction.response.send_message("This channel isn't locked.", ephemeral=True)
            return
        try:
            await unlock_channel(channel, interaction.guild, str(interaction.user))
        except discord.Forbidden:
            await interaction.response.send_message("I don't have permission to unlock this channel.", ephemeral=True)
            return
        await interaction.response.send_message(f"🔓 Unlocked {channel.mention}. Everyone can send messages here again.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
