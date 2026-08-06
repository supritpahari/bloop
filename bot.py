import asyncio
import os

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from economy import config
from economy.db import Database
from economy.db import init_crop_grow

load_dotenv()

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


async def main():
    db = Database()
    await db.setup()
    bot.db = db
    disk = await db.disk_usage()
    info = await db.info()
    print(f"[db] {info['path']}")
    print(f"[db] size: {info['size'] / 1024 / 1024:.2f} MB | disk free: {disk['free'] / 1024 / 1024 / 1024:.1f} GB")
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
        try:
            await bot.start(TOKEN)
        finally:
            await db.close()


if __name__ == "__main__":
    asyncio.run(main())
