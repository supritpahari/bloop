"""Joke command — fetches from JokeAPI and sends an embed."""

import logging
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

FALLBACK_JOKES = [
    "Why do programmers prefer dark mode? Because light attracts bugs.",
    "There are only 10 types of people in the world: those who understand binary and those who don't.",
    "A SQL query walks into a bar, walks up to two tables and asks... 'Can I join you?'",
    "Why was the function sad? Because it lost its return value.",
    "Why don't Python programmers need sunglasses? Because they're used to bright IDE themes.",
]

API_URL = "https://v2.jokeapi.dev/joke/Any?type=single"


class Joke(commands.Cog):
    """Fetch random jokes from JokeAPI."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _fetch_joke(self) -> Optional[str]:
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(API_URL) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        joke = data.get("joke")
                        if joke:
                            return str(joke).strip()
                        setup = data.get("setup")
                        punchline = data.get("punchline")
                        if setup and punchline:
                            return f"{setup}\n\n{punchline}"
        except Exception as e:
            logger.warning(f"Joke API fetch failed: {e}")
        return None

    async def _send_joke(self, ctx):
        joke_text = await self._fetch_joke()
        if not joke_text:
            import random
            joke_text = random.choice(FALLBACK_JOKES)

        embed = discord.Embed(
            title="😂 Random Joke",
            description=joke_text,
            color=0xF43F5E,
        )
        embed.set_footer(text="Fetched from JokeAPI • Fallback used if API is down")

        if isinstance(ctx, discord.Interaction):
            await ctx.followup.send(embed=embed)
        else:
            await ctx.send(embed=embed)

    @commands.command(name="joke", help="Get a random joke")
    async def joke_prefix(self, ctx: commands.Context):
        await self._send_joke(ctx)

    @app_commands.command(name="joke", description="Get a random joke")
    async def joke_slash(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self._send_joke(interaction)


async def setup(bot: commands.Bot):
    await bot.add_cog(Joke(bot))
