"""Interactive help: category menu, rich per-command details, and autocomplete.

The overview and per-category pages are driven by a dropdown, while
`/help <command>` (or `b.help <command>`) shows full details for one command,
including prefix + slash usage, aliases, and parameter descriptions.
"""

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Select, Button

# Canonical category key -> (emoji, display name)
CATEGORY_STYLE = {
    "Info": ("📘", "Info"),
    "Embed": ("📝", "Embeds"),
    "Moderation": ("🛡️", "Moderation"),
    "Tickets": ("🎫", "Tickets"),
    "Music": ("🎵", "Music"),
    "Wallet": ("👛", "Wallet"),
    "Money": ("💼", "Jobs & Money"),
    "Profile": ("🪪", "Profile"),
    "Claims": ("🎁", "Rewards"),
    "Gambling": ("🎲", "Gambling"),
    "Social": ("🤝", "Market & Social"),
    "Joke": ("😄", "Fun"),
    "Meme": ("🖼️", "Memes"),
    "AIChat": ("💬", "AI Chat"),
    "AIModeration": ("🤖", "AI Moderation"),
    "WelcomeLeave": ("👋", "Welcome & Leave"),
    "Maintenance": ("🔧", "Maintenance"),
    "Help": ("❓", "Help"),
    "Misc": ("📦", "Misc"),
}

# Display order for categories (canonical keys).
CATEGORY_ORDER = [
    "Info",
    "Embed",
    "Moderation",
    "Tickets",
    "Music",
    "Wallet",
    "Money",
    "Profile",
    "Claims",
    "Gambling",
    "Social",
    "Joke",
    "Meme",
    "AIChat",
    "AIModeration",
    "WelcomeLeave",
    "Maintenance",
    "Help",
    "Misc",
]


