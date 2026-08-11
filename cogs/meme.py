"""Meme cog for fetching and displaying memes via meme-api.com."""

import logging
import random
import time

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

MEME_API_BASE = "https://meme-api.com/gimme"


class Meme(commands.Cog):
    """Cog for the /meme and b.meme commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._session: aiohttp.ClientSession | None = None
        self._cooldowns: dict[int, float] = {}

    async def cog_unload(self):
        """Clean up when cog is unloaded."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15)
            )
        return self._session

    def _check_cooldown(self, user_id: int) -> tuple[bool, float]:
        """Check if user is on cooldown.

        Returns:
            Tuple of (is_on_cooldown, remaining_seconds).
        """
        now = time.time()
        last_used = self._cooldowns.get(user_id, 0)
        remaining = 3 - (now - last_used)  # 3 second cooldown
        if remaining > 0:
            return True, remaining
        self._cooldowns[user_id] = now
        return False, 0

    async def _fetch_meme(self, subreddit: str | None = None) -> dict | None:
        """Fetch a single meme from meme-api.com.

        Returns the raw meme object, or None if it could not be fetched.
        """
        session = await self._get_session()
        url = MEME_API_BASE
        if subreddit:
            url = f"{MEME_API_BASE}/{subreddit}"

        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.error(f"meme-api returned {resp.status} for {url}")
                    return None
                data = await resp.json()
        except Exception as e:
            logger.error(f"Error fetching meme from {url}: {e}")
            return None

        # The single-meme endpoint returns one object directly.
        # A multi-meme endpoint would wrap them in "memes"; handle both.
        if "memes" in data and isinstance(data["memes"], list) and data["memes"]:
            return data["memes"][0]
        if data.get("url"):
            return data
        return None

    @staticmethod
    def _build_embed(meme: dict) -> discord.Embed:
        embed = discord.Embed(
            title=meme.get("title", "Meme"),
            url=meme.get("postLink"),
            color=0x4FD1C5,
        )
        embed.set_image(url=meme.get("url"))
        subreddit = meme.get("subreddit", "unknown")
        author = meme.get("author", "unknown")
        ups = meme.get("ups", 0)
        embed.set_footer(
            text=f"r/{subreddit} • 👍 {ups} • by u/{author}"
        )
        return embed

    async def _send_meme(self, target, subreddit: str | None):
        """Shared logic for slash and prefix commands."""
        on_cd, remaining = self._check_cooldown(target.user.id if hasattr(target, "user") else target.author.id)
        if on_cd:
            msg = f"⏳ Please wait {remaining:.1f}s before requesting another meme."
            if isinstance(target, discord.Interaction):
                await target.response.send_message(msg, ephemeral=True)
            else:
                await target.send(msg)
            return

        if isinstance(target, discord.Interaction):
            await target.response.defer()
        else:
            async with target.typing():
                pass

        meme = await self._fetch_meme(subreddit)

        if not meme:
            msg = "😔 Couldn't fetch a meme right now. Try again later!"
            if isinstance(target, discord.Interaction):
                await target.followup.send(msg, ephemeral=True)
            else:
                await target.send(msg)
            return

        embed = self._build_embed(meme)
        if isinstance(target, discord.Interaction):
            await target.followup.send(embed=embed)
        else:
            await target.send(embed=embed)

    @app_commands.command(name="meme", description="Get a random meme")
    @app_commands.describe(subreddit="Specific subreddit to fetch from (optional)")
    async def meme_slash(
        self,
        interaction: discord.Interaction,
        subreddit: str = None,
    ):
        """Fetch and display a meme."""
        sub = subreddit.lower().strip() if subreddit else None
        await self._send_meme(interaction, sub)

    @commands.command(name="meme", help="Get a random meme (optional: subreddit)")
    async def meme_prefix(self, ctx: commands.Context, subreddit: str = None):
        """Prefix command: b.meme [subreddit]."""
        sub = subreddit.lower().strip() if subreddit else None
        await self._send_meme(ctx, sub)


async def setup(bot: commands.Bot):
    """Set up the Meme cog."""
    await bot.add_cog(Meme(bot))
