"""Persistent, GUI-driven Discord giveaway system."""

import logging
import re
import secrets
import string
from collections.abc import Callable
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from economy import giveaway_config as cfg
from economy.giveaways_db import utc_ts

logger = logging.getLogger(__name__)

ENTER_ID = "bloop:giveaway:enter"
PARTICIPANTS_ID = "bloop:giveaway:participants"
DURATION_RE = re.compile(r"(?i)(\d+)\s*([wdhms])")


class GiveawayUserError(Exception):
    """A safe, actionable error that may be shown to a Discord user."""


def parse_duration(value: str) -> int:
    """Parse values such as 2d, 1h30m, or 45s into seconds."""
    text = (value or "").strip().replace(" ", "")
    if not text:
        raise ValueError("Duration is required.")
    units = {"w": 604800, "d": 86400, "h": 3600, "m": 60, "s": 1}
    matches = list(DURATION_RE.finditer(text))
    if not matches or "".join(m.group(0) for m in matches).lower() != text.lower():
        raise ValueError("Use a duration like `2d`, `1h30m`, or `45s`.")
    seconds = sum(int(m.group(1)) * units[m.group(2).lower()] for m in matches)
    if seconds < 10:
        raise ValueError("Duration must be at least 10 seconds.")
    if seconds > cfg.MAX_DURATION_SECONDS:
        raise ValueError(f"Duration cannot exceed {cfg.MAX_DURATION_SECONDS // 86400} days.")
    return seconds


def duration_text(seconds: int) -> str:
    parts = []
    for size, suffix in ((604800, "w"), (86400, "d"), (3600, "h"), (60, "m"), (1, "s")):
        if seconds >= size:
            amount, seconds = divmod(seconds, size)
            parts.append(f"{amount}{suffix}")
    return " ".join(parts) or "0s"


def has_admin_permission(member: discord.Member) -> bool:
    return bool(getattr(member.guild_permissions, cfg.REQUIRED_ADMIN_PERMISSION, False))


def bool_value(value: str, name: str) -> bool:
    normalized = (value or "").strip().lower()
    if normalized in {"yes", "y", "true", "on", "1"}:
        return True
    if normalized in {"no", "n", "false", "off", "0"}:
        return False
    raise ValueError(f"{name} must be yes or no.")


def default_draft(guild: discord.Guild, host_id: int) -> dict:
    return {
        "guild_id": guild.id,
        "host_id": host_id,
        "prize": "",
        "description": "",
        "winners_count": cfg.DEFAULT_WINNERS,
        "duration": cfg.DEFAULT_DURATION_SECONDS,
        "channel_id": None,
        "requirements": {
            "required_role_id": None,
            "allowed_role_ids": [],
            "blacklisted_role_ids": [],
            "minimum_account_age_days": 0,
            "minimum_membership_days": 0,
            "minimum_invites": 0,
            "required_channel_id": None,
            "custom_rules": {},
        },
        "bonus_entries": {},
        "settings": {
            "image_url": "",
            "thumbnail_url": "",
            "color": cfg.DEFAULT_COLOR,
            "allow_bots": cfg.DEFAULT_ALLOW_BOTS,
            "allow_host": cfg.DEFAULT_ALLOW_HOST,
            "allow_multiple_entries": cfg.DEFAULT_ALLOW_MULTIPLE_ENTRIES,
            "max_entries_per_user": cfg.DEFAULT_MAX_ENTRIES_PER_USER,
            "allow_previous_winners": cfg.DEFAULT_ALLOW_PREVIOUS_WINNERS,
            "allow_duplicate_winners": False,
            "announce_winners": True,
            "ping_winners": True,
            "announcement_message": "Congratulations! 🎉",
        },
    }


def requirements_lines(giveaway: dict) -> list[str]:
    req = giveaway.get("requirements") or {}
    lines = []
    if req.get("required_role_id"):
        lines.append(f"• Must have <@&{req['required_role_id']}>")
    if req.get("allowed_role_ids"):
        lines.append("• Must have one of: " + ", ".join(f"<@&{r}>" for r in req["allowed_role_ids"]))
    if req.get("blacklisted_role_ids"):
        lines.append("• Cannot have: " + ", ".join(f"<@&{r}>" for r in req["blacklisted_role_ids"]))
    if req.get("minimum_account_age_days"):
        lines.append(f"• Account must be {req['minimum_account_age_days']}+ days old")
    if req.get("minimum_membership_days"):
        lines.append(f"• Server member for {req['minimum_membership_days']}+ days")
    if req.get("minimum_invites"):
        lines.append(f"• Must have {req['minimum_invites']}+ tracked invites")
    if req.get("required_channel_id"):
        lines.append(f"• Must be able to view <#{req['required_channel_id']}>")
    for name, value in (req.get("custom_rules") or {}).items():
        label = "Minimum Bloop level" if name == "bloop_level" else name.replace("_", " ").title()
        lines.append(f"• {label}: {value}")
    if not (giveaway.get("settings") or {}).get("allow_bots", False):
        lines.append("• Bots cannot enter")
    return lines or ["• None — everyone can enter"]


def giveaway_embed(giveaway: dict, counts: dict, *, preview: bool = False) -> discord.Embed:
    settings = giveaway.get("settings") or {}
    status = giveaway.get("status", "active")
    color = int(settings.get("color") or cfg.DEFAULT_COLOR)
    title = "🎉 GIVEAWAY 🎉" if status == "active" else ("🎉 GIVEAWAY ENDED" if status == "ended" else "❌ GIVEAWAY CANCELLED")
    embed = discord.Embed(title=title, color=color, description=giveaway.get("description") or None)
    embed.add_field(name="🎁 Prize", value=f"**{giveaway.get('prize') or 'Not configured'}**", inline=False)
    embed.add_field(name="🏆 Winners", value=str(giveaway.get("winners_count", 1)), inline=True)
    end_time = giveaway.get("end_time") or (utc_ts() + int(giveaway.get("duration", cfg.DEFAULT_DURATION_SECONDS)))
    embed.add_field(name="⏰ Ends", value=f"<t:{end_time}:R>\n<t:{end_time}:F>", inline=True)
    embed.add_field(name="👥 Participants", value=f"{counts.get('users', 0)} ({counts.get('entries', 0)} weighted entries)", inline=True)
    embed.add_field(name="Requirements", value="\n".join(requirements_lines(giveaway))[:1024], inline=False)
    winners = giveaway.get("winner_ids") or []
    if status == "ended":
        embed.add_field(name="🏆 Winners", value="\n".join(f"<@{u}>" for u in winners) or "No eligible winners", inline=False)
    if settings.get("thumbnail_url"):
        embed.set_thumbnail(url=settings["thumbnail_url"])
    if settings.get("image_url"):
        embed.set_image(url=settings["image_url"])
    giveaway_id = giveaway.get("giveaway_id", "Preview")
    host_id = giveaway.get("host_id")
    embed.set_footer(text=f"Giveaway ID: {giveaway_id} • Host: {host_id or 'Preview'} • Status: {status.title()}")
    return embed


