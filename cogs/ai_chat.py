"""AI Chat cog with interactive configuration form."""

import json
import logging
import re
from typing import Optional, List

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Select, Button, Modal, TextInput, ChannelSelect

from ai_moderation.chat_service import AIChatService, AIModel

logger = logging.getLogger(__name__)

# In-memory config storage
GUILD_AI_CHAT_CONFIG = {}


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
            placeholder="Select AI provider...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="aichat_provider"
        )

    async def callback(self, interaction: discord.Interaction):
        self.view.provider = self.values[0]
        await self.view.fetch_models(interaction)


class ModelSelect(Select):
    """Dropdown for selecting AI model."""

    def __init__(self, models: List[AIModel], current: Optional[str] = None):
        options = []
        for model in models[:25]:
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
            custom_id="aichat_model",
            disabled=len(options) == 1 and options[0].value == "none"
        )

    async def callback(self, interaction: discord.Interaction):
        self.view.model_id = self.values[0]
        await interaction.response.defer()


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
                description=label,
                default=(key == current)
            ) for key, label in self.TONES.items()
        ]
        super().__init__(
            placeholder="Select chat tone/personality...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="aichat_tone"
        )

    async def callback(self, interaction: discord.Interaction):
        self.view.tone = self.values[0]
        if self.values[0] == "custom":
            await interaction.response.send_modal(CustomToneModal(self.view))
        else:
            self.view.custom_tone = None
            await interaction.response.defer()


class CustomToneModal(Modal, title="Custom AI Personality"):
    """Modal for entering custom tone."""

    tone_input = TextInput(
        label="Describe the AI's personality",
        placeholder="e.g. You are a sarcastic cat who gives advice in riddles...",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=500,
    )

    def __init__(self, view: "AIChatConfigView"):
        super().__init__()
        self.config_view = view

    async def on_submit(self, interaction: discord.Interaction):
        self.config_view.custom_tone = self.tone_input.value
        await interaction.response.send_message(
            f"✅ Custom tone set: {self.tone_input.value[:100]}...",
            ephemeral=True
        )


class APIKeyModal(Modal, title="Enter API Key"):
    """Modal for entering the API key."""

    api_key = TextInput(
        label="API Key",
        placeholder="sk-... or your provider's API key",
        style=discord.TextStyle.short,
        required=True,
        max_length=200,
    )

    def __init__(self, view: "AIChatConfigView"):
        super().__init__()
        self.config_view = view

    async def on_submit(self, interaction: discord.Interaction):
        self.config_view.api_key = self.api_key.value
        if self.config_view.provider:
            await self.config_view.fetch_models(interaction)
        else:
            await interaction.response.send_message(
                "✅ API key saved. Now select a provider to fetch models.",
                ephemeral=True
            )


