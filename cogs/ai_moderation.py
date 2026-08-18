"""AI Moderation cog with interactive configuration form."""

import asyncio
import json
import logging
import math
from collections import defaultdict
from datetime import timedelta
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Select, Button, Modal, TextInput

from ai_moderation.policy import (
    OFFENSE_WINDOW_DAYS,
    describe_escalation,
    determine_enforcement,
)
from ai_moderation.service import AIModerationService, AIModel, MODERATION_LEVELS

logger = logging.getLogger(__name__)

# In-memory config storage (in production, use database)
# guild_id -> config dict
GUILD_AI_CONFIG = {}


class PlatformSelect(Select):
    """Dropdown for selecting AI platform."""

    PLATFORMS = [
        "OpenRouter", "Gemini",
        "OpenAI", "Anthropic", "DeepSeek", "xAI"
    ]

    def __init__(self, current: Optional[str] = None):
        options = [
            discord.SelectOption(
                label=p,
                value=p,
                default=(p == current)
            ) for p in self.PLATFORMS
        ]
        super().__init__(
            placeholder="Select AI platform...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="aimod_platform"
        )

    async def callback(self, interaction: discord.Interaction):
        self.view.platform = self.values[0]
        # Fetch models for this platform
        await self.view.fetch_models(interaction)


class ModelSelect(Select):
    """Dropdown for selecting AI model (populated dynamically)."""

    def __init__(self, models: list, current: Optional[str] = None):
        options = []
        for model in models[:25]:  # Discord limit
            options.append(discord.SelectOption(
                label=model.name[:100],
                value=model.id[:100],
                default=(model.id == current)
            ))
        if not options:
            options.append(discord.SelectOption(
                label="No models available",
                value="none",
                default=True
            ))

        super().__init__(
            placeholder="Select AI model...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="aimod_model",
            disabled=len(options) == 1 and options[0].value == "none"
        )

    async def callback(self, interaction: discord.Interaction):
        self.view.model_id = self.values[0]
        await interaction.response.defer()


class ModerationLevelSelect(Select):
    """Dropdown for selecting moderation level."""

    def __init__(self, current: Optional[str] = None):
        options = [
            discord.SelectOption(
                label=level.capitalize(),
                value=level,
                description=cfg["description"][:100],
                default=(level == current)
            ) for level, cfg in MODERATION_LEVELS.items()
        ]
        super().__init__(
            placeholder="Select moderation strictness...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="aimod_level"
        )

    async def callback(self, interaction: discord.Interaction):
        self.view.moderation_level = self.values[0]
        await interaction.response.defer()


class EnabledSelect(Select):
    """Dropdown for enabling/disabling moderation."""

    def __init__(self, current: bool = False):
        options = [
            discord.SelectOption(
                label="Enabled",
                value="true",
                description="AI will scan and moderate messages",
                default=current
            ),
            discord.SelectOption(
                label="Disabled",
                value="false",
                description="AI moderation is off",
                default=not current
            ),
        ]
        super().__init__(
            placeholder="Enable AI moderation?",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="aimod_enabled"
        )

    async def callback(self, interaction: discord.Interaction):
        self.view.enabled = (self.values[0] == "true")
        await interaction.response.defer()


class APIKeyModal(Modal, title="Enter API Key"):
    """Modal for entering the API key securely."""

    api_key = TextInput(
        label="API Key",
        placeholder="sk-... or your provider's API key",
        style=discord.TextStyle.short,
        required=True,
        max_length=200,
    )

    def __init__(self, view: "AIModConfigView"):
        super().__init__()
        self.config_view = view

    async def on_submit(self, interaction: discord.Interaction):
        self.config_view.api_key = self.api_key.value
        # Fetch models after API key is provided
        if self.config_view.platform:
            await self.config_view.fetch_models(interaction)
        else:
            await interaction.response.send_message(
                "✅ API key saved. Now select a platform to fetch models.",
                ephemeral=True
            )