def creation_embed(draft: dict, *, editing: bool = False) -> discord.Embed:
    req_count = sum(bool(v) for v in draft["requirements"].values())
    settings = draft["settings"]
    embed = discord.Embed(
        title="✏️ Edit Giveaway" if editing else "🎉 Create Giveaway",
        description="Configure each section, preview the member-facing post, then publish." if not editing else "Change the settings below and save to update the original message.",
        color=int(settings.get("color", cfg.DEFAULT_COLOR)),
    )
    embed.add_field(name="🎁 Prize", value=draft.get("prize") or "❌ Not set", inline=False)
    embed.add_field(name="🏆 Winners", value=str(draft["winners_count"]), inline=True)
    embed.add_field(name="⏱️ Duration", value=duration_text(int(draft["duration"])), inline=True)
    embed.add_field(name="📣 Channel", value=f"<#{draft['channel_id']}>" if draft.get("channel_id") else "❌ Not set", inline=True)
    embed.add_field(name="🛡️ Requirements", value=f"{req_count} configured", inline=True)
    embed.add_field(name="🎟️ Bonus roles", value=str(len(draft["bonus_entries"])), inline=True)
    embed.add_field(name="🖼️ Appearance", value="Custom image" if settings.get("image_url") or settings.get("thumbnail_url") else "Default", inline=True)
    embed.add_field(
        name="⚙️ Entry settings",
        value=(f"Multiple: **{'Yes' if settings['allow_multiple_entries'] else 'No'}** • "
               f"Max: **{settings['max_entries_per_user']}** • Bots: **{'Yes' if settings['allow_bots'] else 'No'}**"),
        inline=False,
    )
    embed.set_footer(text="Only the administrator who opened this panel can use it.")
    return embed


class GiveawayPublicView(discord.ui.View):
    """One persistent view routes all published giveaway buttons by message ID."""

    def __init__(self, cog: "Giveaway | None" = None, disabled: bool = False):
        super().__init__(timeout=None)
        self.cog = cog
        if disabled:
            for item in self.children:
                item.disabled = True

    @discord.ui.button(label="Enter Giveaway", emoji="🎉", style=discord.ButtonStyle.success, custom_id=ENTER_ID)
    async def enter(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.cog is None:
            await interaction.response.send_message("The giveaway system is starting. Try again shortly.", ephemeral=True)
            return
        await self.cog.enter_giveaway(interaction)

    @discord.ui.button(label="Participants", emoji="👥", style=discord.ButtonStyle.secondary, custom_id=PARTICIPANTS_ID)
    async def participants(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.cog is None:
            await interaction.response.send_message("The giveaway system is starting. Try again shortly.", ephemeral=True)
            return
        await self.cog.show_public_participants(interaction)


class PrizeModal(discord.ui.Modal, title="Giveaway Prize"):
    prize = discord.ui.TextInput(label="Prize", max_length=200, placeholder="Discord Nitro")
    description = discord.ui.TextInput(label="Description", style=discord.TextStyle.paragraph, required=False, max_length=1500)

    def __init__(self, view: "CreationView"):
        super().__init__()
        self.parent_view = view
        self.prize.default = view.draft.get("prize", "")
        self.description.default = view.draft.get("description", "")

    async def on_submit(self, interaction):
        self.parent_view.draft["prize"] = str(self.prize).strip()
        self.parent_view.draft["description"] = str(self.description).strip()
        await interaction.response.edit_message(embed=creation_embed(self.parent_view.draft, editing=self.parent_view.edit_id is not None), view=self.parent_view)


class WinnersModal(discord.ui.Modal, title="Winner Count"):
    winners = discord.ui.TextInput(label="Number of winners", max_length=2, placeholder="1")

    def __init__(self, view):
        super().__init__(); self.parent_view = view; self.winners.default = str(view.draft["winners_count"])

    async def on_submit(self, interaction):
        try:
            value = int(str(self.winners)); assert 1 <= value <= cfg.MAX_WINNERS
        except (ValueError, AssertionError):
            await interaction.response.send_message(f"Winner count must be 1–{cfg.MAX_WINNERS}.", ephemeral=True); return
        self.parent_view.draft["winners_count"] = value
        await interaction.response.edit_message(embed=creation_embed(self.parent_view.draft, editing=self.parent_view.edit_id is not None), view=self.parent_view)


class DurationModal(discord.ui.Modal, title="Giveaway Duration"):
    duration = discord.ui.TextInput(label="Duration", placeholder="1d12h", max_length=30)

    def __init__(self, view):
        super().__init__(); self.parent_view = view; self.duration.default = duration_text(view.draft["duration"]).replace(" ", "")

    async def on_submit(self, interaction):
        try: self.parent_view.draft["duration"] = parse_duration(str(self.duration))
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True); return
        await interaction.response.edit_message(embed=creation_embed(self.parent_view.draft, editing=self.parent_view.edit_id is not None), view=self.parent_view)


class AppearanceModal(discord.ui.Modal, title="Giveaway Appearance"):
    image = discord.ui.TextInput(label="Large image URL", required=False, max_length=500)
    thumbnail = discord.ui.TextInput(label="Thumbnail URL", required=False, max_length=500)
    color = discord.ui.TextInput(label="Embed color (hex)", required=False, placeholder="#F59E0B", max_length=7)

    def __init__(self, view):
        super().__init__(); self.parent_view = view
        s = view.draft["settings"]
        self.image.default, self.thumbnail.default, self.color.default = s.get("image_url", ""), s.get("thumbnail_url", ""), f"#{int(s.get('color', cfg.DEFAULT_COLOR)):06X}"

    async def on_submit(self, interaction):
        image, thumb, color = str(self.image).strip(), str(self.thumbnail).strip(), str(self.color).strip().lstrip("#")
        if image and not image.startswith(("https://", "http://")) or thumb and not thumb.startswith(("https://", "http://")):
            await interaction.response.send_message("Image URLs must start with http:// or https://.", ephemeral=True); return
        try: parsed = int(color, 16) if color else cfg.DEFAULT_COLOR; assert 0 <= parsed <= 0xFFFFFF
        except (ValueError, AssertionError):
            await interaction.response.send_message("Color must be a valid hex value such as #F59E0B.", ephemeral=True); return
        self.parent_view.draft["settings"].update(image_url=image, thumbnail_url=thumb, color=parsed)
        await interaction.response.edit_message(embed=creation_embed(self.parent_view.draft, editing=self.parent_view.edit_id is not None), view=self.parent_view)


class LimitsModal(discord.ui.Modal, title="Eligibility Limits"):
    account = discord.ui.TextInput(label="Minimum account age (days)", default="0", max_length=5)
    membership = discord.ui.TextInput(label="Minimum server membership (days)", default="0", max_length=5)
    invites = discord.ui.TextInput(label="Required invites", default="0", max_length=5)
    custom = discord.ui.TextInput(label="Custom rules (key:value)", required=False, placeholder="bloop_level:10", max_length=200)

    def __init__(self, view):
        super().__init__(); self.parent_view = view; r = view.draft["requirements"]
        self.account.default, self.membership.default, self.invites.default = str(r.get("minimum_account_age_days", 0)), str(r.get("minimum_membership_days", 0)), str(r.get("minimum_invites", 0))
        self.custom.default = ", ".join(f"{key}:{value}" for key, value in (r.get("custom_rules") or {}).items())

    async def on_submit(self, interaction):
        try:
            values = [int(str(x)) for x in (self.account, self.membership, self.invites)]
            if any(v < 0 or v > 100000 for v in values): raise ValueError
            custom_rules = {}
            available = self.parent_view.parent_view.cog.custom_eligibility_rules
            for raw in filter(None, (item.strip() for item in str(self.custom).split(","))):
                name, custom_value = raw.split(":", 1)
                name, custom_value = name.strip().lower(), int(custom_value.strip())
                if name not in available or custom_value < 0:
                    raise ValueError
                custom_rules[name] = custom_value
        except (ValueError, TypeError):
            await interaction.response.send_message("Age/invite values must be non-negative numbers. Supported custom rule: `bloop_level:<number>`.", ephemeral=True); return
        self.parent_view.draft["requirements"].update(minimum_account_age_days=values[0], minimum_membership_days=values[1], minimum_invites=values[2], custom_rules=custom_rules)
        await interaction.response.edit_message(embed=self.parent_view._embed(), view=self.parent_view)


class AdvancedModal(discord.ui.Modal, title="Advanced Entry Settings"):
    toggles = discord.ui.TextInput(label="Multiple entries, Bots, Host (yes/no)", placeholder="no, no, no", max_length=30)
    maximum = discord.ui.TextInput(label="Maximum base entries per user", default="1", max_length=2)
    bonus = discord.ui.TextInput(label="Bonus roles: role_id:+entries", required=False, placeholder="123456:+2, 789012:+3", max_length=400)
    reroll = discord.ui.TextInput(label="Previous winners, Ping, Duplicate wins", placeholder="no, yes, no", default="no, yes, no", max_length=30)
    announcement = discord.ui.TextInput(label="Winner message (blank disables announcement)", required=False, default="Congratulations! 🎉", max_length=500)

    def __init__(self, view):
        super().__init__(); self.parent_view = view; s = view.draft["settings"]
        self.toggles.default = ", ".join("yes" if s[k] else "no" for k in ("allow_multiple_entries", "allow_bots", "allow_host"))
        self.maximum.default = str(s["max_entries_per_user"])
        self.bonus.default = ", ".join(f"{rid}:+{extra}" for rid, extra in view.draft["bonus_entries"].items())
        self.reroll.default = ", ".join((
            "yes" if s["allow_previous_winners"] else "no",
            "yes" if s.get("ping_winners", True) else "no",
            "yes" if s.get("allow_duplicate_winners", False) else "no",
        ))
        self.announcement.default = s.get("announcement_message", "") if s.get("announce_winners", True) else ""

    async def on_submit(self, interaction):
        try:
            toggle_parts = [x.strip() for x in str(self.toggles).split(",")]
            if len(toggle_parts) != 3: raise ValueError("Provide exactly three yes/no values for Multiple entries, Bots, Host.")
            toggles = [bool_value(v, "Each toggle") for v in toggle_parts]
            maximum = int(str(self.maximum));
            if not 1 <= maximum <= cfg.MAX_ENTRIES_PER_USER: raise ValueError(f"Maximum entries must be 1–{cfg.MAX_ENTRIES_PER_USER}.")
            bonuses = {}
            for item in filter(None, (x.strip() for x in str(self.bonus).split(","))):
                role, extra = item.replace("+", "").split(":", 1)
                rid, amount = int(role.strip().strip("<@&>")), int(extra)
                if self.parent_view.guild.get_role(rid) is None or not 1 <= amount <= 100: raise ValueError("Every bonus role must exist and award 1–100 entries.")
                bonuses[str(rid)] = amount
            reroll_parts = [x.strip() for x in str(self.reroll).split(",")]
            if len(reroll_parts) != 3: raise ValueError("Provide three yes/no values for Previous winners, Ping, Duplicate wins.")
            reroll_settings = [bool_value(v, "Each reroll setting") for v in reroll_parts]
        except (ValueError, TypeError) as exc:
            await interaction.response.send_message(str(exc) or "Invalid advanced settings.", ephemeral=True); return
        announcement = str(self.announcement).strip()
        self.parent_view.draft["bonus_entries"] = bonuses
        self.parent_view.draft["settings"].update(allow_multiple_entries=toggles[0], allow_bots=toggles[1], allow_host=toggles[2], max_entries_per_user=maximum, allow_previous_winners=reroll_settings[0], ping_winners=reroll_settings[1], allow_duplicate_winners=reroll_settings[2], announce_winners=bool(announcement), announcement_message=announcement)
        await interaction.response.edit_message(embed=creation_embed(self.parent_view.draft, editing=self.parent_view.edit_id is not None), view=self.parent_view)


class ChannelPicker(discord.ui.View):
    def __init__(self, parent):
        super().__init__(timeout=300); self.parent_view = parent

    async def interaction_check(self, interaction): return await self.parent_view.interaction_check(interaction)

    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.text, discord.ChannelType.news], placeholder="Select the giveaway channel")
    async def channel(self, interaction, select):
        selected = select.values[0]
        resolved = self.parent_view.guild.get_channel(selected.id)
        if resolved is None:
            await interaction.response.send_message("That channel is unavailable.", ephemeral=True); return
        perms = resolved.permissions_for(self.parent_view.guild.me)
        if not (
            perms.view_channel
            and perms.send_messages
            and perms.embed_links
            and perms.read_message_history
        ):
            await interaction.response.send_message(
                "I need View Channel, Send Messages, Embed Links, and Read Message History there.",
                ephemeral=True,
            )
            return
        self.parent_view.draft["channel_id"] = selected.id
        await interaction.response.edit_message(embed=creation_embed(self.parent_view.draft, editing=self.parent_view.edit_id is not None), view=self.parent_view)

    @discord.ui.button(label="Back", emoji="↩️")
    async def back(self, interaction, button):
        await interaction.response.edit_message(embed=creation_embed(self.parent_view.draft, editing=self.parent_view.edit_id is not None), view=self.parent_view)


