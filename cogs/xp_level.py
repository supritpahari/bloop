"""XP per message + level-up embeds."""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from economy.xp_db import XPDB

logger = logging.getLogger(__name__)

XP_PER_MESSAGE = 10


def xp_for_level(level: int) -> int:
    """Total XP required to reach the given level."""
    return 100 * (level - 1)


class XPLevel(commands.Cog):
    """Award XP per chat message and notify on level-up."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        # Ignore command messages
        if message.content.startswith(self.bot.command_prefix) or message.content.startswith("/"):
            return

        db: XPDB = getattr(self.bot, "xp_db", None)
        if db is None:
            return

        try:
            data = await db.add_xp(message.guild.id, message.author.id, XP_PER_MESSAGE)
            xp = data.get("xp", 0)
            level = data.get("level", 1)
            new_level = level
            # Level up loop (progressive: 100 * (level-1) total)
            while xp >= xp_for_level(new_level + 1):
                new_level += 1

            if new_level > level:
                await db.set_level(message.guild.id, message.author.id, new_level)
                embed = discord.Embed(
                    title="🎉 Level Up!",
                    description=f"{message.author.mention} reached **Level {new_level}**!\n"
                    f"(`{xp}` XP total — next at `{xp_for_level(new_level + 1)}` XP)",
                    color=0xF59E0B,
                )
                embed.set_footer(text="Keep chatting to earn more XP!")
                try:
                    await message.channel.send(embed=embed)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"XP system error: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(XPLevel(bot))
