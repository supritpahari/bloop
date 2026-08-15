"""AI Chat cog with interactive configuration form."""

import asyncio
import json
import logging
from typing import Optional, List

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Select, Button, Modal, TextInput, ChannelSelect

from ai_moderation.chat_service import AIChatService, AIModel

logger = logging.getLogger(__name__)

# In-memory config cache: guild_id -> config dict (or None when we know there is none)
GUILD_AI_CHAT_CONFIG = {}

# Discord hard limit for a single message
MAX_MESSAGE_LEN = 2000


def _chunk(text: str, size: int = MAX_MESSAGE_LEN) -> List[str]:
    """Split a reply into Discord-sized chunks, preferring line/space boundaries."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    chunks = []
    while text:
        if len(text) <= size:
            chunks.append(text)
            break
        window = text[:size]
        cut = window.rfind("\n")
        if cut < size // 2:
            cut = window.rfind(" ")
        if cut < size // 2:
            cut = size
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    return chunks


class ProviderSelect(Select):
    """Dropdown for selecting AI platform."""

    PROVIDERS = [
        "OpenRouter", "Gemini",
        "OpenAI", "Anthropic", "DeepSeek", "xAI"
    ]

    def __init__(self, current: Optional[str] = None):
        options = [
            discord.SelectOption(
                label=p,
                value=p,
                default=(p == current)
            ) for p in self.PROVIDERS
        ]
        super().__init__(
            placeholder="1️⃣ Select AI provider...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="aichat_provider"
        )

    async def callback(self, interaction: discord.Interaction):
        if not await self.view.ensure_author(interaction):
            return
        new_provider = self.values[0]
        if new_provider != self.view.provider:
            # Models are provider specific - drop anything selected for the old one.
            self.view.provider = new_provider
            self.view.model_id = None
            self.view._models = []
            self.view._model_error = None
        await self.view.refresh(interaction, fetch_models=True)


class ModelSelect(Select):
    """Dropdown for selecting AI model."""

    def __init__(self, models: List[AIModel], current: Optional[str] = None, note: Optional[str] = None):
        options = []
        seen = set()
        for model in models:
            value = model.id[:100]
            if value in seen:
                continue
            seen.add(value)
            options.append(discord.SelectOption(
                label=(model.name or model.id)[:100],
                value=value,
                default=(model.id == current)
            ))
            if len(options) >= 25:
                break

        # Keep a manually typed model visible/selected even if it isn't in the list.
        if current and current[:100] not in seen:
            options.insert(0, discord.SelectOption(
                label=f"{current[:90]} (manual)",
                value=current[:100],
                default=True,
            ))
            options = options[:25]

        placeholder = note or "2️⃣ Select AI model..."
        empty = not options
        if empty:
            options = [discord.SelectOption(label="No models loaded", value="__none__", default=True)]

        super().__init__(
            placeholder=placeholder[:150],
            min_values=1,
            max_values=1,
            options=options,
            custom_id="aichat_model",
            disabled=empty,
        )

    async def callback(self, interaction: discord.Interaction):
        if not await self.view.ensure_author(interaction):
            return
        if self.values[0] == "__none__":
            await interaction.response.defer()
            return
        self.view.model_id = self.values[0]
        await self.view.refresh(interaction)


class ToneSelect(Select):
    """Dropdown for selecting chat tone."""

    TONES = {
        "casual": "Casual - Like a friend, relaxed & natural",
        "friendly": "Friendly - Warm, supportive, uses emojis",
        "witty": "Witty - Clever, playful, humorous",
        "professional": "Professional - Clear, concise, helpful",
        "roleplay": "Roleplay - Immersive, *actions* & \"dialogue\"",
        "custom": "Custom - Write your own personality"
    }

    def __init__(self, current: Optional[str] = None):
        options = [
            discord.SelectOption(
                label=label.split(" - ")[0],
                value=key,
                description=label[:100],
                default=(key == current)
            ) for key, label in self.TONES.items()
        ]
        super().__init__(
            placeholder="4️⃣ Select chat tone/personality...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="aichat_tone"
        )

    async def callback(self, interaction: discord.Interaction):
        if not await self.view.ensure_author(interaction):
            return
        choice = self.values[0]
        if choice == "custom":
            # Opening a modal IS the response to this interaction.
            await interaction.response.send_modal(CustomToneModal(self.view))
            return
        self.view.tone = choice
        self.view.custom_tone = None
        await self.view.refresh(interaction)


class CustomToneModal(Modal, title="Custom AI Personality"):
    """Modal for entering custom tone."""

    tone_input = TextInput(
        label="Describe the AI's personality",
        placeholder="e.g. You are a sarcastic cat who gives advice in riddles...",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1500,
    )

    def __init__(self, view: "AIChatConfigView"):
        super().__init__()
        self.config_view = view
        if view.custom_tone:
            self.tone_input.default = view.custom_tone[:1500]

    async def on_submit(self, interaction: discord.Interaction):
        self.config_view.tone = "custom"
        self.config_view.custom_tone = self.tone_input.value.strip()
        await self.config_view.refresh(interaction)


class ManualModelModal(Modal, title="Enter Model ID"):
    """Fallback for providers with more than 25 models (e.g. OpenRouter)."""

    model_input = TextInput(
        label="Model ID",
        placeholder="e.g. openai/gpt-4o-mini, gemini-1.5-flash, deepseek-chat",
        style=discord.TextStyle.short,
        required=True,
        max_length=100,
    )

    def __init__(self, view: "AIChatConfigView"):
        super().__init__()
        self.config_view = view
        if view.model_id:
            self.model_input.default = view.model_id[:100]

    async def on_submit(self, interaction: discord.Interaction):
        self.config_view.model_id = self.model_input.value.strip()
        await self.config_view.refresh(interaction)


class APIKeyModal(Modal, title="Enter API Key"):
    """Modal for entering the API key."""

    api_key = TextInput(
        label="API Key",
        placeholder="sk-... or your provider's API key",
        style=discord.TextStyle.short,
        required=True,
        max_length=1024,
    )

    def __init__(self, view: "AIChatConfigView"):
        super().__init__()
        self.config_view = view

    async def on_submit(self, interaction: discord.Interaction):
        # Strip whitespace/newlines - copy-pasted keys very often carry a trailing space.
        self.config_view.api_key = self.api_key.value.strip()
        await self.config_view.refresh(interaction, fetch_models=True)


class AIChatConfigView(View):
    """Interactive configuration view for AI chat."""

    def __init__(
        self,
        bot: commands.Bot,
        guild_id: int,
        user_id: int,
        existing_config: Optional[dict] = None,
        service: Optional[AIChatService] = None,
    ):
        super().__init__(timeout=600)
        self.bot = bot
        self.guild_id = guild_id
        self.user_id = user_id
        # Share the cog's service so we don't leak a second aiohttp session.
        self.service = service or AIChatService()

        cfg = existing_config or {}
        self.provider = cfg.get("provider")
        self.model_id = cfg.get("model_id")
        self.channel_id = _as_int(cfg.get("channel_id"))
        self.tone = cfg.get("tone") or "casual"
        self.custom_tone = cfg.get("custom_tone")
        # Default new setups to enabled so saving a fresh config actually turns it on.
        self.enabled = cfg.get("enabled", True)
        self.api_key = cfg.get("api_key")

        self._models: List[AIModel] = []
        self._model_error: Optional[str] = None
        self._status: Optional[str] = None

        self._build_components()

    # ------------------------------------------------------------ components

    def _build_components(self):
        self.clear_items()

        # Row 0: provider
        self.add_item(ProviderSelect(current=self.provider))

        # Row 1: model
        if self.provider:
            note = None
            if self._model_error:
                note = "⚠️ Could not load models - use 'Enter model ID'"
            elif not self._models and not self.api_key:
                note = "Set the API key to load models"
            self.add_item(ModelSelect(self._models, current=self.model_id, note=note))

        # Row 2: channel
        default_channel = []
        if self.channel_id:
            default_channel = [discord.Object(id=self.channel_id, type=discord.abc.GuildChannel)]
        channel_select = ChannelSelect(
            placeholder="3️⃣ Select AI chat channel...",
            channel_types=[discord.ChannelType.text, discord.ChannelType.public_thread],
            custom_id="aichat_channel",
            default_values=default_channel,
        )
        channel_select.callback = self._channel_callback
        self.add_item(channel_select)

        # Row 3: tone
        self.add_item(ToneSelect(current=self.tone))

        # Row 4: buttons (max 5)
        api_btn = Button(
            label="🔑 API Key" + (" ✅" if self.api_key else ""),
            style=discord.ButtonStyle.primary if not self.api_key else discord.ButtonStyle.secondary,
            custom_id="aichat_apikey",
        )
        api_btn.callback = self._api_key_callback
        self.add_item(api_btn)

        manual_btn = Button(label="✏️ Model ID", style=discord.ButtonStyle.secondary, custom_id="aichat_manual")
        manual_btn.callback = self._manual_model_callback
        self.add_item(manual_btn)

        enabled_btn = Button(
            label="🟢 Enabled" if self.enabled else "🔴 Disabled",
            style=discord.ButtonStyle.success if self.enabled else discord.ButtonStyle.danger,
            custom_id="aichat_toggle",
        )
        enabled_btn.callback = self._toggle_callback
        self.add_item(enabled_btn)

        save_btn = Button(label="💾 Save", style=discord.ButtonStyle.success, custom_id="aichat_save")
        save_btn.callback = self._save_callback
        self.add_item(save_btn)

        cancel_btn = Button(label="❌ Cancel", style=discord.ButtonStyle.danger, custom_id="aichat_cancel")
        cancel_btn.callback = self._cancel_callback
        self.add_item(cancel_btn)

    # -------------------------------------------------------------- plumbing

    async def ensure_author(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Only the person who ran the command can use this form.", ephemeral=True
            )
            return False
        return True

    async def refresh(self, interaction: discord.Interaction, *, fetch_models: bool = False):
        """Acknowledge the interaction and redraw the panel in place."""
        if fetch_models and self.provider and self.api_key:
            # Fetching can take a few seconds - ack first or Discord times out at 3s.
            if not interaction.response.is_done():
                await interaction.response.defer()
            await self._fetch_models()
            self._build_components()
            await interaction.edit_original_response(embed=self._build_embed(), view=self)
            return

        self._build_components()
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=self._build_embed(), view=self)
        else:
            await interaction.response.edit_message(embed=self._build_embed(), view=self)

    async def _fetch_models(self):
        try:
            self._models = await self.service.fetch_models(self.provider, self.api_key)
            self._model_error = None
            if not self._models:
                self._model_error = "Provider returned no usable models."
            elif not self.model_id:
                self._status = f"Loaded {len(self._models)} models from {self.provider}."
        except Exception as e:
            self._models = []
            self._model_error = str(e)[:300] or type(e).__name__
            logger.warning("[aichat] model fetch failed for %s: %s", self.provider, e)

    # ------------------------------------------------------------- callbacks

    async def _channel_callback(self, interaction: discord.Interaction):
        if not await self.ensure_author(interaction):
            return
        # interaction.data["values"] gives snowflakes as STRINGS - they must be
        # ints, otherwise the on_message comparison against channel.id never matches.
        raw = (interaction.data or {}).get("values") or []
        self.channel_id = _as_int(raw[0]) if raw else None
        await self.refresh(interaction)

    async def _api_key_callback(self, interaction: discord.Interaction):
        if not await self.ensure_author(interaction):
            return
        await interaction.response.send_modal(APIKeyModal(self))

    async def _manual_model_callback(self, interaction: discord.Interaction):
        if not await self.ensure_author(interaction):
            return
        if not self.provider:
            await interaction.response.send_message("Pick a provider first.", ephemeral=True)
            return
        await interaction.response.send_modal(ManualModelModal(self))

    async def _toggle_callback(self, interaction: discord.Interaction):
        if not await self.ensure_author(interaction):
            return
        self.enabled = not self.enabled
        await self.refresh(interaction)

    async def _save_callback(self, interaction: discord.Interaction):
        if not await self.ensure_author(interaction):
            return

        missing = []
        if not self.provider:
            missing.append("provider")
        if not self.api_key:
            missing.append("API key")
        if not self.model_id:
            missing.append("model")
        if not self.channel_id:
            missing.append("channel")
        if missing:
            await interaction.response.send_message(
                "❌ Still missing: **" + "**, **".join(missing) + "**.", ephemeral=True
            )
            return

        system_prompt = self.system_prompt()

        config = {
            "provider": self.provider,
            "model_id": self.model_id,
            "channel_id": int(self.channel_id),
            "tone": self.tone,
            "custom_tone": self.custom_tone,
            "system_prompt": system_prompt,
            "enabled": bool(self.enabled),
            "api_key": self.api_key,
        }

        await interaction.response.defer()

        saved, err = await self._save_to_db(config)
        # Only publish to the live cache once we know the shape is good.
        GUILD_AI_CHAT_CONFIG[self.guild_id] = config

        embed = self._build_embed()
        if saved:
            embed.title = "✅ AI Chat Configured"
            embed.description = (
                f"I'll now reply to messages in <#{self.channel_id}>.\n"
                "Make sure I can **View Channel**, **Send Messages** and **Read Message History** there."
            )
            embed.color = 0x22C55E
        else:
            embed.title = "⚠️ Saved for this session only"
            embed.description = f"Config is active now but could not be written to the database: `{err}`"
            embed.color = 0xF59E0B

        for child in self.children:
            child.disabled = True
        await interaction.edit_original_response(embed=embed, view=self)
        self.stop()

        logger.info(
            "[aichat] guild %s configured: provider=%s model=%s channel=%s enabled=%s",
            self.guild_id, self.provider, self.model_id, self.channel_id, self.enabled,
        )

    async def _cancel_callback(self, interaction: discord.Interaction):
        if not await self.ensure_author(interaction):
            return
        embed = discord.Embed(
            title="❌ Configuration Cancelled",
            description="No changes were saved.",
            color=0xE11D48,
        )
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    # ------------------------------------------------------------------ misc

    def system_prompt(self) -> str:
        if self.tone == "custom" and self.custom_tone:
            return self.custom_tone
        return self.service.TONE_PRESETS.get(self.tone) or self.service.TONE_PRESETS["casual"]

    async def _save_to_db(self, config: dict):
        try:
            db = getattr(self.bot, "db", None)
            if not db:
                return False, "database not available"
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_chat (
                    guild_id INTEGER PRIMARY KEY,
                    config TEXT NOT NULL
                )
                """
            )
            await db.execute(
                "INSERT OR REPLACE INTO ai_chat (guild_id, config) VALUES (?, ?)",
                (self.guild_id, json.dumps(config)),
            )
            return True, None
        except Exception as e:
            logger.error("Failed to save AI chat config: %s", e, exc_info=True)
            return False, f"{type(e).__name__}: {str(e)[:120]}"

    def _build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="💬 AI Chat Configuration",
            description=(
                "Pick a provider, enter its API key, choose a model and a channel.\n"
                "The bot will then reply to every message posted in that channel."
            ),
            color=0x6366F1,
        )

        embed.add_field(name="1. Provider", value=self.provider or "❌ Not selected", inline=True)
        embed.add_field(name="2. API Key", value="✅ Set" if self.api_key else "❌ Not set", inline=True)

        if not self.provider:
            model_value = "Select a provider first"
        elif self.model_id:
            model_value = f"`{self.model_id}`"
        else:
            model_value = "❌ Not selected"
        embed.add_field(name="3. Model", value=model_value, inline=True)

        embed.add_field(
            name="4. Channel",
            value=f"<#{self.channel_id}>" if self.channel_id else "❌ Not selected",
            inline=True,
        )

        tone_display = self.tone.capitalize()
        if self.tone == "custom":
            tone_display += " ✅" if self.custom_tone else " ⚠️ (empty)"
        embed.add_field(name="5. Tone", value=tone_display, inline=True)
        embed.add_field(name="Status", value="🟢 Enabled" if self.enabled else "🔴 Disabled", inline=True)

        if self._model_error:
            embed.add_field(
                name="⚠️ Model list",
                value=f"{self._model_error[:400]}\n\nYou can still use **✏️ Model ID** to type one manually.",
                inline=False,
            )
        elif self._status:
            embed.add_field(name="ℹ️ Info", value=self._status[:400], inline=False)

        embed.add_field(name="System Prompt", value=self.system_prompt()[:500], inline=False)
        embed.set_footer(text="Configure the options above, then press 💾 Save")
        return embed