class RequirementsView(discord.ui.View):
    def __init__(self, parent):
        super().__init__(timeout=600); self.parent_view = parent; self.draft = parent.draft

    async def interaction_check(self, interaction): return await self.parent_view.interaction_check(interaction)

    def _embed(self):
        return discord.Embed(title="🛡️ Giveaway Requirements", description="Choose roles below. Empty selections clear a requirement.\n\n" + "\n".join(requirements_lines(self.draft)), color=cfg.DEFAULT_COLOR)

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="Required role (optional)", min_values=0, max_values=1, row=0)
    async def required(self, interaction, select):
        self.draft["requirements"]["required_role_id"] = select.values[0].id if select.values else None
        await interaction.response.edit_message(embed=self._embed(), view=self)

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="Allowed roles — member needs one (optional)", min_values=0, max_values=10, row=1)
    async def allowed(self, interaction, select):
        self.draft["requirements"]["allowed_role_ids"] = [r.id for r in select.values]
        await interaction.response.edit_message(embed=self._embed(), view=self)

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="Blacklisted roles (optional)", min_values=0, max_values=10, row=2)
    async def blacklist(self, interaction, select):
        self.draft["requirements"]["blacklisted_role_ids"] = [r.id for r in select.values]
        await interaction.response.edit_message(embed=self._embed(), view=self)

    @discord.ui.button(label="Age, Invites & Membership", emoji="⏳", style=discord.ButtonStyle.primary, row=3)
    async def limits(self, interaction, button): await interaction.response.send_modal(LimitsModal(self))

    @discord.ui.button(label="Back", emoji="↩️", row=3)
    async def back(self, interaction, button):
        await interaction.response.edit_message(embed=creation_embed(self.draft, editing=self.parent_view.edit_id is not None), view=self.parent_view)

    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.text, discord.ChannelType.news], placeholder="Required visible channel (optional)", min_values=0, max_values=1, row=4)
    async def required_channel(self, interaction, select):
        self.draft["requirements"]["required_channel_id"] = select.values[0].id if select.values else None
        await interaction.response.edit_message(embed=self._embed(), view=self)


