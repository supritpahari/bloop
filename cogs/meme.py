"""Meme cog for fetching and displaying Reddit memes."""

import logging
import random

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from .reddit_service import RedditMemeService

logger = logging.getLogger(__name__)


class Meme(commands.Cog):
    """Cog for the /meme slash command."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.service = RedditMemeService()
        self._cooldowns: dict[int, float] = {}

    async def cog_unload(self):
        """Clean up when cog is unloaded."""
        await self.service.close()

    def _check_cooldown(self, user_id: int) -> tuple[bool, float]:
        """Check if user is on cooldown.

        Returns:
            Tuple of (is_on_cooldown, remaining_seconds).
        """
        import time
        now = time.time()
        last_used = self._cooldowns.get(user_id, 0)
        remaining = 3 - (now - last_used)  # 3 second cooldown
        if remaining > 0:
            return True, remaining
        self._cooldowns[user_id] = now
        return False, 0

    @app_commands.command(name="meme", description="Get a random meme from Reddit")
    @app_commands.describe(
        subreddit="Specific subreddit to fetch from (optional)",
        mode="Fetch mode: random (default), trending (top of day), or specific subreddit"
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="Random (from all subreddits)", value="random"),
        app_commands.Choice(name="Trending (top posts of the day)", value="trending"),
    ])
    async def meme(
        self,
        interaction: discord.Interaction,
        subreddit: str = None,
        mode: str = "random",
    ):
        """Fetch and display a meme from Reddit.

        Args:
            interaction: The Discord interaction.
            subreddit: Optional specific subreddit name.
            mode: Fetch mode - "random" or "trending".
        """
        # Check cooldown
        on_cd, remaining = self._check_cooldown(interaction.user.id)
        if on_cd:
            await interaction.response.send_message(
                f"⏳ Please wait {remaining:.1f}s before requesting another meme.",
                ephemeral=True,
            )
            return

        # Validate subreddit if provided
        if subreddit:
            subreddit = subreddit.lower().strip()
            if subreddit not in RedditMemeService.SUBREDDITS:
                valid = ", ".join(f"`r/{s}`" for s in RedditMemeService.SUBREDDITS)
                await interaction.response.send_message(
                    f"❌ Invalid subreddit. Supported: {valid}",
                    ephemeral=True,
                )
                return

        # Defer response since fetching can take a moment
        await interaction.response.defer()

        guild_id = interaction.guild_id or 0

        try:
            if mode == "trending":
                meme = await self.service.get_trending_meme(guild_id, subreddit)
            else:
                meme = await self.service.get_random_meme(guild_id, subreddit)

            if not meme:
                await interaction.followup.send(
                    "😔 Couldn't fetch a meme right now. Reddit might be busy or the subreddit has no valid images. Try again!",
                    ephemeral=True,
                )
                return

            embed = self.service.create_embed(meme)
            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in /meme command: {e}")
            await interaction.followup.send(
                "❌ Something went wrong while fetching a meme. Please try again later.",
                ephemeral=True,
            )

    @app_commands.command(name="memelist", description="List all supported meme subreddits")
    async def memelist(self, interaction: discord.Interaction):
        """Show all supported subreddits for the meme command."""
        subreddits = RedditMemeService.SUBREDDITS
        embed = discord.Embed(
            title="📋 Supported Meme Subreddits",
            description="\n".join(f"• `r/{s}`" for s in subreddits),
            color=0x4FD1C5,  # Bloop teal from config
        )
        embed.set_footer(text="Use /meme [subreddit] to fetch from a specific one")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    """Set up the Meme cog."""
    await bot.add_cog(Meme(bot))