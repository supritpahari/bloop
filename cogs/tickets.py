"""Ticketing system: one /ticket setup form, an Open Ticket panel button, approval-based closing.

Admins run `/ticket` (or `b.ticket`), pick the panel channel and the roles to
add to ticket channels in a GUI form, and press Save. The bot posts the panel
message with a blue Open Ticket button. Members click it to get a private
`ticket-0042` channel (one open ticket at a time) with the configured roles
added. Closing goes through `/closeticket`: whoever didn't request the close
(the creator, if staff asked — or staff, if the creator asked) must approve,
then the ticket is closed and the creator is DM'd an AI summary of the
conversation generated with the AI configured via /aichat.
"""

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from economy import utils as u

logger = logging.getLogger(__name__)

OPEN_BUTTON_ID = "bloop:tickets:open"  # persistent panel button custom_id
FORM_TIMEOUT_SECONDS = 600  # how long the admin setup form stays usable
CLOSE_TIMEOUT_SECONDS = 300  # how long a close request can wait for approval
CLOSE_DELETE_DELAY = 15  # grace period before a closed ticket channel is deleted
TRANSCRIPT_MAX_MESSAGES = 500  # cap so huge tickets don't take forever to export
TRANSCRIPT_MAX_CHARS = 8000  # cap of transcript text fed to the AI model
TICKET_COLOR = 0x4FD1C5  # Bloop teal
CLOSE_COLOR = 0xE11D48

PANEL_MESSAGE = (
    "This channel is configured for ticket system. "
    "If you have any concerns, raise a ticket by clicking the button!"
)

AI_SUMMARY_PROMPT = (
    "You summarize Discord support tickets. Write a short, friendly summary "
    "(3-5 sentences) for the person who opened the ticket: what it was about, "
    "what was discussed, and how it was resolved. Plain text, no markdown headers."
)


class TicketError(Exception):
    """A problem the user can fix or understand — its message is shown to them."""