class CreationView(discord.ui.View):
    def __init__(self, cog: "Giveaway", guild: discord.Guild, owner_id: int, draft: dict | None = None, edit_id: str | None = None):
        super().__init__(timeout=900); self.cog, self.guild, self.owner_id = cog, guild, owner_id
        self.draft, self.edit_id = draft or default_draft(guild, owner_id), edit_id
        if edit_id:
            self.publish.label = "Save Changes"; self.publish.emoji = "💾"
            self.channel.disabled = True

    async def interaction_check(self, interaction):
        if interaction.guild_id != self.guild.id or interaction.user.id != self.owner_id:
            await interaction.response.send_message("Only the administrator who opened this panel can use it.", ephemeral=True); return False
        if not has_admin_permission(interaction.user):
            await interaction.response.send_message("You need Manage Server to use this panel.", ephemeral=True); return False
        return True

    @discord.ui.button(label="Prize", emoji="🎁", style=discord.ButtonStyle.primary, row=0)
    async def prize(self, interaction, button): await interaction.response.send_modal(PrizeModal(self))
    @discord.ui.button(label="Winners", emoji="🏆", style=discord.ButtonStyle.primary, row=0)
    async def winners(self, interaction, button): await interaction.response.send_modal(WinnersModal(self))
    @discord.ui.button(label="Duration", emoji="⏱️", style=discord.ButtonStyle.primary, row=0)
    async def duration(self, interaction, button): await interaction.response.send_modal(DurationModal(self))
    @discord.ui.button(label="Channel", emoji="📣", style=discord.ButtonStyle.primary, row=0)
    async def channel(self, interaction, button): await interaction.response.edit_message(embed=discord.Embed(title="📣 Giveaway Channel", description="Choose where the giveaway will be published.", color=cfg.DEFAULT_COLOR), view=ChannelPicker(self))
    @discord.ui.button(label="Requirements", emoji="🛡️", style=discord.ButtonStyle.primary, row=0)
    async def requirements(self, interaction, button):
        view = RequirementsView(self); await interaction.response.edit_message(embed=view._embed(), view=view)
    @discord.ui.button(label="Appearance", emoji="🖼️", style=discord.ButtonStyle.secondary, row=1)
    async def appearance(self, interaction, button): await interaction.response.send_modal(AppearanceModal(self))
    @discord.ui.button(label="Advanced Settings", emoji="⚙️", style=discord.ButtonStyle.secondary, row=1)
    async def advanced(self, interaction, button): await interaction.response.send_modal(AdvancedModal(self))
    @discord.ui.button(label="Preview", emoji="👁️", style=discord.ButtonStyle.secondary, row=1)
    async def preview(self, interaction, button):
        preview = dict(self.draft); preview["status"] = "active"; preview["end_time"] = utc_ts() + preview["duration"]
        await interaction.response.edit_message(
            content="**Member-facing preview:**",
            embed=giveaway_embed(preview, {"users": 0, "entries": 0}, preview=True),
            view=PreviewBackView(self),
        )
    @discord.ui.button(label="Create Giveaway", emoji="🚀", style=discord.ButtonStyle.success, row=1)
    async def publish(self, interaction, button):
        await interaction.response.defer(ephemeral=True)
        try:
            if self.edit_id: await self.cog.save_edit(interaction, self.edit_id, self.draft)
            else: await self.cog.publish(interaction, self.draft)
            for item in self.children: item.disabled = True
            await interaction.edit_original_response(embed=creation_embed(self.draft, editing=self.edit_id is not None), view=self)
            self.stop()
        except GiveawayUserError as exc: await interaction.followup.send(f"❌ {exc}", ephemeral=True)
        except Exception:
            logger.exception("Giveaway publish/edit failed"); await interaction.followup.send("❌ The giveaway could not be saved. Nothing was duplicated; please try again.", ephemeral=True)
    @discord.ui.button(label="Cancel", emoji="✖️", style=discord.ButtonStyle.danger, row=1)
    async def cancel(self, interaction, button):
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(content="Giveaway setup cancelled.", embed=None, view=self); self.stop()


class PreviewBackView(discord.ui.View):
    def __init__(self, parent): super().__init__(timeout=300); self.parent_view = parent
    async def interaction_check(self, interaction): return await self.parent_view.interaction_check(interaction)
    @discord.ui.button(label="Back to Editor", emoji="↩️")
    async def back(self, interaction, button): await interaction.response.edit_message(content=None, embed=creation_embed(self.parent_view.draft, editing=self.parent_view.edit_id is not None), view=self.parent_view)