class AIChatConfigView(View):
    """Interactive configuration view for AI chat."""

    def __init__(self, bot: commands.Bot, guild_id: int, user_id: int, existing_config: Optional[dict] = None):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.user_id = user_id
        self.service = AIChatService()

        # Config state
        self.provider = existing_config.get("provider") if existing_config else None
        self.model_id = existing_config.get("model_id") if existing_config else None
        self.channel_id = existing_config.get("channel_id") if existing_config else None
        self.tone = existing_config.get("tone", "casual") if existing_config else "casual"
        self.custom_tone = existing_config.get("custom_tone") if existing_config else None
        # Default new setups to enabled so saving a fresh config actually turns it on.
        self.enabled = existing_config.get("enabled", True) if existing_config else True
        self.api_key = existing_config.get("api_key") if existing_config else None
        self._models = []

        self._build_components()

    def _build_components(self):
        self.clear_items()

        # Provider
        self.add_item(ProviderSelect(current=self.provider))

        # Model
        if self.provider and self._models:
            self.add_item(ModelSelect(self._models, current=self.model_id))
        elif self.provider:
            self.add_item(ModelSelect([], current=None))

        # Channel select
        channel_select = ChannelSelect(
            placeholder="Select AI chat channel...",
            channel_types=[discord.ChannelType.text],
            custom_id="aichat_channel"
        )
        channel_select.callback = self._channel_callback
        self.add_item(channel_select)
        if self.channel_id:
            # Pre-select by setting the value - we need to handle this differently
            pass

        # Tone
        self.add_item(ToneSelect(current=self.tone))

        # API Key button
        api_btn = Button(label="🔑 Set API Key", style=discord.ButtonStyle.secondary, custom_id="aichat_apikey")
        api_btn.callback = self._api_key_callback
        self.add_item(api_btn)

        # Toggle enabled
        enabled_btn = Button(
            label="🟢 Enabled" if self.enabled else "🔴 Disabled",
            style=discord.ButtonStyle.success if self.enabled else discord.ButtonStyle.danger,
            custom_id="aichat_toggle"
        )
        enabled_btn.callback = self._toggle_callback
        self.add_item(enabled_btn)

        # Save
        save_btn = Button(label="💾 Save", style=discord.ButtonStyle.success, custom_id="aichat_save")
        save_btn.callback = self._save_callback
        self.add_item(save_btn)

        # Cancel
        cancel_btn = Button(label="❌ Cancel", style=discord.ButtonStyle.danger, custom_id="aichat_cancel")
        cancel_btn.callback = self._cancel_callback
        self.add_item(cancel_btn)

    async def _channel_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the command author can configure this.", ephemeral=True)
            return
        self.channel_id = interaction.data["values"][0]
        await interaction.response.defer()

    async def _api_key_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the command author can configure this.", ephemeral=True)
            return
        await interaction.response.send_modal(APIKeyModal(self))

    async def fetch_models(self, interaction: discord.Interaction):
        if not self.api_key:
            await interaction.response.send_message("❌ Please set an API key first.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            self._models = await self.service.fetch_models(self.provider, self.api_key)
            self._build_components()
            await interaction.edit_original_response(embed=self._build_embed(), view=self)
        except ValueError as e:
            await interaction.followup.send(f"❌ Failed to fetch models: {e}", ephemeral=True)
        except Exception as e:
            logger.error(f"Error fetching models: {e}")
            await interaction.followup.send("❌ An error occurred while fetching models.", ephemeral=True)

    async def _toggle_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the command author can toggle this.", ephemeral=True)
            return
        self.enabled = not self.enabled
        self._build_components()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    async def _save_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the command author can save this config.", ephemeral=True)
            return

        if not self.provider:
            await interaction.response.send_message("❌ Please select a provider.", ephemeral=True)
            return
        if not self.api_key:
            await interaction.response.send_message("❌ Please set an API key.", ephemeral=True)
            return
        if self.provider and not self.model_id and self._models:
            await interaction.response.send_message("❌ Please select a model.", ephemeral=True)
            return
        if not self.channel_id:
            await interaction.response.send_message("❌ Please select a channel.", ephemeral=True)
            return

        # Build system prompt
        tone_preset = self.service.TONE_PRESETS.get(self.tone, "")
        system_prompt = self.custom_tone if self.tone == "custom" and self.custom_tone else tone_preset

        config = {
            "provider": self.provider,
            "model_id": self.model_id,
            "channel_id": self.channel_id,
            "tone": self.tone,
            "custom_tone": self.custom_tone,
            "system_prompt": system_prompt,
            "enabled": self.enabled,
            "api_key": self.api_key,
        }
        GUILD_AI_CHAT_CONFIG[self.guild_id] = config

        self.bot.loop.create_task(self._save_to_db(config))

        embed = self._build_embed()
        embed.title = "✅ AI Chat Configured"
        embed.color = 0x22C55E

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)

    async def _cancel_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the command author can cancel.", ephemeral=True)
            return

        embed = discord.Embed(title="❌ Configuration Cancelled", description="No changes were saved.", color=0xE11D48)
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)

    async def _save_to_db(self, config: dict):
        try:
            db = self.bot.db
            if db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS ai_chat (
                        guild_id INTEGER PRIMARY KEY,
                        config TEXT NOT NULL
                    )
                """)
                await db.execute(
                    "INSERT OR REPLACE INTO ai_chat (guild_id, config) VALUES (?, ?)",
                    (self.guild_id, json.dumps(config))
                )
        except Exception as e:
            logger.error(f"Failed to save AI chat config: {e}")

    def _build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="💬 AI Chat Configuration",
            description="Set up a channel where AI chats with users casually.\nOnly the server owner can use this form.",
            color=0x6366F1
        )

        embed.add_field(name="Provider", value=self.provider or "❌ Not selected", inline=True)
        embed.add_field(name="Model", value=self.model_id or ("❌ Not selected" if self.provider else "Select provider first"), inline=True)
        
        channel_mention = f"<#{self.channel_id}>" if self.channel_id else "❌ Not selected"
        embed.add_field(name="Channel", value=channel_mention, inline=True)
        
        tone_display = self.tone.capitalize()
        if self.tone == "custom" and self.custom_tone:
            tone_display += " (Custom)"
        embed.add_field(name="Tone", value=tone_display, inline=True)
        
        embed.add_field(name="Status", value="🟢 Enabled" if self.enabled else "🔴 Disabled", inline=True)
        embed.add_field(name="API Key", value="✅ Set" if self.api_key else "❌ Not set", inline=True)

        if self.provider:
            embed.add_field(name="System Prompt Preview", value=(self.custom_tone or self.service.TONE_PRESETS.get(self.tone, ""))[:500], inline=False)

        embed.set_footer(text="Configure options above, then click Save")
        return embed


class AIChat(commands.Cog):
    """AI-powered casual chat in a designated channel."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.service = AIChatService()
        # In-memory conversation history: guild_id -> list of {role, content}
        self.conversations: dict[int, List[dict]] = {}

    @commands.command(name="aichat", help="Configure AI chat channel (server owner only)")
    @commands.is_owner()
    async def aichat_prefix(self, ctx: commands.Context):
        await self._show_config(ctx)

    @app_commands.command(name="aichat", description="Configure AI chat channel (server owner only)")
    @app_commands.default_permissions(administrator=True)
    async def aichat_slash(self, interaction: discord.Interaction):
        if interaction.guild and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("❌ Only the server owner can configure AI chat.", ephemeral=True)
            return
        await self._show_config(interaction)

    async def _show_config(self, ctx):
        guild_id = ctx.guild.id if ctx.guild else 0
        user_id = ctx.author.id if hasattr(ctx, 'author') else ctx.user.id

        existing_config = await self._load_config(guild_id)
        view = AIChatConfigView(self.bot, guild_id, user_id, existing_config)
        embed = view._build_embed()

        if hasattr(ctx, 'response'):
            await ctx.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            await ctx.send(embed=embed, view=view)

    async def _load_config(self, guild_id: int) -> Optional[dict]:
        try:
            db = self.bot.db
            if db:
                row = await db.fetchone("SELECT config FROM ai_chat WHERE guild_id = ?", (guild_id,))
                if row and row["config"]:
                    config = json.loads(row["config"])
                    GUILD_AI_CHAT_CONFIG[guild_id] = config
                    return config
        except Exception as e:
            logger.error(f"Failed to load AI chat config: {e}")
        return GUILD_AI_CHAT_CONFIG.get(guild_id)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore bots, DMs, commands
        if message.author.bot or not message.guild:
            return
        if message.content.startswith(self.bot.command_prefix) or message.content.startswith("/"):
            return

        config = GUILD_AI_CHAT_CONFIG.get(message.guild.id)
        if not config:
            config = await self._load_config(message.guild.id)
        if not config:
            logger.info(f"[aichat] guild {message.guild.id}: no config, ignoring message in #{message.channel.name}")
            return
        if not config.get("enabled"):
            logger.info(f"[aichat] guild {message.guild.id}: config exists but disabled, ignoring")
            return

        # Only respond in the designated channel
        if message.channel.id != config.get("channel_id"):
            logger.info(
                f"[aichat] guild {message.guild.id}: message in #{message.channel.id} "
                f"but configured channel is {config.get('channel_id')}, ignoring"
            )
            return

        # Don't reply to the bot itself
        if message.author.id == self.bot.user.id:
            return

        try:
            # Get conversation history
            history = self.conversations.get(message.guild.id, [])

            # Generate response
            response = await self.service.generate_response(
                provider=config["provider"],
                model_id=config["model_id"],
                api_key=config["api_key"],
                user_message=message.content,
                system_prompt=config["system_prompt"],
                conversation_history=history
            )

            # Update history
            history.append({"role": "user", "content": message.content})
            history.append({"role": "assistant", "content": response})
            # Keep last 20 messages (10 pairs)
            if len(history) > 20:
                history = history[-20:]
            self.conversations[message.guild.id] = history

            # Send reply (mention user for clarity)
            await message.reply(response, mention_author=False)

        except Exception as e:
            logger.error(f"AI chat error: {e}")
            try:
                await message.channel.send(
                    f"⚠️ AI chat failed: `{type(e).__name__}: {str(e)[:300]}`"
                )
            except Exception:
                pass

    async def cog_unload(self):
        await self.service.close()


async def setup(bot: commands.Bot):
    await bot.add_cog(AIChat(bot))