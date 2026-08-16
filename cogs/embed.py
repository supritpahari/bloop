"""Create and post custom embeds.

`b.embed` walks you through it interactively (reply with one message);
`/embed` opens a form (modal) instead. Both require the Manage Messages
permission so regular members can't use the bot to fake announcements.
"""

import asyncio
import re

import discord
from discord import app_commands
from discord.ext import commands

HEX_COLOR_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")

EMBED_FORMAT_HELP = (
    "Reply with **one message** in this format:\n"
    "`Title | Text | Footer | Color | Channel`\n"
    "Example: `Server rules | Be kind and have fun! | Staff | #5865F2 | #rules`\n"
    "Use `-` to skip optional parts (footer, color) — the channel defaults to this one."
)


def build_embed(
    title: str | None,
    text: str | None,
    footer: str | None,
    color_hex: str | None,
) -> tuple[discord.Embed | None, str | None]:
    """Build the embed from raw parts. Returns (embed, error) — exactly one is None."""
    if not title or not text:
        return None, "the embed needs at least a **title** and **text**"
    if len(title) > 256:
        return None, "the title is too long (max 256 characters)"
    if len(text) > 4096:
        return None, "the text is too long (max 4096 characters)"
    if footer and len(footer) > 2048:
        return None, "the footer is too long (max 2048 characters)"
    if color_hex:
        if not HEX_COLOR_RE.match(color_hex):
            return None, f"`{color_hex}` isn't a valid hex color — use something like `#5865F2`"
        color = discord.Color(int(color_hex.lstrip("#"), 16))
    else:
        color = discord.Color.blurple()
    embed = discord.Embed(title=title, description=text, color=color)
    if footer:
        embed.set_footer(text=footer)
    return embed, None


async def post_embed(
    guild: discord.Guild,
    author: discord.Member,
    channel: discord.abc.GuildChannel,
    title: str | None,
    text: str | None,
    footer: str | None,
    color_hex: str | None,
) -> str | None:
    """Validate and post the embed. Returns an error message, or None on success."""
    if not isinstance(channel, discord.TextChannel):
        return "I can only post embeds in regular text channels."
    bot_perms = channel.permissions_for(guild.me)
    if not (bot_perms.send_messages and bot_perms.embed_links):
        return f"I don't have permission to post embeds in {channel.mention}."
    user_perms = channel.permissions_for(author)
    if not (user_perms.view_channel and user_perms.send_messages):
        return f"you don't have permission to post in {channel.mention}."
    embed, error = build_embed(title, text, footer, color_hex)
    if error:
        return error
    try:
        await channel.send(embed=embed)
    except discord.Forbidden:
        return f"I don't have permission to post embeds in {channel.mention}."
    except discord.HTTPException as exc:
        return f"Discord rejected the embed: {exc.text}"
    return None


class EmbedModal(discord.ui.Modal, title="Create an embed"):
    """The form shown by /embed."""

    embed_title = discord.ui.TextInput(
        label="Title",
        placeholder="Server rules",
        max_length=256,
    )
    text = discord.ui.TextInput(
        label="Text",
        style=discord.TextStyle.paragraph,
        placeholder="Be kind and have fun!",
        max_length=4000,
    )
    footer = discord.ui.TextInput(
        label="Footer (optional)",
        required=False,
        max_length=2048,
    )
    color = discord.ui.TextInput(
        label="Color (optional, e.g. #5865F2)",
        required=False,
        min_length=6,
        max_length=7,
        placeholder="#5865F2",
    )

    def __init__(self, channel: discord.TextChannel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        error = await post_embed(
            interaction.guild,
            interaction.user,
            self.channel,
            title=self.embed_title.value.strip(),
            text=self.text.value.strip(),
            footer=self.footer.value.strip() or None,
            color_hex=self.color.value.strip() or None,
        )
        if error:
            await interaction.response.send_message(
                f"❌ {error} Run `/embed` again to retry.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"✅ Embed posted in {self.channel.mention}.", ephemeral=True
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        print(f"Ignoring exception in embed modal: {error}")
        message = f"Something went wrong: {error}"
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


class Embed(commands.Cog):
    """Create custom announcement-style embeds."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(
        name="embed",
        help="Interactively create an embed and post it in a channel.",
        usage="b.embed  (then reply with: Title | Text | Footer | Color | Channel)",
    )
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def embed(self, ctx: commands.Context):
        await ctx.send(EMBED_FORMAT_HELP + "\n*(You have 2 minutes to reply.)*")

        def check(message: discord.Message) -> bool:
            return message.author == ctx.author and message.channel == ctx.channel

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=120)
        except asyncio.TimeoutError:
            await ctx.send("⌛ Timed out — run `b.embed` again when you're ready.")
            return

        parts = [part.strip() for part in msg.content.split("|")]
        if len(parts) != 5:
            await ctx.send(
                f"❌ I expected 5 parts separated by `|` but got {len(parts)}. "
                "Run `b.embed` again (avoid `|` inside your text).\n\n" + EMBED_FORMAT_HELP
            )
            return

        title, text, footer, color, channel_text = (
            None if part in ("", "-") else part for part in parts
        )

        if channel_text is None:
            channel = ctx.channel
        else:
            try:
                channel = await commands.TextChannelConverter().convert(ctx, channel_text)
            except commands.ChannelNotFound:
                await ctx.send(
                    f"❌ I can't find a channel matching `{channel_text}`. "
                    "Run `b.embed` again (mention it, e.g. `#general`)."
                )
                return

        error = await post_embed(
            ctx.guild,
            ctx.author,
            channel,
            title=title,
            text=text,
            footer=footer,
            color_hex=color,
        )
        if error:
            await ctx.send(f"❌ {error} Run `b.embed` to try again.")
            return
        if channel == ctx.channel:
            await ctx.send("✅ Done.")
        else:
            await ctx.send(f"✅ Embed posted in {channel.mention}.")

    @app_commands.command(name="embed", description="Create and post a custom embed (opens a form).")
    @app_commands.describe(channel="Where to post the embed (defaults to this channel)")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def slash_embed(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel = None,
    ):
        await interaction.response.send_modal(EmbedModal(channel or interaction.channel))


async def setup(bot: commands.Bot):
    await bot.add_cog(Embed(bot))