class ConfirmView(discord.ui.View):
    def __init__(self, owner_id: int, prompt: str, callback: Callable, *, danger: bool = True):
        super().__init__(timeout=60); self.owner_id, self.prompt, self.callback = owner_id, prompt, callback
        self.confirm.style = discord.ButtonStyle.danger if danger else discord.ButtonStyle.success

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id or not has_admin_permission(interaction.user):
            await interaction.response.send_message("This confirmation belongs to another administrator.", ephemeral=True); return False
        return True

    @discord.ui.button(label="Confirm", emoji="✅")
    async def confirm(self, interaction, button):
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(content=f"Processing: {self.prompt}", view=self)
        try: await self.callback(interaction)
        except GiveawayUserError as exc: await interaction.followup.send(f"❌ {exc}", ephemeral=True)
        except Exception:
            logger.exception("Confirmed giveaway action failed"); await interaction.followup.send("❌ That action failed unexpectedly. Please retry.", ephemeral=True)
        self.stop()

    @discord.ui.button(label="Cancel", emoji="❌", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(content="Action cancelled.", view=self); self.stop()


class ParticipantPages(discord.ui.View):
    def __init__(self, cog: "Giveaway", giveaway: dict, entries: list[dict], owner_id: int, admin: bool):
        super().__init__(timeout=300); self.cog, self.giveaway, self.entries = cog, giveaway, entries
        self.owner_id, self.admin, self.page = owner_id, admin, 0
        self.page_size = 15
        if not admin:
            self.previous.disabled = self.next.disabled = True

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id or interaction.guild_id != self.giveaway["guild_id"]:
            await interaction.response.send_message("This participant panel is not yours.", ephemeral=True); return False
        return True

    def embed(self) -> discord.Embed:
        total_weight = sum(e["base_entries"] + e["bonus_entries"] for e in self.entries)
        embed = discord.Embed(title=f"👥 Participants — {self.giveaway['giveaway_id']}", color=cfg.DEFAULT_COLOR)
        embed.description = f"**Unique participants:** {len(self.entries)}\n**Weighted entries:** {total_weight}"
        own = next((e for e in self.entries if e["user_id"] == self.owner_id), None)
        embed.add_field(name="Your entry", value=(f"Entered • {own['base_entries']} base + {own['bonus_entries']} bonus" if own else "Not entered"), inline=False)
        if self.admin:
            start = self.page * self.page_size
            rows = self.entries[start:start + self.page_size]
            embed.add_field(name="Administrator participant list", value="\n".join(f"<@{e['user_id']}> — {e['base_entries']} base + {e['bonus_entries']} bonus" for e in rows) or "No participants", inline=False)
            pages = max(1, (len(self.entries) + self.page_size - 1) // self.page_size)
            embed.set_footer(text=f"Page {self.page + 1}/{pages} • Public users cannot see this list")
        return embed

    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction, button): self.page = max(0, self.page - 1); await interaction.response.edit_message(embed=self.embed(), view=self)
    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.secondary)
    async def next(self, interaction, button):
        pages = max(1, (len(self.entries) + self.page_size - 1) // self.page_size); self.page = min(pages - 1, self.page + 1)
        await interaction.response.edit_message(embed=self.embed(), view=self)


class ActiveListView(discord.ui.View):
    def __init__(self, owner_id: int, rows: list[tuple[dict, dict]]):
        super().__init__(timeout=300)
        self.owner_id, self.rows, self.page = owner_id, rows, 0
        self.page_size = 10
        self._sync()

    def _sync(self):
        pages = max(1, (len(self.rows) + self.page_size - 1) // self.page_size)
        self.previous.disabled = self.page == 0
        self.next.disabled = self.page >= pages - 1

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Run `/giveaway list` to open your own browser.", ephemeral=True
            )
            return False
        return True

    def embed(self) -> discord.Embed:
        embed = discord.Embed(title="🎉 Active Giveaways", color=cfg.DEFAULT_COLOR)
        if not self.rows:
            embed.description = "There are no active giveaways right now."
            return embed
        start = self.page * self.page_size
        lines = []
        for giveaway, counts in self.rows[start : start + self.page_size]:
            lines.append(
                f"**{giveaway['prize']}** — `{giveaway['giveaway_id']}`\n"
                f"<#{giveaway['channel_id']}> • {counts['users']} participants • "
                f"ends <t:{giveaway['end_time']}:R>"
            )
        pages = max(1, (len(self.rows) + self.page_size - 1) // self.page_size)
        embed.description = "\n\n".join(lines)
        embed.set_footer(text=f"Page {self.page + 1}/{pages} • {len(self.rows)} active giveaways")
        return embed

    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction, button):
        self.page = max(0, self.page - 1)
        self._sync()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.secondary)
    async def next(self, interaction, button):
        pages = max(1, (len(self.rows) + self.page_size - 1) // self.page_size)
        self.page = min(pages - 1, self.page + 1)
        self._sync()
        await interaction.response.edit_message(embed=self.embed(), view=self)


class DashboardView(discord.ui.View):
    def __init__(self, cog: "Giveaway", guild: discord.Guild, owner_id: int, giveaways: list[dict], history: bool = False):
        super().__init__(timeout=600); self.cog, self.guild, self.owner_id = cog, guild, owner_id
        self.giveaways, self.page, self.history = giveaways, 0, history
        self._sync()

    def _sync(self):
        has = bool(self.giveaways); g = self.giveaways[self.page] if has else None
        self.previous.disabled = self.page <= 0; self.next.disabled = self.page >= len(self.giveaways) - 1
        active = bool(g and g["status"] == "active")
        self.edit.disabled = self.end.disabled = self.cancel_giveaway.disabled = not active
        self.reroll.disabled = not bool(g and g["status"] == "ended")
        self.participants.disabled = not has

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id or interaction.guild_id != self.guild.id or not has_admin_permission(interaction.user):
            await interaction.response.send_message("This dashboard belongs to another administrator.", ephemeral=True); return False
        return True

    async def embed(self):
        title = "📚 Giveaway History" if self.history else "🎛️ Active Giveaways"
        embed = discord.Embed(title=title, color=cfg.DEFAULT_COLOR)
        if not self.giveaways:
            embed.description = "No giveaways found."; return embed
        g = self.giveaways[self.page]; counts = await self.cog.db.counts(g["giveaway_id"])
        embed.description = f"### 🎁 {g['prize']}\n**ID:** `{g['giveaway_id']}`\n**Status:** {g['status'].title()}\n**Channel:** <#{g['channel_id']}>\n**Host:** <@{g['host_id']}>\n**Ends:** <t:{g['end_time']}:R>\n**Participants:** {counts['users']} ({counts['entries']} weighted)\n**Winners:** {g['winners_count']}"
        embed.set_footer(text=f"Giveaway {self.page + 1}/{len(self.giveaways)}")
        return embed

    async def refresh(self, interaction): self._sync(); await interaction.response.edit_message(embed=await self.embed(), view=self)
    @discord.ui.button(emoji="◀️", row=0)
    async def previous(self, interaction, button): self.page = max(0, self.page - 1); await self.refresh(interaction)
    @discord.ui.button(emoji="▶️", row=0)
    async def next(self, interaction, button): self.page = min(len(self.giveaways) - 1, self.page + 1); await self.refresh(interaction)
    @discord.ui.button(label="Statistics", emoji="📊", style=discord.ButtonStyle.secondary, row=0)
    async def statistics(self, interaction, button): await self.cog.send_statistics(interaction)
    @discord.ui.button(label="History/Active", emoji="📚", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_history(self, interaction, button):
        self.history = not self.history; self.giveaways = await self.cog.db.list_guild(self.guild.id, None if self.history else "active"); self.page = 0
        self._sync(); await interaction.response.edit_message(embed=await self.embed(), view=self)
    @discord.ui.button(label="Edit", emoji="✏️", style=discord.ButtonStyle.primary, row=1)
    async def edit(self, interaction, button): await self.cog.open_editor(interaction, self.giveaways[self.page])
    @discord.ui.button(label="End", emoji="⏹️", style=discord.ButtonStyle.danger, row=1)
    async def end(self, interaction, button): await self.cog.ask_confirmation(interaction, self.giveaways[self.page], "end")
    @discord.ui.button(label="Reroll", emoji="🔄", style=discord.ButtonStyle.primary, row=1)
    async def reroll(self, interaction, button): await self.cog.ask_confirmation(interaction, self.giveaways[self.page], "reroll")
    @discord.ui.button(label="Cancel", emoji="❌", style=discord.ButtonStyle.danger, row=1)
    async def cancel_giveaway(self, interaction, button): await self.cog.ask_confirmation(interaction, self.giveaways[self.page], "cancel")
    @discord.ui.button(label="Participants", emoji="👥", style=discord.ButtonStyle.secondary, row=1)
    async def participants(self, interaction, button): await self.cog.send_participants(interaction, self.giveaways[self.page], admin=True)


class Giveaway(commands.Cog):
    """Create and manage persistent, requirement-aware giveaways."""

    giveaway = app_commands.Group(name="giveaway", description="Create, enter, and manage giveaways", guild_only=True)

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._ending: set[str] = set()
        # Extensions may register additional async rules. A rule receives a
        # member and configured value, then returns None or a failure reason.
        self.custom_eligibility_rules: dict[str, Callable] = {
            "bloop_level": self._check_bloop_level,
        }

    def register_eligibility_rule(self, name: str, checker: Callable) -> None:
        """Register an async custom requirement checker for other cogs."""
        self.custom_eligibility_rules[name.strip().lower()] = checker

    async def _check_bloop_level(self, member: discord.Member, minimum: int) -> str | None:
        database = getattr(self.bot, "db", None)
        if database is None:
            return "your Bloop level could not be verified"
        user = await database.get_user(member.id)
        if int(user.get("level", 1)) < int(minimum):
            return f"you need Bloop level {minimum}+ (currently {user.get('level', 1)})"
        return None

    @property
    def db(self):
        database = getattr(self.bot, "giveaways_db", None)
        if database is None: raise GiveawayUserError("The giveaway database is not ready.")
        return database

    async def cog_load(self):
        self.bot.add_view(GiveawayPublicView(self))
        self.scheduler.start()

    async def cog_unload(self):
        self.scheduler.cancel()

    @tasks.loop(seconds=cfg.SCHEDULER_INTERVAL_SECONDS)
    async def scheduler(self):
        try:
            for giveaway in await self.db.expired(utc_ts()):
                guild = self.bot.get_guild(giveaway["guild_id"])
                if guild:
                    await self.end_now(guild, giveaway["giveaway_id"], automatic=True)
                else:
                    logger.warning("Cannot end %s: guild %s unavailable", giveaway["giveaway_id"], giveaway["guild_id"])
            # Reconcile message edits that previously failed due to a temporary
            # Discord API/channel error. State remains authoritative in SQLite.
            for giveaway in await self.db.dirty_messages():
                if giveaway["status"] != "ending":
                    await self.update_message(giveaway)
        except Exception:
            logger.exception("Giveaway scheduler cycle failed")

    @scheduler.before_loop
    async def before_scheduler(self): await self.bot.wait_until_ready()

    @staticmethod
    def _admin(member: discord.Member) -> bool:
        return has_admin_permission(member)

    async def _lookup(self, guild_id: int, giveaway_id: str) -> dict:
        giveaway = await self.db.get(giveaway_id.strip().upper(), guild_id)
        if not giveaway: raise GiveawayUserError(f"No giveaway `{giveaway_id}` exists in this server.")
        return giveaway

    async def _message(self, giveaway: dict):
        guild = self.bot.get_guild(giveaway["guild_id"])
        channel = guild.get_channel(giveaway["channel_id"]) if guild else None
        if channel is None: return None
        try: return await channel.fetch_message(giveaway["message_id"]) if giveaway.get("message_id") else None
        except (discord.NotFound, discord.Forbidden, discord.HTTPException): return None

    async def update_message(self, giveaway: dict):
        message = await self._message(giveaway)
        if message is None:
            logger.warning("Giveaway %s message/channel is unavailable", giveaway["giveaway_id"]); return False
        counts = await self.db.counts(giveaway["giveaway_id"])
        try:
            await message.edit(embed=giveaway_embed(giveaway, counts), view=GiveawayPublicView(self, disabled=giveaway["status"] != "active"))
            await self.db.mark_message_synced(giveaway["giveaway_id"])
            return True
        except (discord.Forbidden, discord.HTTPException):
            logger.exception("Could not update giveaway message %s", giveaway["giveaway_id"]); return False

    async def publish(self, interaction: discord.Interaction, draft: dict):
        if not draft.get("prize"): raise GiveawayUserError("Set a prize before publishing.")
        if not draft.get("channel_id"): raise GiveawayUserError("Select a giveaway channel before publishing.")
        if interaction.guild_id != draft["guild_id"] or interaction.user.id != draft["host_id"]: raise GiveawayUserError("This draft does not belong to this server and administrator.")
        channel = interaction.guild.get_channel(draft["channel_id"])
        if channel is None: raise GiveawayUserError("The selected channel was deleted or is inaccessible.")
        perms = channel.permissions_for(interaction.guild.me)
        if not (
            perms.view_channel
            and perms.send_messages
            and perms.embed_links
            and perms.read_message_history
        ):
            raise GiveawayUserError(
                "I need View Channel, Send Messages, Embed Links, and Read Message History in the selected channel."
            )
        giveaway_id = await self.new_id()
        data = dict(draft); data.update(giveaway_id=giveaway_id, start_time=utc_ts(), end_time=utc_ts() + draft["duration"], status="active", winner_ids=[])
        await self.db.create(data)
        try:
            message = await channel.send(embed=giveaway_embed(data, {"users": 0, "entries": 0}), view=GiveawayPublicView(self))
            await self.db.set_message_id(giveaway_id, message.id)
            await self.db.mark_message_synced(giveaway_id)
        except Exception:
            await self.db.cancel(giveaway_id, interaction.guild_id); raise
        await interaction.followup.send(f"✅ Giveaway `{giveaway_id}` published in {channel.mention}. [Jump to it]({message.jump_url})", ephemeral=True)

    async def new_id(self) -> str:
        alphabet = string.ascii_uppercase + string.digits
        for _ in range(20):
            value = "GW-" + "".join(secrets.choice(alphabet) for _ in range(5))
            if await self.db.get(value) is None: return value
        raise GiveawayUserError("Could not generate a unique giveaway ID. Try again.")

    async def save_edit(self, interaction: discord.Interaction, giveaway_id: str, draft: dict):
        old = await self._lookup(interaction.guild_id, giveaway_id)
        if old["status"] != "active": raise GiveawayUserError("Only active giveaways can be edited.")
        if not draft.get("prize") or not draft.get("channel_id"): raise GiveawayUserError("Prize and channel are required.")
        if draft["channel_id"] != old["channel_id"]: raise GiveawayUserError("The channel cannot be changed after publishing; this prevents duplicate messages.")
        changes = {"prize": draft["prize"], "description": draft["description"], "winners_count": draft["winners_count"], "end_time": utc_ts() + draft["duration"], "requirements": draft["requirements"], "bonus_entries": draft["bonus_entries"], "settings": draft["settings"]}
        if not await self.db.update(giveaway_id, interaction.guild_id, changes): raise GiveawayUserError("The giveaway changed while editing. Reopen the dashboard.")
        updated = await self._lookup(interaction.guild_id, giveaway_id); message_ok = await self.update_message(updated)
        await interaction.followup.send(f"✅ `{giveaway_id}` updated." + ("" if message_ok else " The original message is unavailable, but the database changes were saved."), ephemeral=True)

    async def eligibility(self, giveaway: dict, member: discord.Member, invite_counts: dict[int, int] | None = None) -> list[str]:
        failures, req, settings = [], giveaway.get("requirements") or {}, giveaway.get("settings") or {}
        role_ids = {r.id for r in member.roles}
        if member.bot and not settings.get("allow_bots", False): failures.append("bots are not allowed")
        if member.id == giveaway["host_id"] and not settings.get("allow_host", False): failures.append("the giveaway host cannot enter")
        if req.get("required_role_id") and req["required_role_id"] not in role_ids: failures.append(f"you need the <@&{req['required_role_id']}> role")
        allowed = set(req.get("allowed_role_ids") or [])
        if allowed and not role_ids.intersection(allowed): failures.append("you do not have any allowed role")
        blocked = role_ids.intersection(req.get("blacklisted_role_ids") or [])
        if blocked: failures.append("you have a blacklisted role: " + ", ".join(f"<@&{r}>" for r in blocked))
        now = datetime.now(timezone.utc)
        account_days = (now - member.created_at).total_seconds() / 86400
        if account_days < int(req.get("minimum_account_age_days") or 0): failures.append(f"your account must be {req['minimum_account_age_days']}+ days old")
        if req.get("minimum_membership_days") and (
            member.joined_at is None
            or (now - member.joined_at).total_seconds() / 86400
            < int(req["minimum_membership_days"])
        ):
            failures.append(
                f"you must be a server member for {req['minimum_membership_days']}+ days"
            )
        required_channel = member.guild.get_channel(req.get("required_channel_id")) if req.get("required_channel_id") else None
        if req.get("required_channel_id") and (required_channel is None or not required_channel.permissions_for(member).view_channel): failures.append(f"you must be able to view <#{req['required_channel_id']}>")
        if req.get("minimum_invites"):
            if invite_counts is None:
                try: invite_counts = await self.invite_counts(member.guild)
                except (discord.Forbidden, discord.HTTPException): failures.append("invite eligibility could not be verified (the bot needs Manage Server)"); invite_counts = {}
            if invite_counts.get(member.id, 0) < int(req["minimum_invites"]): failures.append(f"you need {req['minimum_invites']}+ invites (currently {invite_counts.get(member.id, 0)})")
        for name, value in (req.get("custom_rules") or {}).items():
            checker = self.custom_eligibility_rules.get(name)
            if checker is None:
                failures.append(f"custom rule `{name}` is unavailable")
                continue
            try:
                failure = await checker(member, value)
                if failure: failures.append(failure)
            except Exception:
                logger.exception("Custom giveaway rule %s failed", name)
                failures.append(f"custom rule `{name}` could not be verified")
        return failures

    @staticmethod
    async def invite_counts(guild: discord.Guild) -> dict[int, int]:
        result = {}
        for invite in await guild.invites():
            if invite.inviter: result[invite.inviter.id] = result.get(invite.inviter.id, 0) + (invite.uses or 0)
        return result

    def bonus_for(self, giveaway: dict, member: discord.Member) -> int:
        role_ids = {str(r.id) for r in member.roles}; return sum(int(v) for k, v in (giveaway.get("bonus_entries") or {}).items() if str(k) in role_ids)

    async def enter_giveaway(self, interaction: discord.Interaction):
        if interaction.guild is None or interaction.message is None:
            await interaction.response.send_message("This button only works inside its server.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)
        giveaway = await self.db.get_by_message(interaction.message.id, interaction.guild_id)
        if giveaway is None: await interaction.followup.send("This giveaway no longer exists in this server.", ephemeral=True); return
        if giveaway["status"] != "active" or giveaway["end_time"] <= utc_ts():
            await interaction.followup.send("This giveaway has already ended.", ephemeral=True); return
        failures = await self.eligibility(giveaway, interaction.user)
        if failures:
            await interaction.followup.send("You cannot enter because:\n• " + "\n• ".join(failures), ephemeral=True); return
        settings = giveaway["settings"]
        result, entry = await self.db.add_entry(giveaway["giveaway_id"], interaction.user.id, self.bonus_for(giveaway, interaction.user), bool(settings.get("allow_multiple_entries")), int(settings.get("max_entries_per_user", 1)))
        if result == "inactive": await interaction.followup.send("This giveaway just ended.", ephemeral=True); return
        if result == "exists": await interaction.followup.send("You are already participating in this giveaway.", ephemeral=True); return
        if result == "maximum": await interaction.followup.send(f"You already reached the maximum of {settings.get('max_entries_per_user', 1)} entries.", ephemeral=True); return
        await interaction.followup.send(f"🎉 You successfully entered! You now have **{entry['base_entries'] + entry['bonus_entries']}** weighted entries.", ephemeral=True)
        fresh = await self._lookup(interaction.guild_id, giveaway["giveaway_id"]); await self.update_message(fresh)

    async def show_public_participants(self, interaction: discord.Interaction):
        if interaction.guild is None or interaction.message is None:
            await interaction.response.send_message("This button only works inside its server.", ephemeral=True); return
        giveaway = await self.db.get_by_message(interaction.message.id, interaction.guild_id)
        if giveaway is None: await interaction.response.send_message("Giveaway not found.", ephemeral=True); return
        await self.send_participants(interaction, giveaway, admin=self._admin(interaction.user))

    async def send_participants(self, interaction, giveaway: dict, admin: bool):
        entries = await self.db.entries(giveaway["giveaway_id"]); view = ParticipantPages(self, giveaway, entries, interaction.user.id, admin)
        await interaction.response.send_message(embed=view.embed(), view=view, ephemeral=True)

    async def eligible_entries(self, guild: discord.Guild, giveaway: dict, *, exclude: set[int] | None = None) -> list[tuple[int, int]]:
        exclude = exclude or set(); result = []
        invite_counts = None
        if (giveaway.get("requirements") or {}).get("minimum_invites"):
            try: invite_counts = await self.invite_counts(guild)
            except (discord.Forbidden, discord.HTTPException):
                logger.warning("Cannot verify invites for giveaway %s", giveaway["giveaway_id"]); invite_counts = {}
        for entry in await self.db.entries(giveaway["giveaway_id"]):
            if entry["user_id"] in exclude: continue
            member = guild.get_member(entry["user_id"])
            if member is None:
                try: member = await guild.fetch_member(entry["user_id"])
                except (discord.NotFound, discord.Forbidden, discord.HTTPException): continue
            if await self.eligibility(giveaway, member, invite_counts): continue
            result.append((member.id, max(1, int(entry["base_entries"]) + int(entry["bonus_entries"]))))
        return result

    @staticmethod
    def choose_winners(weighted: list[tuple[int, int]], count: int, allow_duplicates: bool = False) -> list[int]:
        """Cryptographically random weighted draw, without replacement by default."""
        pool = list(weighted); winners = []
        while pool and len(winners) < count:
            total = sum(weight for _, weight in pool)
            pick = secrets.randbelow(total)
            running, selected = 0, 0
            for index, (_, weight) in enumerate(pool):
                running += weight
                if pick < running: selected = index; break
            winners.append(pool[selected][0])
            if not allow_duplicates: pool.pop(selected)
        return winners

    async def end_now(self, guild: discord.Guild, giveaway_id: str, *, automatic: bool = False) -> list[int]:
        giveaway_id = giveaway_id.upper()
        if giveaway_id in self._ending: raise GiveawayUserError("This giveaway is already being ended.")
        self._ending.add(giveaway_id)
        try:
            giveaway = await self.db.claim_for_end(giveaway_id, guild.id)
            if giveaway is None:
                current = await self._lookup(guild.id, giveaway_id)
                raise GiveawayUserError(f"This giveaway is already {current['status']}.")
            try:
                weighted = await self.eligible_entries(guild, giveaway)
                winners = self.choose_winners(weighted, giveaway["winners_count"], bool(giveaway["settings"].get("allow_duplicate_winners")))
                await self.db.finish_end(giveaway_id, winners)
            except Exception:
                await self.db.restore_active(giveaway_id); raise
            ended = await self._lookup(guild.id, giveaway_id)
            await self.update_message(ended)
            await self.announce(ended, winners, reroll=False)
            logger.info("Giveaway %s ended%s with %d winner(s)", giveaway_id, " automatically" if automatic else "", len(winners))
            return winners
        finally: self._ending.discard(giveaway_id)

    async def reroll_now(self, guild: discord.Guild, giveaway_id: str) -> list[int]:
        giveaway = await self._lookup(guild.id, giveaway_id)
        if giveaway["status"] != "ended": raise GiveawayUserError("Only ended giveaways can be rerolled.")
        history = await self.db.winner_history(giveaway["giveaway_id"])
        excluded = set() if giveaway["settings"].get("allow_previous_winners") else {w["user_id"] for w in history}
        weighted = await self.eligible_entries(guild, giveaway, exclude=excluded)
        winners = self.choose_winners(weighted, giveaway["winners_count"], bool(giveaway["settings"].get("allow_duplicate_winners")))
        await self.db.record_reroll(giveaway["giveaway_id"], winners)
        updated = await self._lookup(guild.id, giveaway_id); await self.update_message(updated); await self.announce(updated, winners, reroll=True)
        return winners

    async def cancel_now(self, guild: discord.Guild, giveaway_id: str):
        giveaway = await self._lookup(guild.id, giveaway_id)
        if giveaway["status"] != "active": raise GiveawayUserError(f"This giveaway is already {giveaway['status']}.")
        if not await self.db.cancel(giveaway["giveaway_id"], guild.id): raise GiveawayUserError("The giveaway changed before it could be cancelled.")
        updated = await self._lookup(guild.id, giveaway_id); await self.update_message(updated)

    async def announce(self, giveaway: dict, winners: list[int], *, reroll: bool):
        settings = giveaway["settings"]
        if not settings.get("announce_winners", True): return
        guild = self.bot.get_guild(giveaway["guild_id"]); channel = guild.get_channel(giveaway["channel_id"]) if guild else None
        if channel is None:
            logger.warning("Cannot announce winners for %s: channel deleted", giveaway["giveaway_id"]); return
        mentions = " ".join(f"<@{uid}>" for uid in winners)
        title = "🔄 Giveaway Rerolled!" if reroll else "🎉 Giveaway Ended!"
        embed = discord.Embed(title=title, color=int(settings.get("color", cfg.DEFAULT_COLOR)))
        embed.description = f"🎁 **Prize:** {giveaway['prize']}\n\n🏆 **Winners:**\n" + ("\n".join(f"<@{uid}>" for uid in winners) if winners else "No eligible participants")
        embed.set_footer(text=f"Giveaway ID: {giveaway['giveaway_id']}")
        content = ((settings.get("announcement_message") or "Congratulations! 🎉") + (f" {mentions}" if mentions and settings.get("ping_winners", True) else "")) if winners else "There were not enough eligible participants to select a winner."
        try:
            await channel.send(content=content, embed=embed, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
        except (discord.Forbidden, discord.HTTPException): logger.exception("Could not announce giveaway %s", giveaway["giveaway_id"])

    async def ask_confirmation(self, interaction: discord.Interaction, giveaway: dict, action: str):
        prompts = {"end": "end this giveaway and select winners", "cancel": "cancel this giveaway without winners", "reroll": "reroll and announce new winners"}
        async def perform(done_interaction):
            if action == "end": winners = await self.end_now(done_interaction.guild, giveaway["giveaway_id"]); message = f"✅ Giveaway ended with {len(winners)} winner(s)."
            elif action == "cancel": await self.cancel_now(done_interaction.guild, giveaway["giveaway_id"]); message = "✅ Giveaway cancelled."
            else: winners = await self.reroll_now(done_interaction.guild, giveaway["giveaway_id"]); message = f"✅ Giveaway rerolled with {len(winners)} new winner(s)."
            await done_interaction.followup.send(message, ephemeral=True)
        prompt = prompts[action]
        await interaction.response.send_message(f"Are you sure you want to **{prompt}**?\n`{giveaway['giveaway_id']}` — **{giveaway['prize']}**", view=ConfirmView(interaction.user.id, prompt, perform), ephemeral=True)

    async def open_editor(self, interaction: discord.Interaction, giveaway: dict):
        if giveaway["status"] != "active":
            await interaction.response.send_message("Only active giveaways can be edited.", ephemeral=True); return
        draft = default_draft(interaction.guild, giveaway["host_id"])
        draft.update(prize=giveaway["prize"], description=giveaway["description"], winners_count=giveaway["winners_count"], duration=max(10, giveaway["end_time"] - utc_ts()), channel_id=giveaway["channel_id"], requirements=giveaway["requirements"], bonus_entries=giveaway["bonus_entries"], settings=giveaway["settings"])
        view = CreationView(self, interaction.guild, interaction.user.id, draft, giveaway["giveaway_id"])
        await interaction.response.send_message(embed=creation_embed(draft, editing=True), view=view, ephemeral=True)

    async def send_statistics(self, interaction: discord.Interaction):
        stats = await self.db.statistics(interaction.guild_id)
        total, participants = int(stats.get("total") or 0), int(stats.get("participants") or 0)
        embed = discord.Embed(title="📊 Giveaway Statistics", color=cfg.DEFAULT_COLOR)
        embed.add_field(name="Giveaways", value=f"Total: **{total}**\nActive: **{int(stats.get('active') or 0)}**\nCompleted: **{int(stats.get('completed') or 0)}**\nCancelled: **{int(stats.get('cancelled') or 0)}**")
        embed.add_field(name="Participation", value=f"Total participants: **{participants}**\nTotal winners: **{int(stats.get('winners') or 0)}**\nAverage: **{participants / total:.1f}** per giveaway")
        popular = stats.get("popular_prizes") or []
        embed.add_field(name="Popular prizes", value="\n".join(f"{x['prize']} — {x['uses']} giveaway(s)" for x in popular) or "No data", inline=False)
        success = stats.get("most_successful")
        embed.add_field(name="Most successful", value=(f"`{success['giveaway_id']}` — **{success['prize']}** ({success['participants']} participants)" if success else "No data"), inline=False)
        timeline = stats.get("timeline") or []
        embed.add_field(name="Participation over time (last 14 active days)", value="\n".join(f"`{x['day']}` {'▰' * min(20, max(1, x['participants']))} {x['participants']}" for x in timeline) or "No data", inline=False)
        if interaction.response.is_done(): await interaction.followup.send(embed=embed, ephemeral=True)
        else: await interaction.response.send_message(embed=embed, ephemeral=True)

    def info_embed(self, giveaway: dict, counts: dict, history: list[dict]) -> discord.Embed:
        embed = giveaway_embed(giveaway, counts)
        embed.title = f"ℹ️ Giveaway {giveaway['giveaway_id']}"
        embed.add_field(name="Dates", value=f"Created: <t:{giveaway['created_at']}:F>\nStarted: <t:{giveaway['start_time']}:F>\nEnds/ended: <t:{giveaway.get('ended_at') or giveaway['end_time']}:F>", inline=False)
        if history:
            rounds = {}
            for winner in history: rounds.setdefault(winner["round"], []).append(winner["user_id"])
            embed.add_field(name="Winner history", value="\n".join(f"Round {r + 1}: " + (", ".join(f"<@{u}>" for u in users) or "None") for r, users in rounds.items())[:1024], inline=False)
        return embed

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        original = getattr(error, "original", error)
        if isinstance(error, app_commands.MissingPermissions):
            message = "❌ You need the configured giveaway administrator permission to do that."
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
            return
        if isinstance(original, GiveawayUserError):
            message = f"❌ {original}"
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
            return
        logger.error("Giveaway command failed: %s", error, exc_info=(type(error), error, error.__traceback__))
        message = "❌ The giveaway operation failed. Please try again; no duplicate action was performed."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    @giveaway.command(name="create", description="Open the interactive giveaway creator")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def create_command(self, interaction: discord.Interaction):
        draft = default_draft(interaction.guild, interaction.user.id); draft["channel_id"] = interaction.channel_id
        view = CreationView(self, interaction.guild, interaction.user.id, draft)
        await interaction.response.send_message(embed=creation_embed(draft), view=view, ephemeral=True)

    @giveaway.command(name="list", description="List active giveaways in this server")
    async def list_command(self, interaction: discord.Interaction):
        giveaways = await self.db.list_guild(interaction.guild_id, "active")
        rows = [(item, await self.db.counts(item["giveaway_id"])) for item in giveaways]
        view = ActiveListView(interaction.user.id, rows)
        await interaction.response.send_message(embed=view.embed(), view=view)

    @giveaway.command(name="manage", description="Open the administrator giveaway dashboard")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def manage_command(self, interaction: discord.Interaction):
        giveaways = await self.db.list_guild(interaction.guild_id, "active")
        view = DashboardView(self, interaction.guild, interaction.user.id, giveaways)
        await interaction.response.send_message(embed=await view.embed(), view=view, ephemeral=True)

    @giveaway.command(name="end", description="Immediately end a giveaway and select winners")
    @app_commands.describe(giveaway_id="Short ID, for example GW-8F42K")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def end_command(self, interaction: discord.Interaction, giveaway_id: str):
        giveaway = await self._lookup(interaction.guild_id, giveaway_id); await self.ask_confirmation(interaction, giveaway, "end")

    @giveaway.command(name="reroll", description="Select new winners for an ended giveaway")
    @app_commands.describe(giveaway_id="Short ID, for example GW-8F42K")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def reroll_command(self, interaction: discord.Interaction, giveaway_id: str):
        giveaway = await self._lookup(interaction.guild_id, giveaway_id); await self.ask_confirmation(interaction, giveaway, "reroll")

    @giveaway.command(name="cancel", description="Cancel a giveaway without selecting winners")
    @app_commands.describe(giveaway_id="Short ID, for example GW-8F42K")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cancel_command(self, interaction: discord.Interaction, giveaway_id: str):
        giveaway = await self._lookup(interaction.guild_id, giveaway_id); await self.ask_confirmation(interaction, giveaway, "cancel")

    @giveaway.command(name="info", description="Show detailed giveaway information")
    @app_commands.describe(giveaway_id="Short ID, for example GW-8F42K")
    async def info_command(self, interaction: discord.Interaction, giveaway_id: str):
        giveaway = await self._lookup(interaction.guild_id, giveaway_id)
        counts, history = await self.db.counts(giveaway["giveaway_id"]), await self.db.winner_history(giveaway["giveaway_id"])
        await interaction.response.send_message(embed=self.info_embed(giveaway, counts, history), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Giveaway(bot))