class Help(commands.Cog):
    """Browse every command with an interactive category menu."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ------------------------------------------------------------ index

    @staticmethod
    def _default_entry(name: str, category: str) -> dict:
        return {
            "name": name,
            "category": category,
            "desc": "No description.",
            "aliases": [],
            "prefix": None,
            "slash": None,
            "params": [],
        }

    def _build_index(self) -> dict:
        """Merge prefix + slash commands into one entry per command name."""
        index: dict = {}

        # Prefix commands first (their help/usage tends to be richer).
        for cmd in self.bot.commands:
            if cmd.hidden:
                continue
            category = cmd.cog_name or "Misc"
            entry = index.setdefault(cmd.name, self._default_entry(cmd.name, category))
            entry["category"] = category
            entry["desc"] = cmd.help or cmd.short_doc or entry["desc"]
            entry["aliases"] = list(cmd.aliases or [])
            entry["prefix"] = cmd.usage or f"b.{cmd.qualified_name} {cmd.signature}".strip()

        # Slash commands, grouped by their cog.
        for cog_name, cog in self.bot.cogs.items():
            for cmd in cog.get_app_commands():
                entry = index.setdefault(cmd.name, self._default_entry(cmd.name, cog_name))
                entry["category"] = cog_name
                entry["desc"] = cmd.description or entry["desc"]
                params = []
                for p in cmd.parameters:
                    choices = getattr(p, "choices", None) or []
                    params.append(
                        {
                            "name": p.name,
                            "required": p.required,
                            "description": (p.description or "").strip(),
                            "choices": [c.name for c in choices],
                        }
                    )
                entry["params"] = params
                entry["slash"] = self._slash_usage(cmd)

        return index

    @staticmethod
    def _slash_usage(cmd) -> str:
        parts = []
        for p in cmd.parameters:
            parts.append(f"<{p.name}>" if p.required else f"[{p.name}]")
        return ("/" + cmd.qualified_name + " " + " ".join(parts)).strip()

    def _categories(self, index: dict) -> list:
        present = {e["category"] for e in index.values()}
        return [c for c in CATEGORY_ORDER if c in present]

    @staticmethod
    def _style(category: str) -> tuple:
        return CATEGORY_STYLE.get(category, ("📦", category))

    @staticmethod
    def _category_entries(index: dict, category: str) -> list:
        return sorted(
            (e for e in index.values() if e["category"] == category),
            key=lambda e: e["name"],
        )

    def _find(self, query: str) -> dict | None:
        q = (query or "").lower().strip()
        if not q:
            return None
        index = self._build_index()
        if q in index:
            return index[q]
        for entry in index.values():
            if q in [a.lower() for a in entry["aliases"]]:
                return entry
        return None

    # --------------------------------------------------------- commands

    @commands.command(
        name="help",
        aliases=["h", "commands"],
        help="Show all commands, browse by category, or get details for one command.",
        usage="b.help [command]",
    )
    async def help(self, ctx: commands.Context, *, command: str = None):
        if command:
            entry = self._find(command)
            if entry is None:
                await ctx.send(f"No command named `{command}` was found.")
                return
            await ctx.send(embed=self._detail_embed(entry), view=HelpDetailView(self, entry))
        else:
            await ctx.send(embed=self._overview_embed(), view=HelpMenuView(self))

    @app_commands.command(name="help", description="Browse all commands by category, or get details for one.")
    @app_commands.describe(command="A command name (or alias) to get details for")
    async def slash_help(self, interaction: discord.Interaction, command: str = None):
        if command:
            entry = self._find(command)
            if entry is None:
                await interaction.response.send_message(f"No command named `{command}` was found.", ephemeral=True)
                return
            await interaction.response.send_message(embed=self._detail_embed(entry), view=HelpDetailView(self, entry))
        else:
            await interaction.response.send_message(embed=self._overview_embed(), view=HelpMenuView(self))

    @slash_help.autocomplete("command")
    async def _command_autocomplete(self, interaction: discord.Interaction, current: str):
        index = self._build_index()
        current = (current or "").strip().lower()
        starts, contains = [], []
        for name in sorted(index):
            entry = index[name]
            hay = [name] + entry["aliases"]
            if not current:
                starts.append(name)
            elif any(h.startswith(current) for h in hay):
                starts.append(name)
            elif any(current in h for h in hay):
                contains.append(name)
        ordered = starts + contains
        return [app_commands.Choice(name=n[:100], value=n[:100]) for n in ordered[:25]]

    # ------------------------------------------------------------ embeds

    def _overview_embed(self) -> discord.Embed:
        index = self._build_index()
        total = len(index)
        embed = discord.Embed(
            title="Bloop Bot — Help",
            description=(
                f"**{total}** commands across **{len(self._categories(index))}** categories.\n"
                "Every command works with the **`b.`** prefix or as a **slash** command.\n\n"
                "Pick a category from the dropdown below, or run `/help <command>` "
                "for details on a single command."
            ),
            color=discord.Color.blurple(),
        )
        for cat in self._categories(index):
            emoji, display = self._style(cat)
            entries = self._category_entries(index, cat)
            names = ", ".join(f"`{e['name']}`" for e in entries)
            embed.add_field(name=f"{emoji} {display}", value=f"{len(entries)} command(s): {names}", inline=False)
        embed.set_footer(text="Tip: angle brackets < > are required, square brackets [ ] are optional.")
        return embed

    def _category_embed(self, category: str) -> discord.Embed:
        index = self._build_index()
        emoji, display = self._style(category)
        entries = self._category_entries(index, category)

        embed = discord.Embed(title=f"{emoji} {display}", color=discord.Color.blurple())
        if not entries:
            embed.description = "No commands here."
            return embed

        lines = []
        for e in entries:
            usage = self._usage_summary(e)
            lines.append(f"**{e['name']}** — {e['desc']}\n{usage}")
        embed.description = "\n\n".join(lines)
        embed.set_footer(
            text=f"{len(entries)} command(s) · pick another category below, or use /help <command> for details."
        )
        return embed

    @staticmethod
    def _usage_summary(entry: dict) -> str:
        parts = []
        if entry["prefix"]:
            parts.append(f"`{entry['prefix']}`")
        if entry["slash"]:
            parts.append(f"`{entry['slash']}`")
        return " · ".join(parts)

    def _detail_embed(self, entry: dict) -> discord.Embed:
        emoji, display = self._style(entry["category"])
        embed = discord.Embed(title=f"Help — `{entry['name']}`", color=discord.Color.blurple())
        embed.description = entry["desc"]

        if entry["prefix"]:
            value = f"`{entry['prefix']}`"
            if entry["aliases"]:
                value += f"\nAliases: {', '.join('`b.' + a + '`' for a in entry['aliases'])}"
            embed.add_field(name="Prefix usage", value=value, inline=False)

        if entry["slash"]:
            embed.add_field(name="Slash usage", value=f"`{entry['slash']}`", inline=False)

        if entry["params"]:
            lines = []
            for p in entry["params"]:
                req = "required" if p["required"] else "optional"
                desc = p["description"]
                if p["choices"]:
                    desc = (desc + f" Options: {', '.join(p['choices'])}.").strip()
                line = f"`{p['name']}` — {req}"
                if desc:
                    line += f" · {desc}"
                lines.append(line)
            embed.add_field(name="Parameters", value="\n".join(lines), inline=False)

        embed.set_footer(text=f"Category: {emoji} {display} · < > required, [ ] optional")
        return embed

    # ------------------------------------------------------------ views

    class _CategorySelect(Select):
        def __init__(self, cog: "Help", current: str | None):
            index = cog._build_index()
            options = []
            for cat in cog._categories(index):
                emoji, display = cog._style(cat)
                count = len(cog._category_entries(index, cat))
                options.append(
                    discord.SelectOption(
                        label=f"{emoji} {display}",
                        value=cat,
                        description=f"{count} command(s)",
                        default=(cat == current),
                    )
                )
            super().__init__(
                placeholder="🗂️ Choose a category…",
                min_values=1,
                max_values=1,
                options=options,
            )
            self.cog = cog

        async def callback(self, interaction: discord.Interaction):
            category = self.values[0]
            await interaction.response.edit_message(
                embed=self.cog._category_embed(category),
                view=HelpMenuView(self.cog, category=category),
            )


class HelpMenuView(View):
    """Dropdown-driven help menu (overview + per-category pages)."""

    def __init__(self, cog: Help, category: str | None = None):
        super().__init__(timeout=None)
        self.cog = cog
        self.add_item(Help._CategorySelect(cog, category))


class HelpDetailView(View):
    """Navigation buttons shown on a single command's detail page."""

    def __init__(self, cog: Help, entry: dict):
        super().__init__(timeout=None)
        self.cog = cog
        self.entry = entry

    @discord.ui.button(label="📖 Overview", style=discord.ButtonStyle.secondary)
    async def overview(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(
            embed=self.cog._overview_embed(),
            view=HelpMenuView(self.cog),
        )

    @discord.ui.button(label="🗂️ Category", style=discord.ButtonStyle.secondary)
    async def category(self, interaction: discord.Interaction, button: Button):
        cat = self.entry["category"]
        await interaction.response.edit_message(
            embed=self.cog._category_embed(cat),
            view=HelpMenuView(self.cog, category=cat),
        )


# ------------------------------------------------------------------ setup


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
