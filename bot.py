import os

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
PREFIX = "b."

if not TOKEN:
    raise ValueError("DISCORD_TOKEN not set. Copy .env.example to .env and add your bot token.")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"Prefix: {PREFIX} | Slash commands available via /")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash command(s)")
    except Exception as e:
        print(f"Failed to sync slash commands: {e}")


@bot.command(name="ping")
async def ping(ctx: commands.Context):
    latency = round(bot.latency * 1000, 2)
    await ctx.send(f"Pong! {latency}ms")


@bot.command(name="echo")
async def echo(ctx: commands.Context, *, message: str):
    await ctx.send(message)


@bot.tree.command(name="ping", description="Check the bot's latency")
async def slash_ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000, 2)
    await interaction.response.send_message(f"Pong! {latency}ms")


@bot.tree.command(name="echo", description="Repeat a message back")
@app_commands.describe(message="The message to echo")
async def slash_echo(interaction: discord.Interaction, message: str):
    await interaction.response.send_message(message)


bot.run(TOKEN)
