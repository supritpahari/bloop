"""Neko command backed by nekos.life API."""

import asyncio
import logging
import time
from types import SimpleNamespace
from typing import Any

import discord
import httpx
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

NEKO_CATEGORY = "neko"
COOLDOWN_SECONDS = 3


class Neko(commands.Cog):
    """Fetch random neko images from nekos.life API."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
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
        """Fetch without blocking Discord's event loop."""
        try:
            async with self._request_lock:
                # Call nekos.life API directly - simpler and no strict User-Agent requirements
                url = f"https://nekos.life/api/v2/img/{NEKO_CATEGORY}"
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(url)
                    logger.info(f"Nekos API HTTP status: {resp.status_code}")
                    logger.info(f"Nekos API raw response: {resp.text[:500]}")

                    if resp.status_code != 200:
                        logger.error(f"Nekos API returned {resp.status_code}")
                        return None

                    data = resp.json()
                    logger.info(f"Nekos API parsed JSON: {data}")

                    # nekos.life returns {"url": "https://..."}
                    image_url = data.get("url")
                    if not image_url:
                        logger.error(f"Unexpected API response structure: {data}")
                        return None

                    # Return a simple object with the needed attributes
                    return SimpleNamespace(
                        url=image_url,
                        artist=None,
                        source=SimpleNamespace(
                            name="nekos.life",
                            url="https://nekos.life",
                        ),
                        id="unknown",
                    )
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

        footer = "Powered by nekos.life"
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

    @commands.command(name="neko", help="Get a random neko image from nekos.life")
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