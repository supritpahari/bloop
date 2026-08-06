import asyncio
import os

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
PREFIX = "b."

if not TOKEN:
    raise ValueError("DISCORD_TOKEN is not set. Copy .env.example to .env and add your bot token.")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)


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
        print(f"Ignoring exception in command {ctx.command}: {error}")
        await ctx.send(f"Something went wrong: {error}")


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
        print(f"Ignoring exception in slash command {interaction.command}: {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message(
                f"Something went wrong: {error}", ephemeral=True
            )


async def main():
    async with bot:
        await bot.load_extension("cogs.moderation")
        await bot.load_extension("cogs.info")
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
