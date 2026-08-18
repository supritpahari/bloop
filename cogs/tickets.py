"""Ticketing system: button panels, private ticket channels, claim/close, transcripts.

Admins run `/ticketsetup` once (support role, category, transcript channel),
then post a panel with `/ticketpanel`. Members click 🎫 to get a private
`ticket-0042` channel visible only to them, staff, and the bot. Staff claim,
add/remove people, and close with `/close`, which archives a transcript to the
configured channel before deleting the ticket channel.
"""

import asyncio
import io
import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from economy import utils as u

logger = logging.getLogger(__name__)

PANEL_BUTTON_ID = "bloop:tickets:create"
DELETE_DELAY_SECONDS = 10  # grace period before a closed ticket channel is deleted
TRANSCRIPT_MAX_MESSAGES = 500  # cap so huge tickets don't take forever to export
TICKET_COLOR = 0x4FD1C5  # Bloop teal


class TicketError(Exception):
    """A problem the user can fix or understand — its message is shown to them."""


def ticket_overwrites(
    guild: discord.Guild,
    creator: discord.Member,
    support_role: discord.Role | None,
    bot_member: discord.Member,
) -> dict:
    """Who can see a fresh ticket channel: nobody but the creator, staff, and the bot."""
    member_overwrites = discord.PermissionOverwrite(
        view_channel=True,
        read_message_history=True,
        send_messages=True,
        attach_files=True,
        embed_links=True,
    )
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        creator: member_overwrites,
        bot_member: discord.PermissionOverwrite(
            view_channel=True,
            read_message_history=True,
            send_messages=True,
            attach_files=True,
            embed_links=True,
            manage_channels=True,
            manage_messages=True,
        ),
    }
    if support_role:
        overwrites[support_role] = discord.PermissionOverwrite(
            view_channel=True,
            read_message_history=True,
            send_messages=True,
            attach_files=True,
            embed_links=True,
            manage_messages=True,
        )
    return overwrites


def format_transcript(ticket: dict, channel_name: str, messages: list) -> str:
    """Render ticket messages (oldest first) as a plain-text transcript."""
    lines = [
        f"Transcript — ticket #{ticket['ticket_id']:04d} (#{channel_name})",
        f"Opened by <@{ticket['creator_id']}> ({ticket['creator_id']}) "
        f"at {ticket.get('created_at', '?')}",
        "=" * 60,
    ]
    for msg in messages:
        stamp = msg.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
        author = f"{msg.author} ({msg.author.id})"
        parts = [msg.content] if msg.content else []
        parts.extend(a.url for a in msg.attachments)
        lines.append(f"[{stamp}] {author}: {' '.join(parts)}".rstrip())
    if len(messages) >= TRANSCRIPT_MAX_MESSAGES:
        lines.append(f"(transcript capped at the newest {TRANSCRIPT_MAX_MESSAGES} messages)")
    return "\n".join(lines)


class TicketPanelView(discord.ui.View):
    """Persistent panel view — survives restarts via its fixed custom_id."""

    def __init__(self, cog: "Tickets | None" = None):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Create Ticket",
        emoji="🎫",
        style=discord.ButtonStyle.primary,
        custom_id=PANEL_BUTTON_ID,
    )
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.cog is None:
            await interaction.response.send_message(
                "The ticket system is still starting up — try again in a moment.", ephemeral=True
            )
            return
        await self.cog.panel_button_callback(interaction)


