import discord
from discord import app_commands
from discord.ext import commands

COG_ORDER = ["Info", "Moderation", "Help"]


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _build_index(self) -> dict:
        index = {}
        for cmd in self.bot.commands:
            if cmd.hidden:
                continue
            name = cmd.name
            index.setdefault(
                name,
                {
                    "name": name,
                    "cog": cmd.cog_name or "Misc",
                    "desc": "No description.",
                    "prefix": None,
                    "slash": None,
                },
            )
            index[name]["cog"] = cmd.cog_name or index[name]["cog"]
            index[name]["desc"] = cmd.help or cmd.short_doc or index[name]["desc"]
            index[name]["prefix"] = cmd.usage or f"b.{name} {cmd.signature}".strip()

        for cmd in self.bot.tree.walk_commands():
            name = cmd.name
            params = " ".join(f"<{p.name}>" if p.required else f"[{p.name}]" for p in cmd.parameters)
            index.setdefault(
                name,
                {
                    "name": name,
                    "cog": cmd.module.rsplit(".", 1)[-1].replace("_", " ").title(),
                    "desc": cmd.description or "No description.",
                    "prefix": None,
                    "slash": None,
                },
            )
            index[name]["slash"] = f"/{name}{' ' + params if params else ''}"
        return index

    def _find(self, query: str) -> dict | None:
        query = query.lower()
        for cmd in self.bot.commands:
            if cmd.name == query or query in (cmd.aliases or []):
                return self._build_index()[cmd.name]
        for cmd in self.bot.tree.walk_commands():
            if cmd.name == query:
                return self._build_index()[cmd.name]
        return None

    @commands.command(
        name="help",
        aliases=["h", "commands"],
        help="Show all available commands, or details for one command.",
        usage="b.help [command]",
    )
    async def help(self, ctx: commands.Context, *, command: str = None):
        index = self._build_index()
        if command:
            entry = self._find(command)
            if not entry:
                await ctx.send(f"No command named `{command}` was found.")
                return
            embed = self._detail_embed(entry)
        else:
            embed = self._overview_embed(index)
        await ctx.send(embed=embed)

    @app_commands.command(name="help", description="Show all available commands, or details for one command.")
    @app_commands.describe(command="The name of a command to get details for")
    async def slash_help(self, interaction: discord.Interaction, command: str = None):
        index = self._build_index()
        if command:
            entry = self._find(command)
            if not entry:
                await interaction.response.send_message(f"No command named `{command}` was found.", ephemeral=True)
                return
            embed = self._detail_embed(entry)
        else:
            embed = self._overview_embed(index)
        await interaction.response.send_message(embed=embed)

    def _overview_embed(self, index: dict) -> discord.Embed:
        embed = discord.Embed(
            title="Bloop Bot Commands",
            description=(
                "Every command works with the prefix **`b.`** or as a slash command (`/`).\n"
                "Use `b.help <command>` or `/help <command>` for usage details."
            ),
            color=discord.Color.blurple(),
        )
        grouped = {}
        for entry in index.values():
            grouped.setdefault(entry["cog"], []).append(entry)
        for cog in sorted(grouped, key=lambda c: COG_ORDER.index(c) if c in COG_ORDER else 99):
            entries = sorted(grouped[cog], key=lambda e: e["name"])
            value = "\n".join(
                f"**`b.{e['name']}`** / **`/{e['name']}`** — {e['desc']}" for e in entries
            )
            embed.add_field(name=f"{cog}", value=value, inline=False)
        return embed

    def _detail_embed(self, entry: dict) -> discord.Embed:
        embed = discord.Embed(title=f"Help — `{entry['name']}`", color=discord.Color.blurple())
        embed.add_field(name="Description", value=entry["desc"], inline=False)
        if entry["prefix"]:
            embed.add_field(name="Prefix usage", value=f"`{entry['prefix']}`", inline=True)
        if entry["slash"]:
            embed.add_field(name="Slash usage", value=f"`{entry['slash']}`", inline=True)
        embed.set_footer(text="Tip: angle brackets < > are required, square brackets [ ] are optional.")
        return embed


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