class AIModConfigView(View):
    """Interactive configuration view for AI moderation."""

    def __init__(self, bot: commands.Bot, guild_id: int, user_id: int, existing_config: Optional[dict] = None):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.user_id = user_id
        self.service = AIModerationService()

        # Config state
        self.platform = existing_config.get("platform") if existing_config else None
        self.model_id = existing_config.get("model_id") if existing_config else None
        self.moderation_level = existing_config.get("moderation_level", "moderate") if existing_config else "moderate"
        self.enabled = existing_config.get("enabled", False) if existing_config else False
        self.api_key = existing_config.get("api_key") if existing_config else None
        self._models = []

        self._build_components()

    def _build_components(self):
        """Build/rebuild the form components based on current state."""
        self.clear_items()

        # Platform select
        self.add_item(PlatformSelect(current=self.platform))

        # Model select (only if platform selected)
        if self.platform and self._models:
            self.add_item(ModelSelect(self._models, current=self.model_id))
        elif self.platform:
            # Show placeholder while loading, or preserve saved model selection
            if self.model_id:
                self.add_item(ModelSelect(
                    [AIModel(id=self.model_id, name=self.model_id, provider=self.platform)],
                    current=self.model_id
                ))
            else:
                self.add_item(ModelSelect([], current=None))

        # Moderation level
        self.add_item(ModerationLevelSelect(current=self.moderation_level))

        # Enabled toggle
        self.add_item(EnabledSelect(current=self.enabled))

        # API Key button
        api_btn = Button(
            label="🔑 Set API Key",
            style=discord.ButtonStyle.secondary,
            custom_id="aimod_apikey"
        )
        api_btn.callback = self._api_key_callback
        self.add_item(api_btn)

        # Save button
        save_btn = Button(
            label="💾 Save",
            style=discord.ButtonStyle.success,
            custom_id="aimod_save"
        )
        save_btn.callback = self._save_callback
        self.add_item(save_btn)

        # Cancel button
        cancel_btn = Button(
            label="❌ Cancel",
            style=discord.ButtonStyle.danger,
            custom_id="aimod_cancel"
        )
        cancel_btn.callback = self._cancel_callback
        self.add_item(cancel_btn)

    async def _api_key_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the command author can configure this.", ephemeral=True)
            return
        await interaction.response.send_modal(APIKeyModal(self))

    async def fetch_models(self, interaction: discord.Interaction):
        """Fetch models for the selected platform."""
        if not self.api_key:
            await interaction.response.send_message(
                "❌ Please set an API key first.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            self._models = await self.service.fetch_models(self.platform, self.api_key)
            self._build_components()
            # Update the message that carries this view
            try:
                await interaction.message.edit(embed=self._build_embed(), view=self)
            except (AttributeError, discord.NotFound, discord.HTTPException):
                await interaction.edit_original_response(embed=self._build_embed(), view=self)
        except ValueError as e:
            await interaction.followup.send(f"❌ Failed to fetch models: {e}", ephemeral=True)
        except Exception as e:
            logger.error(f"Error fetching models: {e}")
            await interaction.followup.send("❌ An error occurred while fetching models.", ephemeral=True)

    async def _save_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the command author can save this config.", ephemeral=True)
            return

        # Validate required fields
        if not self.platform:
            await interaction.response.send_message("❌ Please select a platform.", ephemeral=True)
            return
        if not self.api_key:
            await interaction.response.send_message("❌ Please set an API key.", ephemeral=True)
            return
        if self.platform and not self.model_id:
            await interaction.response.send_message("❌ Please select a model.", ephemeral=True)
            return

        # Save config
        config = {
            "platform": self.platform,
            "model_id": self.model_id,
            "moderation_level": self.moderation_level,
            "enabled": self.enabled,
            "api_key": self.api_key,
        }
        GUILD_AI_CONFIG[self.guild_id] = config

        # Save to database (async, don't wait)
        asyncio.create_task(self._save_to_db(config))

        embed = self._build_embed()
        embed.title = "✅ AI Moderation Configured"
        embed.color = 0x22C55E

        # Disable all components
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)

    async def _cancel_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the command author can cancel.", ephemeral=True)
            return

        embed = discord.Embed(
            title="❌ Configuration Cancelled",
            description="No changes were saved.",
            color=0xE11D48
        )
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)

    async def _save_to_db(self, config: dict):
        """Persist config to database."""
        try:
            db = self.bot.db
            if db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS ai_moderation (
                        guild_id INTEGER PRIMARY KEY,
                        config TEXT NOT NULL
                    )
                """)
                await db.execute(
                    "INSERT OR REPLACE INTO ai_moderation (guild_id, config) VALUES (?, ?)",
                    (self.guild_id, json.dumps(config))
                )
        except Exception as e:
            logger.error(f"Failed to save AI moderation config: {e}")

    async def on_timeout(self):
        await self.service.close()
        try:
            for child in self.children:
                child.disabled = True
            if hasattr(self, 'message') and self.message:
                await self.message.edit(embed=self._build_embed(), view=self)
        except Exception:
            pass

    def _build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🤖 AI Moderation Configuration",
            description="Configure automated message moderation using AI.\nOnly the server owner can use this form.",
            color=0x6366F1
        )

        embed.add_field(
            name="Platform",
            value=self.platform or "❌ Not selected",
            inline=True
        )
        embed.add_field(
            name="Model",
            value=self.model_id or ("❌ Not selected" if self.platform else "Select platform first"),
            inline=True
        )
        embed.add_field(
            name="Strictness",
            value=self.moderation_level.capitalize(),
            inline=True
        )
        embed.add_field(
            name="Status",
            value="🟢 Enabled" if self.enabled else "🔴 Disabled",
            inline=True
        )
        embed.add_field(
            name="API Key",
            value="✅ Set" if self.api_key else "❌ Not set",
            inline=True
        )

        if self.platform:
            level_cfg = MODERATION_LEVELS.get(self.moderation_level, {})
            embed.add_field(
                name="Level Description",
                value=level_cfg.get("description", ""),
                inline=False
            )

        embed.add_field(
            name="Automatic Actions",
            value=(
                describe_escalation(self.moderation_level)
                + f"\nStrikes reset after {OFFENSE_WINDOW_DAYS} violation-free days."
            ),
            inline=False,
        )

        embed.set_footer(text="Select options above, then click Save")
        return embed


class AIModeration(commands.Cog):
    """AI-powered message moderation."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.service = AIModerationService()
        # AI requests for separate messages finish out of order. Serializing the
        # strike update and punishment per member keeps escalation deterministic.
        self._member_locks: dict[tuple[int, int], asyncio.Lock] = defaultdict(asyncio.Lock)

    @commands.command(name="aimod", help="Configure AI moderation (server owner only)")
    async def aimod_prefix(self, ctx: commands.Context):
        if ctx.guild and ctx.author.id != ctx.guild.owner_id:
            await ctx.send("❌ Only the server owner can configure AI moderation.")
            return
        await self._show_config(ctx)

    @app_commands.command(name="aimod", description="Configure AI moderation (server owner only)")
    @app_commands.default_permissions(administrator=True)
    async def aimod_slash(self, interaction: discord.Interaction):
        # Check if user is server owner
        if interaction.guild and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message(
                "❌ Only the server owner can configure AI moderation.",
                ephemeral=True
            )
            return
        await self._show_config(interaction)

    @commands.command(
        name="aimodreset",
        help="Clear a member's AI moderation strikes (server owner only)",
        usage="b.aimodreset <@user>",
    )
    @commands.guild_only()
    async def aimodreset_prefix(self, ctx: commands.Context, member: discord.Member):
        if ctx.author.id != ctx.guild.owner_id:
            await ctx.send("❌ Only the server owner can clear AI moderation strikes.")
            return
        await self.bot.db.reset_ai_moderation_offenses(ctx.guild.id, member.id)
        await ctx.send(f"✅ Cleared AI moderation strikes for {member.mention}.")

    @app_commands.command(
        name="aimodreset",
        description="Clear a member's AI moderation strikes (server owner only)",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    @app_commands.describe(member="Member whose AI moderation strikes should be cleared")
    async def aimodreset_slash(
        self, interaction: discord.Interaction, member: discord.Member
    ):
        if interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message(
                "❌ Only the server owner can clear AI moderation strikes.",
                ephemeral=True,
            )
            return
        await self.bot.db.reset_ai_moderation_offenses(interaction.guild.id, member.id)
        await interaction.response.send_message(
            f"✅ Cleared AI moderation strikes for {member.mention}.",
            ephemeral=True,
        )

    async def _show_config(self, ctx):
        """Show the AI moderation configuration form."""
        guild_id = ctx.guild.id if ctx.guild else 0
        user_id = ctx.author.id if hasattr(ctx, 'author') else ctx.user.id

        # Load existing config from database
        existing_config = await self._load_config(guild_id)

        view = AIModConfigView(self.bot, guild_id, user_id, existing_config)
        embed = view._build_embed()

        if hasattr(ctx, 'response'):
            msg = await ctx.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            msg = await ctx.send(embed=embed, view=view)
        view.message = msg
        return msg

    async def _load_config(self, guild_id: int) -> Optional[dict]:
        """Load config from database."""
        try:
            db = self.bot.db
            if db:
                row = await db.fetchone(
                    "SELECT config FROM ai_moderation WHERE guild_id = ?",
                    (guild_id,)
                )
                if row and row["config"]:
                    config = json.loads(row["config"])
                    GUILD_AI_CONFIG[guild_id] = config
                    return config
        except Exception as e:
            logger.error(f"Failed to load AI moderation config: {e}")
        return GUILD_AI_CONFIG.get(guild_id)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Scan messages for moderation violations."""
        # Ignore bots, DMs
        if message.author.bot or not message.guild:
            return

        # Skip server owner (can't moderate owner)
        if message.author.id == message.guild.owner_id:
            return

        # Skip moderators/admins with moderation permissions
        if isinstance(message.author, discord.Member):
            perms = message.author.guild_permissions
            if perms.administrator or perms.manage_messages or perms.moderate_members:
                return

        # Check if AI moderation is enabled for this guild
        config = GUILD_AI_CONFIG.get(message.guild.id)
        if not config:
            config = await self._load_config(message.guild.id)
        if not config or not config.get("enabled"):
            return

        if not message.content.strip():
            return

        try:
            # The AI classifies the violation; a deterministic strike policy
            # below chooses the minimum punishment for repeat behavior.
            moderation_level = config.get("moderation_level", "moderate")
            result = await self.service.moderate_message(
                provider=config["platform"],
                model_id=config["model_id"],
                api_key=config["api_key"],
                message_content=message.content,
                moderation_level=moderation_level,
                guild_context=f"Server: {message.guild.name}, Channel: #{message.channel.name}"
            )

            suggested_action = result.get("action", "none")
            reason = str(result.get("reason") or "AI-detected violation")[:400]
            try:
                confidence = float(result.get("confidence", 0))
                if not math.isfinite(confidence):
                    confidence = 0.0
                confidence = max(0.0, min(confidence, 1.0))
            except (TypeError, ValueError):
                confidence = 0.0

            if suggested_action == "none":
                return

            # Respect each level/category threshold rather than the previous
            # hard-coded 0.5 check, which accidentally disabled strict-mode
            # actions with valid confidence scores between 0.3 and 0.5.
            level_config = MODERATION_LEVELS.get(
                moderation_level, MODERATION_LEVELS["moderate"]
            )
            thresholds = level_config["thresholds"]
            categories = result.get("categories") or []
            required_confidence = min(
                (thresholds[c] for c in categories if c in thresholds),
                default=min(thresholds.values()),
            )
            if confidence < required_confidence:
                return

            lock_key = (message.guild.id, message.author.id)
            async with self._member_locks[lock_key]:
                strike_count = await self.bot.db.record_ai_moderation_offense(
                    message.guild.id, message.author.id
                )
                enforcement = determine_enforcement(
                    moderation_level, strike_count, suggested_action
                )
                await self._apply_action(
                    message=message,
                    action=enforcement.action,
                    reason=reason,
                    confidence=confidence,
                    strike_count=strike_count,
                    timeout_seconds=enforcement.timeout_seconds,
                )

        except Exception:
            logger.exception("AI moderation failed for message %s", message.id)

    async def _apply_action(
        self,
        message: discord.Message,
        action: str,
        reason: str,
        confidence: float,
        strike_count: int,
        timeout_seconds: int | None = None,
    ) -> bool:
        """Apply an enforcement action and report permission failures visibly."""
        member = message.author
        guild = message.guild
        if action not in {"warn", "timeout", "kick", "ban"}:
            logger.error("Refusing unknown AI moderation action: %r", action)
            return False

        display_reason = discord.utils.escape_mentions(reason)
        details = (
            f"Reason: {display_reason} (Confidence: {confidence:.0%}, "
            f"active strike: {strike_count})"
        )

        if action == "warn":
            try:
                await message.reply(
                    "⚠️ **AI moderation warning**\n"
                    f"{details}\nRepeated violations automatically escalate to a "
                    "timeout, kick, and ban.",
                    mention_author=True,
                    allowed_mentions=discord.AllowedMentions(
                        everyone=False,
                        roles=False,
                        users=[member],
                        replied_user=True,
                    ),
                )
                return True
            except discord.HTTPException as exc:
                logger.warning("Could not warn %s in %s: %s", member, guild, exc)
                return False

        me = guild.me
        permission_by_action = {
            "timeout": "moderate_members",
            "kick": "kick_members",
            "ban": "ban_members",
        }
        permission = permission_by_action.get(action)
        if not me or not permission:
            await self._report_action_failure(message, action, "the bot member was unavailable")
            return False
        if not getattr(me.guild_permissions, permission, False):
            readable_permission = permission.replace("_", " ").title()
            await self._report_action_failure(
                message, action, f"I need the **{readable_permission}** permission"
            )
            return False
        if member.top_role >= me.top_role:
            await self._report_action_failure(
                message,
                action,
                "the member's highest role is equal to or above my highest role",
            )
            return False

        audit_reason = f"AI moderation strike {strike_count}: {reason}"[:512]
        try:
            if action == "timeout":
                timeout_seconds = timeout_seconds or 10 * 60
                await member.timeout(
                    timedelta(seconds=timeout_seconds), reason=audit_reason
                )
                duration = self._format_timeout(timeout_seconds)
                notice = f"🔇 {member.mention} was timed out for {duration}.\n{details}"
            elif action == "kick":
                await member.kick(reason=audit_reason)
                notice = f"👢 {member.mention} was kicked.\n{details}"
            else:  # ban
                await member.ban(reason=audit_reason)
                notice = f"🔨 {member.mention} was banned.\n{details}"
        except discord.Forbidden:
            await self._report_action_failure(
                message,
                action,
                "Discord denied the action; check my permissions and role position",
            )
            return False
        except discord.HTTPException as exc:
            logger.warning("Discord rejected AI moderation action %s: %s", action, exc)
            await self._report_action_failure(
                message, action, "Discord rejected the action"
            )
            return False

        # The punishment has already succeeded, so a missing Send Messages
        # permission must not make it look like enforcement itself failed.
        try:
            await message.channel.send(
                notice,
                allowed_mentions=discord.AllowedMentions(
                    everyone=False, roles=False, users=[member]
                ),
            )
        except discord.HTTPException as exc:
            logger.warning(
                "Applied %s to %s in %s but could not announce it: %s",
                action,
                member,
                guild,
                exc,
            )
        return True

    async def _report_action_failure(
        self, message: discord.Message, action: str, explanation: str
    ) -> None:
        """Log and, when possible, tell moderators why enforcement failed."""
        logger.warning(
            "Could not apply AI moderation action %s to %s in %s: %s",
            action,
            message.author,
            message.guild,
            explanation,
        )
        try:
            await message.channel.send(
                f"⚠️ {message.author.mention} reached an AI moderation **{action}**, "
                f"but I could not apply it because {explanation}.",
                allowed_mentions=discord.AllowedMentions(
                    everyone=False, roles=False, users=[message.author]
                ),
            )
        except discord.HTTPException:
            pass

    @staticmethod
    def _format_timeout(seconds: int) -> str:
        if seconds % 3600 == 0:
            hours = seconds // 3600
            return f"{hours} hour{'s' if hours != 1 else ''}"
        minutes = max(1, seconds // 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''}"

    async def cog_unload(self):
        await self.service.close()


async def setup(bot: commands.Bot):
    await bot.add_cog(AIModeration(bot))