def _as_int(value) -> Optional[int]:
    """Coerce snowflakes that may arrive as str (component payloads / old JSON)."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class AIChat(commands.Cog):
    """AI-powered casual chat in a designated channel."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.service = AIChatService()
        # channel_id -> list of {role, content}
        self.conversations: dict[int, List[dict]] = {}
        # Guilds we've already looked up and found nothing for (avoids a DB hit per message)
        self._no_config: set[int] = set()
        self._locks: dict[int, asyncio.Lock] = {}

    # ------------------------------------------------------------- commands

    @commands.command(name="aichat", help="Configure the AI chat channel (server admins only)")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def aichat_prefix(self, ctx: commands.Context):
        await self._show_config(ctx)

    @app_commands.command(name="aichat", description="Configure the AI chat channel (server admins only)")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def aichat_slash(self, interaction: discord.Interaction):
        perms = getattr(interaction.user, "guild_permissions", None)
        is_owner = interaction.guild and interaction.user.id == interaction.guild.owner_id
        if not is_owner and not (perms and perms.administrator):
            await interaction.response.send_message(
                "❌ You need the **Administrator** permission to configure AI chat.", ephemeral=True
            )
            return
        await self._show_config(interaction)

    async def _show_config(self, ctx):
        is_interaction = isinstance(ctx, discord.Interaction)
        guild = ctx.guild
        guild_id = guild.id if guild else 0
        user_id = ctx.user.id if is_interaction else ctx.author.id

        existing_config = await self._load_config(guild_id)
        view = AIChatConfigView(self.bot, guild_id, user_id, existing_config, service=self.service)
        embed = view._build_embed()

        if is_interaction:
            await ctx.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            # Ephemeral isn't possible for prefix commands; the API key is never
            # rendered in the embed, and it's only ever typed into a private modal.
            await ctx.send(embed=embed, view=view)

    # ---------------------------------------------------------------- config

    async def _load_config(self, guild_id: int) -> Optional[dict]:
        if guild_id in GUILD_AI_CHAT_CONFIG:
            return GUILD_AI_CHAT_CONFIG[guild_id]
        try:
            db = getattr(self.bot, "db", None)
            if db:
                row = await db.fetchone("SELECT config FROM ai_chat WHERE guild_id = ?", (guild_id,))
                if row and row["config"]:
                    config = json.loads(row["config"])
                    # Old rows may have stored the channel id as a string.
                    config["channel_id"] = _as_int(config.get("channel_id"))
                    GUILD_AI_CHAT_CONFIG[guild_id] = config
                    return config
        except Exception as e:
            logger.error("Failed to load AI chat config: %s", e, exc_info=True)
        return None

    # --------------------------------------------------------------- runtime

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if self.bot.user and message.author.id == self.bot.user.id:
            return

        content = (message.content or "").strip()

        config = GUILD_AI_CHAT_CONFIG.get(message.guild.id)
        if config is None:
            if message.guild.id in self._no_config:
                return
            config = await self._load_config(message.guild.id)
            if config is None:
                self._no_config.add(message.guild.id)
                return

        if not config.get("enabled"):
            return

        channel_id = _as_int(config.get("channel_id"))
        if not channel_id or message.channel.id != channel_id:
            return

        # Don't answer command invocations posted in the AI channel.
        prefixes = self.bot.command_prefix
        if isinstance(prefixes, str):
            prefixes = (prefixes,)
        if content.startswith(tuple(prefixes)) or content.startswith("/"):
            return

        # Nothing to send the model (sticker/attachment-only post).
        if not content:
            return

        provider = config.get("provider")
        model_id = config.get("model_id")
        api_key = config.get("api_key")
        if not (provider and model_id and api_key):
            logger.warning("[aichat] guild %s: incomplete config, run b.aichat again", message.guild.id)
            return

        lock = self._locks.setdefault(message.channel.id, asyncio.Lock())
        async with lock:
            history = self.conversations.get(message.channel.id, [])
            try:
                async with message.channel.typing():
                    response = await self.service.generate_response(
                        provider=provider,
                        model_id=model_id,
                        api_key=api_key,
                        user_message=content,
                        system_prompt=config.get("system_prompt")
                        or self.service.TONE_PRESETS["casual"],
                        conversation_history=history,
                    )
            except Exception as e:
                logger.error("[aichat] generation failed: %s", e, exc_info=True)
                try:
                    await message.reply(
                        f"⚠️ AI chat failed: `{type(e).__name__}: {str(e)[:250]}`",
                        mention_author=False,
                    )
                except discord.HTTPException:
                    pass
                return

            if not response or not response.strip():
                return

            history = history + [
                {"role": "user", "content": content},
                {"role": "assistant", "content": response},
            ]
            self.conversations[message.channel.id] = history[-20:]

            try:
                chunks = _chunk(response)
                await message.reply(chunks[0], mention_author=False)
                for extra in chunks[1:]:
                    await message.channel.send(extra)
            except discord.Forbidden:
                logger.warning(
                    "[aichat] missing permissions to reply in #%s (%s)",
                    message.channel, message.channel.id,
                )
            except discord.HTTPException as e:
                logger.error("[aichat] failed to send reply: %s", e)

    async def cog_unload(self):
        await self.service.close()


async def setup(bot: commands.Bot):
    await bot.add_cog(AIChat(bot))