def ticket_overwrites(
    guild: discord.Guild,
    creator: discord.Member,
    staff_roles: list[discord.Role],
    bot_member: discord.Member,
) -> dict:
    """Who can see a fresh ticket channel: nobody but the creator, staff roles, and the bot."""
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
    for role in staff_roles:
        overwrites[role] = discord.PermissionOverwrite(
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
        f"Ticket #{ticket['ticket_id']:04d} (#{channel_name}) — "
        f"opened by user {ticket['creator_id']}",
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


class TicketFormView(discord.ui.View):
    """The /ticket setup GUI: pick a panel channel and roles, then Save."""

    def __init__(self, cog: "Tickets", guild: discord.Guild, user_id: int):
        super().__init__(timeout=FORM_TIMEOUT_SECONDS)
        self.cog = cog
        self.guild = guild
        self.user_id = user_id
        self.channel_id: int | None = None
        self.role_ids: list[int] = []

    async def ensure_author(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Only the admin who ran the command can use this form.", ephemeral=True
            )
            return False
        return True

    def _embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🎫 Ticket system setup",
            description=(
                "**1.** Pick the channel to post the ticket panel in\n"
                "**2.** Pick the roles to add to ticket channels\n"
                "**3.** Press **Save**"
            ),
            color=TICKET_COLOR,
        )
        embed.add_field(
            name="1. Channel", value=f"<#{self.channel_id}>" if self.channel_id else "❌ Not selected"
        )
        roles = ", ".join(f"<@&{r}>" for r in self.role_ids) or "❌ Not selected"
        embed.add_field(name="2. Roles to add", value=roles[:1024])
        embed.set_footer(text="Only you can use this form.")
        return embed

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder="1. Channel for the ticket panel",
        min_values=1,
        max_values=1,
    )
    async def pick_channel(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        if not await self.ensure_author(interaction):
            return
        self.channel_id = select.values[0].id
        await interaction.response.edit_message(embed=self._embed(), view=self)

    @discord.ui.select(
        cls=discord.ui.RoleSelect,
        placeholder="2. Roles to add to ticket channels",
        min_values=1,
        max_values=10,
    )
    async def pick_roles(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        if not await self.ensure_author(interaction):
            return
        self.role_ids = [role.id for role in select.values]
        await interaction.response.edit_message(embed=self._embed(), view=self)

    @discord.ui.button(label="Save", emoji="💾", style=discord.ButtonStyle.success)
    async def save(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.ensure_author(interaction):
            return
        if not self.channel_id:
            await interaction.response.send_message("Pick a channel first.", ephemeral=True)
            return
        if not self.role_ids:
            await interaction.response.send_message("Pick at least one role to add to tickets.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await self.cog._save_setup(self.guild, self.channel_id, self.role_ids)
        except discord.Forbidden:
            await interaction.followup.send(
                "I don't have permission for that — I need **Manage Channels** and "
                "**Manage Roles** to set up tickets.",
                ephemeral=True,
            )
            return
        except Exception as e:
            logger.error(f"ticket setup failed: {e}", exc_info=True)
            await interaction.followup.send("Something went wrong saving the setup.", ephemeral=True)
            return
        for item in self.children:
            item.disabled = True
        await interaction.edit_original_response(embed=self._embed(), view=self)
        await interaction.followup.send(
            f"✅ Ticket system configured — panel posted in <#{self.channel_id}>.", ephemeral=True
        )


class TicketPanelView(discord.ui.View):
    """Persistent panel view — survives restarts via its fixed custom_id."""

    def __init__(self, cog: "Tickets | None" = None):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Open Ticket",
        emoji="🎫",
        style=discord.ButtonStyle.primary,
        custom_id=OPEN_BUTTON_ID,
    )
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.cog is None:
            await interaction.response.send_message(
                "The ticket system is still starting up — try again in a moment.", ephemeral=True
            )
            return
        await self.cog.panel_button_callback(interaction)


class CloseTicketView(discord.ui.View):
    """Approval prompt: one side requests the close, the other side approves."""

    def __init__(self, ticket: dict, check_approver, approver_desc: str, requester_id: int, on_approve):
        super().__init__(timeout=CLOSE_TIMEOUT_SECONDS)
        self.ticket = ticket
        self.check_approver = check_approver  # callable(member) -> bool
        self.approver_desc = approver_desc
        self.requester_id = requester_id
        self.on_approve = on_approve  # async callable(interaction)
        self.message: discord.Message | None = None

    async def on_timeout(self):
        if self.message is None:
            return
        try:
            for item in self.children:
                item.disabled = True
            await self.message.edit(
                content="⌛ This close request expired — the ticket stays open.", view=self
            )
        except discord.HTTPException:
            pass

    @discord.ui.button(label="Approve Close", emoji="✅", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.check_approver(interaction.user):
            await interaction.response.send_message(
                f"Only {self.approver_desc} can respond to this close request.", ephemeral=True
            )
            return
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"✅ Close approved by {interaction.user.mention}.", view=self
        )
        await self.on_approve(interaction)

    @discord.ui.button(label="Cancel", emoji="❌", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.check_approver(interaction.user) and interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                f"Only {self.approver_desc} or the requester can cancel this.", ephemeral=True
            )
            return
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="❌ Close request cancelled.", view=self)


class Tickets(commands.Cog):
    """Run a support-ticket system with private per-user channels."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _db(self):
        return getattr(self.bot, "tickets_db", None)

    async def cog_load(self):
        # Register the persistent view so the panel button works after a restart.
        self.bot.add_view(TicketPanelView(self))

    # ------------------------------------------------------------ staff & config

    @staticmethod
    def _is_staff(member, cfg: dict | None) -> bool:
        if getattr(member, "guild_permissions", None) and member.guild_permissions.administrator:
            return True
        role_ids = (cfg or {}).get("role_ids") or []
        return any(r.id in role_ids for r in getattr(member, "roles", []))

    async def _cfg(self, guild_id: int) -> dict | None:
        db = self._db()
        return await db.get_setup(guild_id) if db else None

    async def _ensure_category(self, guild: discord.Guild, role_ids: list[int]) -> discord.CategoryChannel:
        """Return the ticket category, (re)creating it if missing."""
        db = self._db()
        cfg = await self._cfg(guild.id) if db else None
        category = guild.get_channel(cfg["category_id"]) if cfg and cfg.get("category_id") else None
        if isinstance(category, discord.CategoryChannel):
            return category
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_channels=True, manage_roles=True
            ),
        }
        for rid in role_ids:
            role = guild.get_role(rid)
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True
                )
        category = await guild.create_category("🎫 Tickets", overwrites=overwrites, reason="Ticket system setup")
        if db:
            await db.set_setup(guild.id, category_id=category.id)
        return category

    # ------------------------------------------------------------ /ticket (setup form)

    @commands.command(
        name="ticket",
        help="Open the ticket system setup form (admin): pick the panel channel and the roles to add to tickets, then Save.",
        usage="b.ticket",
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(manage_channels=True, manage_roles=True)
    async def ticket(self, ctx: commands.Context):
        await self._show_form(ctx)

    @app_commands.command(
        name="ticket", description="Open the ticket system setup form (admins only)"
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.checks.bot_has_permissions(manage_channels=True, manage_roles=True)
    async def slash_ticket(self, interaction: discord.Interaction):
        await self._show_form(interaction)

    async def _show_form(self, ctx):
        if self._db() is None:
            await u.reply(ctx, content="❌ Database not ready.")
            return
        is_interaction = isinstance(ctx, discord.Interaction)
        user_id = ctx.user.id if is_interaction else ctx.author.id
        view = TicketFormView(self, ctx.guild, user_id)
        if is_interaction:
            await ctx.response.send_message(embed=view._embed(), view=view, ephemeral=True)
        else:
            # Ephemeral isn't possible for prefix commands; the form is
            # restricted to the invoking admin instead.
            await ctx.send(embed=view._embed(), view=view)

    async def _save_setup(self, guild: discord.Guild, channel_id: int, role_ids: list[int]):
        db = self._db()
        if db is None:
            raise TicketError("Database not ready.")
        await db.set_setup(guild.id, panel_channel_id=channel_id, role_ids=role_ids)
        await self._ensure_category(guild, role_ids)
        channel = guild.get_channel(channel_id)
        if channel is None:
            raise TicketError("I can't see that channel.")
        await channel.send(content=PANEL_MESSAGE, view=TicketPanelView(self))

    # ------------------------------------------------------------ opening tickets

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
            logger.error(f"failed to open ticket: {e}", exc_info=True)
            await interaction.followup.send("Something went wrong creating your ticket.", ephemeral=True)
            return
        await interaction.followup.send(f"🎫 Your ticket has been created: {channel.mention}", ephemeral=True)

    async def _open_ticket(self, guild: discord.Guild, member: discord.Member) -> discord.TextChannel:
        db = self._db()
        if db is None:
            raise TicketError("The ticket database isn't ready right now. Try again in a moment.")
        cfg = await db.get_setup(guild.id)
        if cfg is None or not cfg.get("panel_channel_id"):
            raise TicketError("The ticket system isn't set up yet. Ask an admin to run `/ticket`.")
        existing = await db.get_open_ticket_by_user(guild.id, member.id)
        if existing:
            raise TicketError(
                f"You already have an open ticket: <#{existing['channel_id']}>. "
                "Please close it before opening a new one."
            )
        role_ids = cfg.get("role_ids") or []
        category = await self._ensure_category(guild, role_ids)
        staff_roles = [r for r in (guild.get_role(rid) for rid in role_ids) if r is not None]

        number = await db.next_ticket_number(guild.id)
        channel = await guild.create_text_channel(
            name=f"ticket-{number:04d}",
            category=category,
            overwrites=ticket_overwrites(guild, member, staff_roles, guild.me),
            reason=f"Ticket #{number} opened by {member}",
        )
        await db.create_ticket(guild.id, number, channel.id, member.id)

        embed = discord.Embed(
            title=f"🎫 Ticket #{number:04d}",
            description=f"{member.mention} describe your issue here and staff will be with you shortly.",
            color=TICKET_COLOR,
        )
        role_mentions = " ".join(r.mention for r in staff_roles) or "the admins"
        embed.add_field(name="Staff", value=f"Notified: {role_mentions}")
        embed.set_footer(text="Use /closeticket when your issue is resolved.")
        await channel.send(content=f"{member.mention} {role_mentions}", embed=embed)
        return channel

    # ------------------------------------------------------------ /closeticket

    @commands.command(
        name="closeticket",
        help="Close the ticket channel you're in. Needs approval: if staff requests it, the ticket creator approves (and vice versa). Then the creator gets an AI summary DM.",
        usage="b.closeticket",
    )
    @commands.guild_only()
    async def closeticket(self, ctx: commands.Context):
        await self._closeticket(ctx)

    @app_commands.command(
        name="closeticket", description="Close this ticket (needs the other side's approval)"
    )
    @app_commands.guild_only()
    async def slash_closeticket(self, interaction: discord.Interaction):
        await self._closeticket(interaction)

    async def _closeticket(self, ctx):
        db = self._db()
        if db is None:
            await u.reply(ctx, content="❌ Database not ready.")
            return
        channel = ctx.channel
        ticket = await db.get_ticket_by_channel(channel.id)
        if not ticket or ticket["status"] != "open":
            await u.reply(ctx, content="This channel isn't an open ticket.")
            return
        author = u.author_of(ctx)
        cfg = await db.get_setup(channel.guild.id)
        is_creator = author.id == ticket["creator_id"]
        is_staff = self._is_staff(author, cfg)
        if not (is_creator or is_staff):
            await u.reply(ctx, content="Only the ticket creator or staff can close tickets.")
            return

        if is_creator and is_staff:
            # You're both sides of the approval — no one left to ask.
            await u.reply(ctx, content="Closing ticket…")
            await self._finalize_close(channel, ticket, approver=author, requester_id=author.id)
            return

        if is_creator:
            view = CloseTicketView(
                ticket,
                check_approver=lambda m, _cfg=cfg: self._is_staff(m, _cfg),
                approver_desc="staff",
                requester_id=author.id,
                on_approve=self._make_approve_handler(ticket, author.id),
            )
            prompt = (
                f"✋ {author.mention} (the ticket creator) wants to close this ticket.\n"
                f"Staff: approve the close?"
            )
        else:
            view = CloseTicketView(
                ticket,
                check_approver=lambda m, _cid=ticket["creator_id"]: m.id == _cid,
                approver_desc="the ticket creator",
                requester_id=author.id,
                on_approve=self._make_approve_handler(ticket, author.id),
            )
            prompt = (
                f"✋ Staff member {author.mention} wants to close this ticket.\n"
                f"<@{ticket['creator_id']}>: approve the close?"
            )
        embed = discord.Embed(description=prompt, color=CLOSE_COLOR)
        embed.set_footer(text=f"Request expires in {CLOSE_TIMEOUT_SECONDS // 60} minutes.")
        if isinstance(ctx, discord.Interaction):
            await ctx.response.send_message(embed=embed, view=view)
            view.message = await ctx.original_response()
        else:
            view.message = await ctx.send(embed=embed, view=view)

    def _make_approve_handler(self, ticket: dict, requester_id: int):
        async def handle(interaction: discord.Interaction):
            await self._finalize_close(
                interaction.channel, ticket, approver=interaction.user, requester_id=requester_id
            )

        return handle

    async def _finalize_close(self, channel, ticket: dict, approver, requester_id: int):
        db = self._db()
        if db:
            await db.close_ticket(channel.id, approver.id, f"Requested by user {requester_id}")

        embed = discord.Embed(
            title=f"🔒 Ticket #{ticket['ticket_id']:04d} closed",
            description=(
                f"Approved by {approver.mention} (requested by <@{requester_id}>).\n"
                "The ticket creator will get a summary DM, then this channel is deleted."
            ),
            color=CLOSE_COLOR,
        )
        await channel.send(embed=embed)

        summary = await self._ai_summary(channel.guild, ticket, channel)
        creator = channel.guild.get_member(ticket["creator_id"])
        if creator is not None:
            dm = discord.Embed(
                title=f"🎫 Ticket #{ticket['ticket_id']:04d} closed",
                description=f"Your ticket in **{channel.guild.name}** was closed.",
                color=TICKET_COLOR,
            )
            dm.add_field(
                name="Summary",
                value=summary
                or "No AI summary was available (ask an admin to configure the AI with /aichat).",
                inline=False,
            )
            try:
                await creator.send(embed=dm)
            except (discord.Forbidden, discord.HTTPException):
                logger.warning(f"couldn't DM ticket summary to user {ticket['creator_id']}")

        await asyncio.sleep(CLOSE_DELETE_DELAY)
        try:
            await channel.delete(reason=f"Ticket closed by {approver}")
        except discord.Forbidden:
            await channel.send("I couldn't delete this channel — please remove it manually.")

    async def collect_transcript(self, channel, ticket: dict) -> str:
        messages = [m async for m in channel.history(limit=TRANSCRIPT_MAX_MESSAGES, oldest_first=True)]
        return format_transcript(ticket, channel.name, messages)

    async def _ai_summary(self, guild, ticket: dict, channel) -> str | None:
        """Summarize the ticket with the AI configured via /aichat, if any."""
        cog = self.bot.get_cog("AIChat")
        if cog is None:
            return None
        try:
            config = await cog._load_config(guild.id)
        except Exception as e:
            logger.error(f"couldn't load AI chat config: {e}")
            return None
        if not config:
            return None
        provider, model_id, api_key = (
            config.get("provider"),
            config.get("model_id"),
            config.get("api_key"),
        )
        if not (provider and model_id and api_key):
            return None
        try:
            transcript = await self.collect_transcript(channel, ticket)
            response = await cog.service.generate_response(
                provider=provider,
                model_id=model_id,
                api_key=api_key,
                user_message="Summarize this support ticket transcript:\n\n"
                + transcript[-TRANSCRIPT_MAX_CHARS:],
                system_prompt=AI_SUMMARY_PROMPT,
            )
            return (response or "").strip() or None
        except Exception as e:
            logger.error(f"ticket AI summary failed: {e}")
            return None

    # ------------------------------------------------------------ listeners

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        """Mark tickets closed if their channel is deleted without a close."""
        db = self._db()
        if db is None or getattr(channel, "guild", None) is None:
            return
        try:
            ticket = await db.get_ticket_by_channel(channel.id)
            if ticket and ticket["status"] == "open":
                await db.close_ticket(channel.id, closed_by=None, reason="Channel deleted manually")
        except Exception as e:
            logger.error(f"failed to record manual ticket deletion: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
