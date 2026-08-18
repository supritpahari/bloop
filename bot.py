import asyncio
import logging
import os
import signal
import sys

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from economy import config
from economy.db import Database
from economy.db import init_crop_grow

load_dotenv()

# bot.start() (unlike bot.run()) does NOT configure logging, so cog logger.info/
# warning calls were being silently dropped - which made debugging the AI cogs
# impossible. Set LOG_LEVEL=DEBUG in .env for more detail.
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("discord").setLevel(logging.WARNING)

TOKEN = os.getenv("DISCORD_TOKEN")
PREFIX = "b."

if not TOKEN:
    raise ValueError("DISCORD_TOKEN is not set. Copy .env.example to .env and add your bot token.")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)
bot.db = None

init_crop_grow(config.CROPS)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash command(s)")
    except Exception as e:
        print(f"Failed to sync slash commands: {e}")


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You don't have permission to use this command.")
    elif isinstance(error, commands.BotMissingPermissions):
        await ctx.send("I don't have the required permissions to do that.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(
            f"Missing required argument `{error.param.name}`. "
            f"Usage: `{ctx.prefix}{ctx.command.qualified_name} {ctx.command.signature}`"
        )
    else:
        if _is_disk_error(error):
            print(f"[db] disk/storage error: {error}")
            await ctx.send("🗄️ The database can't write right now (disk or storage issue). An admin can run `b.dbinfo` and `b.dbprune`.")
            return
        print(f"Ignoring exception in command {ctx.command}: {error}")
        await ctx.send(f"Something went wrong: {error}")


def _is_disk_error(error: Exception) -> bool:
    import sqlite3
    if isinstance(error, sqlite3.OperationalError) and "full" in str(error).lower():
        return True
    return any(isinstance(err, sqlite3.OperationalError) and "full" in str(err).lower()
               for err in (getattr(error, "original", None),) if err is not None)


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "You don't have permission to use this command.", ephemeral=True
        )
    elif isinstance(error, app_commands.BotMissingPermissions):
        await interaction.response.send_message(
            "I don't have the required permissions to do that.", ephemeral=True
        )
    else:
        if _is_disk_error(error):
            print(f"[db] disk/storage error: {error}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "🗄️ The database can't write right now (disk or storage issue). An admin can run `/dbinfo` and `/dbprune`.", ephemeral=True
                )
            return
        print(f"Ignoring exception in slash command {interaction.command}: {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message(
                f"Something went wrong: {error}", ephemeral=True
            )


async def shutdown(signal_name: str):
    """Graceful shutdown handler."""
    print(f"Received {signal_name}, shutting down gracefully...")
    if bot.db:
        await bot.db.close()
    if hasattr(bot, "xp_db") and bot.xp_db:
        await bot.xp_db.close()
    if hasattr(bot, "tickets_db") and bot.tickets_db:
        await bot.tickets_db.close()
    await bot.close()
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    asyncio.get_event_loop().stop()


async def main():
    db = Database()
    await db.setup()
    bot.db = db
    from economy.xp_db import XPDB
    bot.xp_db = XPDB()
    await bot.xp_db.setup()
    from economy.tickets_db import TicketsDB
    bot.tickets_db = TicketsDB()
    await bot.tickets_db.setup()
    disk = await db.disk_usage()
    info = await db.info()
    print(f"[db] {info['path']}")
    print(f"[db] size: {info['size'] / 1024 / 1024:.2f} MB | disk free: {disk['free'] / 1024 / 1024 / 1024:.1f} GB")

    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown(s.name)))
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    async with bot:
        await bot.load_extension("cogs.moderation")
        await bot.load_extension("cogs.info")
        await bot.load_extension("cogs.help")
        await bot.load_extension("cogs.wallet")
        await bot.load_extension("cogs.profile")
        await bot.load_extension("cogs.money")
        await bot.load_extension("cogs.claims")
        await bot.load_extension("cogs.gambling")
        await bot.load_extension("cogs.social")
        await bot.load_extension("cogs.maintenance")
        await bot.load_extension("cogs.music")
        await bot.load_extension("cogs.joke")
        await bot.load_extension("cogs.meme")
        await bot.load_extension("cogs.ai_moderation")
        await bot.load_extension("cogs.ai_chat")
        await bot.load_extension("cogs.xp_level")
        await bot.load_extension("cogs.welcome_leave")
        await bot.load_extension("cogs.embed")
        await bot.load_extension("cogs.tickets")
        try:
            await bot.start(TOKEN)
        except asyncio.CancelledError:
            print("Bot startup cancelled")
        except KeyboardInterrupt:
            print("Bot interrupted")
        finally:
            if bot.db:
                await bot.db.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown complete")
        sys.exit(0)