class Tickets(commands.Cog):
    """Run a support-ticket system with private per-user channels."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _db(self):
        return getattr(self.bot, "tickets_db", None)

    async def cog_load(self):
        # Register the persistent view so panel buttons work after a restart.
        self.bot.add_view(TicketPanelView(self))

    # ------------------------------------------------------------ helpers

    @staticmethod
    def _is_staff(member: discord.Member, cfg: dict | None) -> bool:
        if member.guild_permissions.administrator:
            return True
        role_id = cfg.get("support_role_id") if cfg else None
        return bool(role_id and any(r.id == role_id for r in member.roles))

    async def _ticket_or_error(self, ctx) -> tuple[dict, discord.TextChannel] | None:
        """Fetch the open ticket for this channel, replying with an error if it isn't one."""
        db = self._db()
        channel = ctx.channel
        ticket = await db.get_ticket_by_channel(channel.id) if db else None
        if not ticket or ticket["status"] != "open":
            await u.reply(ctx, content="This channel isn't an open ticket.")
            return None
        return ticket, channel

    async def panel_button_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            channel = await self._open_ticket(interaction.guild, interaction.user)
        except TicketError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return
        except discord.Forbidden:
            await interaction.followup.send(
                "I don't have permission to create that channel. Ask an admin to check my "
                "**Manage Channels** and **Manage Roles** permissions.",
                ephemeral=True,
            )
            return
        except Exception as e:
            logger.error(f"failed to open ticket: {e}")
            await interaction.followup.send("Something went wrong creating your ticket.", ephemeral=True)
            return
        await interaction.followup.send(f"🎫 Your ticket has been created: {channel.mention}", ephemeral=True)

    async def _open_ticket(self, guild: discord.Guild, member: discord.Member) -> discord.TextChannel:
        db = self._db()
        if db is None:
            raise TicketError("The ticket database isn't ready right now. Try again in a moment.")
        cfg = await db.get_config(guild.id)
        if cfg is None or not cfg.get("category_id"):
            raise TicketError("The ticket system isn't set up yet. Ask an admin to run `/ticketsetup`.")
        existing = await db.get_open_ticket_by_user(guild.id, member.id)
        if existing:
            raise TicketError(
                f"You already have an open ticket: <#{existing['channel_id']}>. "
                "Please close it before opening a new one."
            )
        category = guild.get_channel(cfg["category_id"])
        if not isinstance(category, discord.CategoryChannel):
            raise TicketError("The ticket category is missing. Ask an admin to run `/ticketsetup` again.")
        support_role = guild.get_role(cfg["support_role_id"]) if cfg.get("support_role_id") else None

        number = await db.next_ticket_number(guild.id)
        channel = await guild.create_text_channel(
            name=f"ticket-{number:04d}",
            category=category,
            overwrites=ticket_overwrites(guild, member, support_role, guild.me),
            reason=f"Ticket #{number} opened by {member}",
        )
        await db.create_ticket(guild.id, number, channel.id, member.id)

        welcome = cfg.get("welcome_message") or (
            "Describe your issue here and staff will be with you shortly."
        )
        embed = discord.Embed(
            title=f"🎫 Ticket #{number:04d}",
            description=f"{member.mention} {welcome}",
            color=TICKET_COLOR,
        )
        support_line = support_role.mention if support_role else "the admins"
        embed.add_field(name="Staff", value=f"Staff on this ticket: {support_line}")
        embed.set_footer(text="Use /close [reason] when your issue is resolved.")
        await channel.send(content=member.mention, embed=embed)
        return channel

    async def collect_transcript(self, channel: discord.TextChannel, ticket: dict) -> str:
        messages = [m async for m in channel.history(limit=TRANSCRIPT_MAX_MESSAGES, oldest_first=True)]
        return format_transcript(ticket, channel.name, messages)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        """Mark tickets closed if their channel is deleted without /close."""
        db = self._db()
        if db is None or getattr(channel, "guild", None) is None:
            return
        try:
            ticket = await db.get_ticket_by_channel(channel.id)
            if ticket and ticket["status"] == "open":
                await db.close_ticket(channel.id, closed_by=None, reason="Channel deleted manually")
        except Exception as e:
            logger.error(f"failed to record manual ticket deletion: {e}")

    # ------------------------------------------------------------ setup & panel

    @commands.command(
        name="ticketsetup",
        help="Configure the ticket system (admin). Optionally set a support role, category, transcript channel, and welcome message. Creates a 🎫 Tickets category if none is given.",
        usage="b.ticketsetup [@support_role] [#category] [#transcript_channel] [welcome message]",
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(manage_channels=True, manage_roles=True)
    async def ticketsetup(
        self,
        ctx: commands.Context,
        support_role: discord.Role = None,
        category: discord.CategoryChannel = None,
        transcript_channel: discord.TextChannel = None,
        *,
        welcome_message: str = "",
    ):
        await self._setup(ctx, support_role, category, transcript_channel, welcome_message)

    @app_commands.command(
        name="ticketsetup",
        description="Configure the ticket system: support role, category, transcripts (admins only)",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.checks.bot_has_permissions(manage_channels=True, manage_roles=True)
    @app_commands.describe(
        support_role="Role that can see and claim tickets (optional)",
        category="Category to create ticket channels in (optional, auto-created if omitted)",
        transcript_channel="Channel that receives closed-ticket transcripts (optional)",
        welcome_message="Message shown when a ticket opens (optional)",
    )
    async def slash_ticketsetup(
        self,
        interaction: discord.Interaction,
        support_role: discord.Role = None,
        category: discord.CategoryChannel = None,
        transcript_channel: discord.TextChannel = None,
        welcome_message: str = "",
    ):
        await self._setup(interaction, support_role, category, transcript_channel, welcome_message)

    async def _setup(self, ctx, support_role, category, transcript_channel, welcome_message):
        db = self._db()
        if db is None:
            await u.reply(ctx, content="❌ Database not ready.")
            return
        guild = ctx.guild
        cfg = await db.get_config(guild.id)

        if category is None and not (cfg and cfg.get("category_id")):
            # No category given and none configured: create one, hidden from @everyone.
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                guild.me: discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, manage_channels=True, manage_roles=True
                ),
            }
            if support_role:
                overwrites[support_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
            category = await guild.create_category("🎫 Tickets", overwrites=overwrites, reason="Ticket system setup")

        await db.set_config(
            guild.id,
            category_id=category.id if category else None,
            support_role_id=support_role.id if support_role else None,
            transcript_channel_id=transcript_channel.id if transcript_channel else None,
            welcome_message=welcome_message or None,
        )
        cfg = await db.get_config(guild.id)

        embed = discord.Embed(title="🎫 Ticket system configured", color=0x22C55E)
        embed.add_field(name="Category", value=f"<#{cfg['category_id']}>", inline=True)
        role = f"<@&{cfg['support_role_id']}>" if cfg["support_role_id"] else "Admins only"
        embed.add_field(name="Support role", value=role, inline=True)
        transcript = (
            f"<#{cfg['transcript_channel_id']}>" if cfg["transcript_channel_id"] else "Not set"
        )
        embed.add_field(name="Transcripts", value=transcript, inline=True)
        if cfg["welcome_message"]:
            embed.add_field(name="Welcome message", value=cfg["welcome_message"][:1024], inline=False)
        embed.set_footer(text="Next: post a panel with /ticketpanel")
        await u.reply(ctx, embed=embed)

    @commands.command(
        name="ticketpanel",
        help="Post the ticket panel with a Create Ticket button (admin).",
        usage="b.ticketpanel [#channel] [description]",
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(manage_channels=True, manage_roles=True)
    async def ticketpanel(
        self, ctx: commands.Context, channel: discord.TextChannel = None, *, description: str = None
    ):
        await self._panel(ctx, channel or ctx.channel, description)

    @app_commands.command(
        name="ticketpanel", description="Post the ticket panel with a Create Ticket button (admins only)"
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.checks.bot_has_permissions(manage_channels=True, manage_roles=True)
    @app_commands.describe(
        channel="Channel to post the panel in (default: this one)",
        description="Panel text (default: a short 'need help?' blurb)",
    )
    async def slash_ticketpanel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel = None,
        description: str = "",
    ):
        await interaction.response.defer(ephemeral=True)
        await self._panel(interaction, channel or interaction.channel, description or None)

    async def _panel(self, ctx, channel: discord.TextChannel, description: str | None):
        db = self._db()
        if db is None:
            await u.reply(ctx, content="❌ Database not ready.")
            return
        cfg = await db.get_config(ctx.guild.id)
        if cfg is None or not cfg.get("category_id"):
            await u.reply(ctx, content="The ticket system isn't configured yet — run `/ticketsetup` first.")
            return
        embed = discord.Embed(
            title="🎫 Support Tickets",
            description=description
            or "Need help? Click **Create Ticket** below and a private channel will open for you and the staff team.",
            color=TICKET_COLOR,
        )
        await channel.send(embed=embed, view=TicketPanelView(self))
        await u.reply(ctx, content=f"Panel posted in {channel.mention}.", ephemeral=True)

    # ------------------------------------------------------------ ticket actions

    @commands.command(
        name="close",
        help="Close the ticket channel you're in. Saves a transcript and deletes the channel. Usable by the ticket creator or staff.",
        usage="b.close [reason]",
    )
    @commands.guild_only()
    async def close(self, ctx: commands.Context, *, reason: str = None):
        await self._close(ctx, reason)

    @app_commands.command(name="close", description="Close this ticket (saves a transcript)")
    @app_commands.guild_only()
    @app_commands.describe(reason="Why the ticket is being closed (optional)")
    async def slash_close(self, interaction: discord.Interaction, reason: str = None):
        await self._close(interaction, reason)

    async def _close(self, ctx, reason: str | None):
        db = self._db()
        if db is None:
            await u.reply(ctx, content="❌ Database not ready.")
            return
        found = await self._ticket_or_error(ctx)
        if found is None:
            return
        ticket, channel = found
        author = u.author_of(ctx)
        cfg = await db.get_config(channel.guild.id)
        if ticket["creator_id"] != author.id and not self._is_staff(author, cfg):
            await u.reply(ctx, content="Only the ticket creator or staff can close this ticket.")
            return

        # Mark closed in the DB first so listings stay accurate even if deletion fails.
        await db.close_ticket(channel.id, author.id, reason)

        # Transcript to the configured channel (if any).
        if cfg and cfg.get("transcript_channel_id"):
            target = channel.guild.get_channel(cfg["transcript_channel_id"])
            if target:
                try:
                    text = await self.collect_transcript(channel, ticket)
                    log_embed = discord.Embed(
                        title=f"🎫 Ticket #{ticket['ticket_id']:04d} closed",
                        color=0x6B7280,
                        timestamp=datetime.now(timezone.utc),
                    )
                    log_embed.add_field(name="Opened by", value=f"<@{ticket['creator_id']}>", inline=True)
                    log_embed.add_field(name="Closed by", value=f"<@{author.id}>", inline=True)
                    closer_reason = reason or "No reason given"
                    log_embed.add_field(name="Reason", value=closer_reason[:1024], inline=False)
                    await target.send(
                        embed=log_embed,
                        file=discord.File(
                            io.BytesIO(text.encode("utf-8")),
                            filename=f"ticket-{ticket['ticket_id']:04d}-transcript.txt",
                        ),
                    )
                except Exception as e:
                    logger.error(f"failed to save transcript: {e}")

        embed = discord.Embed(
            title=f"🔒 Ticket #{ticket['ticket_id']:04d} closed",
            description=(
                f"Closed by {author.mention}"
                + (f" — {reason}" if reason else "")
                + f"\n\nThis channel will be deleted in {DELETE_DELAY_SECONDS} seconds."
            ),
            color=0xE11D48,
        )
        await u.reply(ctx, embed=embed)
        await asyncio.sleep(DELETE_DELAY_SECONDS)
        try:
            await channel.delete(reason=f"Ticket closed by {author}")
        except discord.Forbidden:
            await channel.send("I couldn't delete this channel — please remove it manually.")

    @commands.command(
        name="claim",
        help="Claim the ticket channel you're in (staff only).",
        usage="b.claim",
    )
    @commands.guild_only()
    async def claim(self, ctx: commands.Context):
        await self._claim(ctx)

    @app_commands.command(name="claim", description="Claim this ticket (staff only)")
    @app_commands.guild_only()
    async def slash_claim(self, interaction: discord.Interaction):
        await self._claim(interaction)

    async def _claim(self, ctx):
        db = self._db()
        if db is None:
            await u.reply(ctx, content="❌ Database not ready.")
            return
        found = await self._ticket_or_error(ctx)
        if found is None:
            return
        ticket, channel = found
        author = u.author_of(ctx)
        cfg = await db.get_config(channel.guild.id)
        if not self._is_staff(author, cfg):
            await u.reply(ctx, content="Only staff can claim tickets.")
            return
        if ticket.get("claimed_by"):
            await u.reply(ctx, content=f"This ticket is already claimed by <@{ticket['claimed_by']}>.")
            return
        await db.set_claimed(channel.id, author.id)
        embed = discord.Embed(
            description=f"🙌 {author.mention} claimed this ticket and will help you shortly.",
            color=TICKET_COLOR,
        )
        await u.reply(ctx, embed=embed)

    @commands.command(
        name="adduser",
        help="Add a member to this ticket channel (staff only).",
        usage="b.adduser <@user>",
    )
    @commands.guild_only()
    async def adduser(self, ctx: commands.Context, member: discord.Member):
        await self._adduser(ctx, member)

    @app_commands.command(name="adduser", description="Add a member to this ticket (staff only)")
    @app_commands.guild_only()
    @app_commands.describe(member="The member to add")
    async def slash_adduser(self, interaction: discord.Interaction, member: discord.Member):
        await self._adduser(interaction, member)

    async def _adduser(self, ctx, member: discord.Member):
        db = self._db()
        if db is None:
            await u.reply(ctx, content="❌ Database not ready.")
            return
        found = await self._ticket_or_error(ctx)
        if found is None:
            return
        _, channel = found
        author = u.author_of(ctx)
        cfg = await db.get_config(channel.guild.id)
        if not self._is_staff(author, cfg):
            await u.reply(ctx, content="Only staff can add members to tickets.")
            return
        await channel.set_permissions(
            member,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True,
            reason=f"Added to ticket by {author}",
        )
        await u.reply(ctx, content=f"➕ Added {member.mention} to this ticket.")

    @commands.command(
        name="removeuser",
        help="Remove a member from this ticket channel (staff only). Can't remove the creator.",
        usage="b.removeuser <@user>",
    )
    @commands.guild_only()
    async def removeuser(self, ctx: commands.Context, member: discord.Member):
        await self._removeuser(ctx, member)

    @app_commands.command(name="removeuser", description="Remove a member from this ticket (staff only)")
    @app_commands.guild_only()
    @app_commands.describe(member="The member to remove")
    async def slash_removeuser(self, interaction: discord.Interaction, member: discord.Member):
        await self._removeuser(interaction, member)

    async def _removeuser(self, ctx, member: discord.Member):
        db = self._db()
        if db is None:
            await u.reply(ctx, content="❌ Database not ready.")
            return
        found = await self._ticket_or_error(ctx)
        if found is None:
            return
        ticket, channel = found
        author = u.author_of(ctx)
        cfg = await db.get_config(channel.guild.id)
        if not self._is_staff(author, cfg):
            await u.reply(ctx, content="Only staff can remove members from tickets.")
            return
        if member.id == ticket["creator_id"]:
            await u.reply(ctx, content="You can't remove the ticket creator from their own ticket.")
            return
        await channel.set_permissions(member, overwrite=None, reason=f"Removed from ticket by {author}")
        await u.reply(ctx, content=f"➖ Removed {member.mention} from this ticket.")

    @commands.command(
        name="tickets",
        help="List open tickets and ticket stats (staff only).",
        usage="b.tickets",
    )
    @commands.guild_only()
    async def tickets(self, ctx: commands.Context):
        await self._list(ctx)

    @app_commands.command(name="tickets", description="List open tickets and stats (staff only)")
    @app_commands.guild_only()
    async def slash_tickets(self, interaction: discord.Interaction):
        await self._list(interaction)

    async def _list(self, ctx):
        db = self._db()
        if db is None:
            await u.reply(ctx, content="❌ Database not ready.")
            return
        author = u.author_of(ctx)
        cfg = await db.get_config(ctx.guild.id)
        if not self._is_staff(author, cfg):
            await u.reply(ctx, content="Only staff can view the ticket list.")
            return
        open_list = await db.open_tickets(ctx.guild.id)
        stats = await db.ticket_stats(ctx.guild.id)
        embed = discord.Embed(
            title="🎫 Open tickets",
            description=(
                "\n".join(
                    f"**#{t['ticket_id']:04d}** <#{t['channel_id']}> — opened by <@{t['creator_id']}>"
                    + (f", claimed by <@{t['claimed_by']}>" if t["claimed_by"] else ", unclaimed")
                    for t in open_list
                )
                or "No open tickets right now. 🎉"
            ),
            color=TICKET_COLOR,
        )
        embed.set_footer(text=f"{stats['open']} open · {stats['total']} total")
        await u.reply(ctx, embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
