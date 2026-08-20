"""Neko command backed by Nekos API's official Python client."""

import asyncio
import logging
import time
from typing import Any

import discord
from anime_api.apis import NekosAPI
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

NEKO_CATEGORY = "kemonomimi"
COOLDOWN_SECONDS = 3


class Neko(commands.Cog):
    """Fetch random neko images from Nekos API."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.nekos = NekosAPI()
        self._request_lock = asyncio.Lock()
        self._cooldowns: dict[int, float] = {}

    def _cooldown_remaining(self, user_id: int) -> float:
        """Return the remaining cooldown and record an allowed request."""
        now = time.monotonic()
        remaining = COOLDOWN_SECONDS - (now - self._cooldowns.get(user_id, 0))
        if remaining > 0:
            return remaining
        self._cooldowns[user_id] = now
        return 0

    async def _fetch_neko(self) -> Any | None:
        """Fetch without blocking Discord's event loop.

        anime-api uses the synchronous requests library and performs its own
        rate limiting, so calls are moved to a worker thread and serialized.
        """
        try:
            async with self._request_lock:
                result = await asyncio.to_thread(
                    self.nekos.get_random_image,
                    categories=[NEKO_CATEGORY],
                )
                logger.info(f"Nekos API raw result: {result!r}")
                logger.info(f"Nekos API result type: {type(result)}")
                if result:
                    logger.info(f"Nekos API result attrs: url={getattr(result, 'url', 'MISSING')}, id={getattr(result, 'id', 'MISSING')}")
                return result
        except Exception:
            logger.exception("Could not fetch an image from Nekos API")
            return None

    @staticmethod
    def _build_embed(image: Any) -> discord.Embed:
        artist = getattr(image, "artist", None)
        source = getattr(image, "source", None)
        image_id = getattr(image, "id", None)

        description = []
        if artist:
            artist_name = getattr(artist, "name", None)
            artist_url = getattr(artist, "url", None)
            if artist_name:
                description.append(
                    f"Artist: [{artist_name}]({artist_url})"
                    if artist_url
                    else f"Artist: {artist_name}"
                )

        embed = discord.Embed(
            title="🐱 Random Neko",
            description="\n".join(description) or None,
            color=0xF5A9D0,
        )
        embed.set_image(url=image.url)

        if source and getattr(source, "url", None):
            source_name = getattr(source, "name", None) or "Original source"
            embed.add_field(name="Source", value=f"[{source_name}]({source.url})")

        footer = "Powered by Nekos API"
        if image_id:
            footer += f" • ID: {image_id}"
        embed.set_footer(text=footer)
        return embed

    async def _send_neko(self, target: commands.Context | discord.Interaction):
        user_id = target.user.id if isinstance(target, discord.Interaction) else target.author.id
        remaining = self._cooldown_remaining(user_id)
        if remaining:
            message = f"⏳ Please wait {remaining:.1f}s before requesting another neko."
            if isinstance(target, discord.Interaction):
                await target.response.send_message(message, ephemeral=True)
            else:
                await target.send(message)
            return

        if isinstance(target, discord.Interaction):
            await target.response.defer()
            image = await self._fetch_neko()
        else:
            async with target.typing():
                image = await self._fetch_neko()

        logger.info(f"_send_neko got image: {image!r}")
        if image:
            logger.info(f"image.url = {getattr(image, 'url', 'MISSING')}")

        if image is None or not getattr(image, "url", None):
            message = "😿 Couldn't fetch a neko right now. Please try again later!"
            if isinstance(target, discord.Interaction):
                await target.followup.send(message, ephemeral=True)
            else:
                await target.send(message)
            return

        embed = self._build_embed(image)
        if isinstance(target, discord.Interaction):
            await target.followup.send(embed=embed)
        else:
            await target.send(embed=embed)

    @commands.command(name="neko", help="Get a random neko image from Nekos API")
    async def neko_prefix(self, ctx: commands.Context):
        """Prefix command: b.neko."""
        await self._send_neko(ctx)

    @app_commands.command(name="neko", description="Get a random neko image")
    async def neko_slash(self, interaction: discord.Interaction):
        """Slash command: /neko."""
        await self._send_neko(interaction)


async def setup(bot: commands.Bot):
    """Load the Neko cog."""
    await bot.add_cog(Neko(bot))
