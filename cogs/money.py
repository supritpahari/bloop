"""Money-making commands: work, search, crime, beg, fish, mine, hunt, dig, farm."""

import random
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from economy import config, db as dbm, utils as u


def _tool_check(tools: list, tool_key: str):
    """Return a usable tool dict or None."""
    return next((t for t in tools if t["tool_key"] == tool_key and t["durability"] > 0), None)


class Money(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db: dbm.Database = bot.db

    # ------------------------------------------------------------- work

    async def _work(self, ctx):
        user_id = u.user_id_of(ctx)
        if await u.check_cooldown(self.db, ctx, "work", config.WORK_COOLDOWN, "work again"):
            return
        job = random.choice(config.JOBS)
        mult = await u.income_multiplier(self.db, user_id)
        low, high = job["pay"]
        if random.random() < job["chance"]:
            pay = int(random.uniform(low, high) * mult)
            await self.db.try_add_coins(user_id, pay, note=f"Work: {job['name']}")
            await u.track_activity(self.db, user_id, "work", 1)
            await u.track_earn(self.db, user_id, pay)
            embed = discord.Embed(title=f"{job['emoji']} {job['name']}", color=0x22C55E)
            embed.description = random.choice(job["success"]) + f"\n\nYou earned **{u.CURRENCY} {u.fmt(pay)}**."
        else:
            await u.track_activity(self.db, user_id, "work", 1)
            embed = discord.Embed(title=f"{job['emoji']} {job['name']}", color=0xE11D48)
            embed.description = random.choice(job["fail"]) + "\n\nYou earned nothing today."
        levels = await u.grant_xp(self.db, user_id, job["xp"])
        if levels:
            embed.add_field(name="🎉 Level up!", value=f"You reached level **{levels[-1]}**!", inline=False)
        events = await u.maybe_random_event(self.db, ctx, user_id, 200)
        if events:
            embed.add_field(name="Random event", value="\n".join(events), inline=False)
        achievements = await u.check_achievements(self.db, user_id)
        for ach in achievements:
            embed.add_field(name=f"🏅 Achievement: {ach['name']}", value=ach["desc"], inline=False)
        await u.reply(ctx, embed=embed)

    @commands.command(name="work", aliases=["job"], help="Work a random job for coins.", usage="b.work")
    async def work(self, ctx):
        await self._work(ctx)

    @app_commands.command(name="work", description="Work a random job for coins.")
    async def slash_work(self, interaction: discord.Interaction):
        await self._work(interaction)

    # ------------------------------------------------------------- search

    async def _search(self, ctx):
        user_id = u.user_id_of(ctx)
        if await u.check_cooldown(self.db, ctx, "search", config.SEARCH_COOLDOWN, "search again"):
            return
        loc = random.choice(config.LOCATIONS)
        mult = await u.income_multiplier(self.db, user_id)
        luck = await u.luck_multiplier(self.db, user_id)
        coins = int(random.uniform(loc["low"], loc["high"]) * mult)
        await self.db.try_add_coins(user_id, coins, note=f"Search: {loc['name']}")
        await u.track_activity(self.db, user_id, "search", 1)
        await u.track_earn(self.db, user_id, coins)
        embed = discord.Embed(title=f"🔍 Search — {loc['emoji']} {loc['name'].title()}", color=0x3B82F6)
        lines = [f"{random.choice(loc['lines'])} {u.CURRENCY} **{u.fmt(coins)}**."]
        for item_key, chance in loc["loot"]:
            if random.random() < chance * (1 + luck):
                item = config.ITEMS[item_key]
                await self.db.add_item(user_id, item_key, 1)
                lines.append(f"You also pocket **{u.item_display(item_key, item)}**! ({u.rarity_emoji(item['rarity'])} {item['rarity']})")
                if item["rarity"] in ("Legendary", "Mythic"):
                    await u.track_activity(self.db, user_id, "search", 0, legendary=True)
        if random.random() < loc["risk"]:
            fine = min(int(coins * 0.3), 100)
            try:
                await self.db.try_remove_coins(user_id, fine, note="Search caught")
                lines.append(f"🚨 A security drone catches you snooping and fines you {u.CURRENCY} **{u.fmt(fine)}**.")
            except dbm.InsufficientFunds:
                lines.append("🚨 A security drone catches you snooping, but you're already broke. It sighs.")
        embed.description = "\n".join(lines)
        levels = await u.grant_xp(self.db, user_id, random.randint(15, 30))
        if levels:
            embed.add_field(name="🎉 Level up!", value=f"You reached level **{levels[-1]}**!", inline=False)
        events = await u.maybe_random_event(self.db, ctx, user_id, coins)
        if events:
            embed.add_field(name="Random event", value="\n".join(events), inline=False)
        await u.reply(ctx, embed=embed)

    @commands.command(name="search", aliases=["scout"], help="Search random locations for coins and loot.", usage="b.search")
    async def search(self, ctx):
        await self._search(ctx)

    @app_commands.command(name="search", description="Search random locations for coins and loot.")
    async def slash_search(self, interaction: discord.Interaction):
        await self._search(interaction)

    # ------------------------------------------------------------- crime

    async def _crime(self, ctx):
        user_id = u.user_id_of(ctx)
        if await u.check_cooldown(self.db, ctx, "crime", config.CRIME_COOLDOWN, "commit crime again"):
            return
        crime = random.choice(config.CRIMES)
        mult = await u.income_multiplier(self.db, user_id)
        roll = random.random()
        await u.track_activity(self.db, user_id, "crime", 1)
        embed = discord.Embed(title=f"{crime['emoji']} {crime['name']}", color=0xE11D48)
        if roll < crime["chance"]:
            pay = int(random.uniform(*crime["pay"]) * mult)
            await self.db.try_add_coins(user_id, pay, note=f"Crime: {crime['name']}")
            await self.db.bump_stat(user_id, "crimes_success", 1)
            await u.track_earn(self.db, user_id, pay)
            embed.color = 0x22C55E
            embed.description = random.choice(crime["success"]) + f"\n\nYou get away with {u.CURRENCY} **{u.fmt(pay)}**."
        elif roll < crime["chance"] + 0.15:
            fine = crime["fine"]
            try:
                await self.db.try_remove_coins(user_id, fine, note="Crime fine")
                embed.description = random.choice(crime["fail"]) + f"\n\nYou're fined {u.CURRENCY} **{u.fmt(fine)}**."
            except dbm.InsufficientFunds:
                embed.description = random.choice(crime["fail"]) + "\n\nYou're fined, but your wallet is empty. The judge sighs."
        else:
            jail = crime["jail"]
            await self.db.set_cooldown(user_id, "crime_jail", jail)
            await self.db.bump_stat(user_id, "times_jailed", 1)
            embed.description = random.choice(crime["fail"]) + f"\n\n🚔 The cops take you in. You're grounded for **{u.fmt_time(jail)}** (no work, no fun)."
        levels = await u.grant_xp(self.db, user_id, crime["xp"])
        if levels:
            embed.add_field(name="🎉 Level up!", value=f"You reached level **{levels[-1]}**!", inline=False)
        achievements = await u.check_achievements(self.db, user_id)
        for ach in achievements:
            embed.add_field(name=f"🏅 Achievement: {ach['name']}", value=ach["desc"], inline=False)
        await u.reply(ctx, embed=embed)

    @commands.command(name="crime", aliases=["rob"], help="Commit a risky crime. Money, fines, or jail await.", usage="b.crime")
    async def crime(self, ctx):
        await self._crime(ctx)

    @app_commands.command(name="crime", description="Commit a risky crime. Money, fines, or jail await.")
    async def slash_crime(self, interaction: discord.Interaction):
        await self._crime(interaction)

    # ------------------------------------------------------------- beg

    async def _beg(self, ctx):
        user_id = u.user_id_of(ctx)
        if await u.check_cooldown(self.db, ctx, "beg", config.BEG_COOLDOWN, "beg again"):
            return
        npc = random.choice(config.NPCS)
        embed = discord.Embed(title=f"{npc['emoji']} {npc['name']}", color=0xF59E0B)
        line = random.choice(npc["lines"])
        if npc["type"] == "grumpy":
            embed.description = line + "\n\nYou get nothing. You feel judged."
        else:
            low, high = npc["pool"]
            amount = random.randint(low, high)
            if amount <= 0:
                embed.description = line + "\n\nYou get nothing. The economy is cruel."
            else:
                await self.db.try_add_coins(user_id, amount, note=f"Begging: {npc['name']}")
                await u.track_earn(self.db, user_id, amount)
                embed.color = 0x22C55E
                embed.description = line + f"\n\nYou receive {u.CURRENCY} **{u.fmt(amount)}**."
            if random.random() < 0.02:
                gems = 1
                await self.db.add_gems(user_id, gems, note="Begging gem")
                embed.add_field(name="✨ Incredible luck", value=f"The NPC tosses you **{gems} gem** out of sheer surprise.", inline=False)
        await u.reply(ctx, embed=embed)

    @commands.command(name="beg", aliases=["begging"], help="Beg NPCs for coins with humorous results.", usage="b.beg")
    async def beg(self, ctx):
        await self._beg(ctx)

    @app_commands.command(name="beg", description="Beg an NPC for coins.")
    async def slash_beg(self, interaction: discord.Interaction):
        await self._beg(interaction)

    # ------------------------------------------------------------- activity base

    async def _activity(self, ctx, tool_key: str, action: str, pool: list, cooldown: int, xp: int,
                        success_lines: dict):
        user_id = u.user_id_of(ctx)
        tools = await self.db.get_tools(user_id)
        tool = _tool_check(tools, tool_key)
        if not tool:
            item = config.ITEMS[tool_key]
            await u.reply(ctx, embed=discord.Embed(
                title=f"{item['emoji']} Missing tool",
                description=f"You need a **{item['name']}** to {action}. Buy one with `/buy {tool_key}`!",
                color=0xE11D48,
            ))
            return
        jail = await self.db.cooldown_remaining(user_id, "crime_jail")
        if jail > 0:
            await u.cooldown_error(ctx, jail, "do anything (you're in jail)")
            return
        if await u.check_cooldown(self.db, ctx, action, cooldown, f"{action} again"):
            return
        luck = await u.luck_multiplier(self.db, user_id)
        item_key = u.roll_pool(pool, luck)
        item = config.ITEMS[item_key]
        await self.db.add_item(user_id, item_key, 1)
        remaining = await self.db.use_tool_durability(tool["id"])
        await u.track_activity(self.db, user_id, action, 1, legendary=item["rarity"] in ("Legendary", "Mythic"))
        if item["rarity"] == "Mythic":
            await self.db.bump_stat(user_id, f"mythic_{action}", 1)
        if item_key in ("amethyst", "sapphire", "ruby", "diamond", "meteorite_shard", "starforged_ore"):
            await self.db.bump_stat(user_id, "gems_mined", 1)
        embed = discord.Embed(title=f"{item['emoji']} {action.title()}", color=u.rarity_color(item["rarity"]))
        verb = {"fish": "caught", "mine": "mined", "hunt": "hunted down", "dig": "dug up"}[action]
        embed.description = f"You {verb} **{u.item_display(item_key, item)}** ({u.rarity_emoji(item['rarity'])} {item['rarity']})!\n\nThis is worth {u.CURRENCY} **{u.fmt(item['sell'])}** at the shop."
        roll = random.random()
        if roll < 0.08:
            bonus_key = u.roll_pool(pool, luck)
            bonus = config.ITEMS[bonus_key]
            await self.db.add_item(user_id, bonus_key, 1)
            embed.add_field(name="Bonus find!", value=f"You also {verb} **{u.item_display(bonus_key, bonus)}**!", inline=False)
        elif roll < 0.16:
            miss_lines = [line for line, kind in success_lines.get(action, []) if kind == "miss"]
            if miss_lines:
                embed.add_field(name="Close call", value=random.choice(miss_lines), inline=False)
        if remaining <= 0:
            embed.add_field(name="💥 Tool broke", value=f"Your **{config.ITEMS[tool_key]['name']}** snapped. Buy a new one or use a Repair Kit.", inline=False)
        levels = await u.grant_xp(self.db, user_id, xp + (50 if item["rarity"] in ("Legendary", "Mythic") else 0))
        if levels:
            embed.add_field(name="🎉 Level up!", value=f"You reached level **{levels[-1]}**!", inline=False)
        events = await u.maybe_random_event(self.db, ctx, user_id, max(item["sell"] * 2, 100))
        if events:
            embed.add_field(name="Random event", value="\n".join(events), inline=False)
        achievements = await u.check_achievements(self.db, user_id)
        for ach in achievements:
            embed.add_field(name=f"🏅 Achievement: {ach['name']}", value=ach["desc"], inline=False)
        embed.set_footer(text=f"Tool durability: {max(remaining, 0)}/100")
        await u.reply(ctx, embed=embed)

    # ------------------------------------------------------------- fish/mine/hunt/dig

    async def _fish(self, ctx):
        await self._activity(ctx, "fishing_rod", "fish", config.FISH_POOL, config.FISH_COOLDOWN, 25,
                             config.ACTIVITY_LINES)

    async def _mine(self, ctx):
        await self._activity(ctx, "pickaxe", "mine", config.ORE_POOL, config.MINE_COOLDOWN, 30,
                             config.ACTIVITY_LINES)

    async def _hunt(self, ctx):
        await self._activity(ctx, "hunting_bow", "hunt", config.HUNT_POOL, config.HUNT_COOLDOWN, 35,
                             config.ACTIVITY_LINES)

    async def _dig(self, ctx):
        await self._activity(ctx, "shovel", "dig", config.DIG_POOL, config.DIG_COOLDOWN, 25,
                             config.ACTIVITY_LINES)

    @commands.command(name="fish", help="Catch fish with your fishing rod.", usage="b.fish")
    async def fish(self, ctx):
        await self._fish(ctx)

    @commands.command(name="mine", help="Mine ores and gems with your pickaxe.", usage="b.mine")
    async def mine(self, ctx):
        await self._mine(ctx)

    @commands.command(name="hunt", help="Hunt animals with your bow.", usage="b.hunt")
    async def hunt(self, ctx):
        await self._hunt(ctx)

    @commands.command(name="dig", help="Dig for treasure with your shovel.", usage="b.dig")
    async def dig(self, ctx):
        await self._dig(ctx)

    @app_commands.command(name="fish", description="Catch fish with your fishing rod.")
    async def slash_fish(self, interaction: discord.Interaction):
        await self._fish(interaction)

    @app_commands.command(name="mine", description="Mine ores and gems with your pickaxe.")
    async def slash_mine(self, interaction: discord.Interaction):
        await self._mine(interaction)

    @app_commands.command(name="hunt", description="Hunt animals with your bow.")
    async def slash_hunt(self, interaction: discord.Interaction):
        await self._hunt(interaction)

    @app_commands.command(name="dig", description="Dig for treasure with your shovel.")
    async def slash_dig(self, interaction: discord.Interaction):
        await self._dig(interaction)

    # ------------------------------------------------------------- farm

    def _farm_embed(self, farms: dict, user_name: str) -> discord.Embed:
        embed = discord.Embed(title="🚜 Bloopian Farm", description=f"{user_name}'s plots (grow times in config)", color=0x22C55E)
        now = datetime.now(timezone.utc)
        for plot in range(config.PLOTS):
            f = farms.get(plot)
            if not f:
                embed.add_field(name=f"Plot {plot + 1} 🌱", value="Empty — plant a seed!", inline=True)
            else:
                crop = config.CROPS[f["crop_key"]]
                planted = datetime.strptime(f["planted_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                elapsed = (now - planted).total_seconds()
                remaining = crop["grow"] - elapsed
                if remaining <= 0:
                    embed.add_field(name=f"Plot {plot + 1} {config.ITEMS[f['crop_key']]['emoji']}", value=f"**{config.ITEMS[f['crop_key']]['name']}** — ready to harvest!", inline=True)
                else:
                    embed.add_field(name=f"Plot {plot + 1} {config.ITEMS[f['crop_key']]['emoji']}", value=f"**{config.ITEMS[f['crop_key']]['name']}** — {u.fmt_time(int(remaining))} left", inline=True)
        return embed

    async def _farm(self, ctx):
        user_id = u.user_id_of(ctx)
        farms = await self.db.farms(user_id)
        embed = self._farm_embed(farms, u.author_of(ctx).display_name)
        view = FarmView(self.db, user_id, farms)
        await u.reply(ctx, embed=embed, view=view)

    @commands.command(name="farm", help="View your farm and plant or harvest crops.", usage="b.farm")
    async def farm(self, ctx):
        await self._farm(ctx)

    @app_commands.command(name="farm", description="View your farm and plant or harvest crops.")
    async def slash_farm(self, interaction: discord.Interaction):
        await self._farm(interaction)


class FarmView(discord.ui.View):
    def __init__(self, db, user_id: int, farms: dict):
        super().__init__(timeout=120)
        self.db = db
        self.user_id = user_id
        self.farms = farms
        self.message = None
        self._build()

    def _build(self):
        self.clear_items()
        crop_options = []
        for key, crop in config.CROPS.items():
            item = config.ITEMS[key]
            crop_options.append(discord.SelectOption(label=item["name"], value=key, emoji=item["emoji"], description=f"Grows in {u.fmt_time(crop['grow'])}"))
        for plot in range(config.PLOTS):
            f = self.farms.get(plot)
            if f:
                item = config.ITEMS[f["crop_key"]]
                crop = config.CROPS[f["crop_key"]]
                now = datetime.now(timezone.utc)
                planted = datetime.strptime(f["planted_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                ready = (now - planted).total_seconds() >= crop["grow"]
                if ready:
                    button = discord.ui.Button(label=f"Harvest plot {plot + 1}", emoji="🧺", style=discord.ButtonStyle.success, custom_id=f"harvest:{plot}")
                    button.callback = self._make_harvest_cb(plot)
                else:
                    button = discord.ui.Button(label=f"Plot {plot + 1} ({item['name']})", emoji="⏳", style=discord.ButtonStyle.secondary, disabled=True, custom_id=f"wait:{plot}")
                    button.callback = self._noop
                self.add_item(button)
        select = discord.ui.Select(placeholder="🌱 Plant a seed...", options=crop_options, custom_id="plant")
        select.callback = self._make_plant_cb()
        self.add_item(select)
        refresh = discord.ui.Button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.blurple, custom_id="refresh")
        refresh.callback = self._make_refresh_cb()
        self.add_item(refresh)

    async def _noop(self, interaction: discord.Interaction):
        await interaction.response.defer()

    def _make_harvest_cb(self, plot: int):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("This isn't your farm!", ephemeral=True)
                return
            result = await self.db.harvest(self.user_id, plot)
            if not result:
                await interaction.response.send_message("Not ready yet!", ephemeral=True)
                return
            crop_key, _ = result
            crop = config.CROPS[crop_key]
            item = config.ITEMS[crop_key]
            qty = random.randint(*crop["yield"])
            await self.db.add_item(self.user_id, crop_key, qty)
            await u.track_activity(self.db, self.user_id, "harvest", 1)
            await self.db.bump_stat(self.user_id, "harvest_count", qty)
            coins = item["sell"] * qty
            await self.db.try_add_coins(self.user_id, coins, note=f"Harvest: {item['name']}")
            await u.track_earn(self.db, self.user_id, coins)
            self.farms = await self.db.farms(self.user_id)
            self._build()
            embed = discord.Embed(title=f"{item['emoji']} Harvested!", color=0x22C55E,
                                  description=f"You gathered **{item['name']}** ×{qty} and sold it for {u.CURRENCY} **{u.fmt(coins)}**.")
            embed.add_field(name="Farm status", value="The plots below are updated.", inline=False)
            await interaction.response.edit_message(embed=embed, view=self)
        return cb

    def _make_plant_cb(self):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("This isn't your farm!", ephemeral=True)
                return
            crop_key = interaction.data["values"][0]
            crop = config.CROPS[crop_key]
            seed_key = crop["seed"]
            seed = config.ITEMS[seed_key]
            if not await self.db.remove_item(self.user_id, seed_key, 1):
                await interaction.response.send_message(f"You need **{seed['name']}** — buy them with `/buy {seed_key}`.", ephemeral=True)
                return
            empty = next((p for p in range(config.PLOTS) if p not in self.farms), None)
            if empty is None:
                await self.db.add_item(self.user_id, seed_key, 1)
                await interaction.response.send_message("All plots are full! Harvest something first.", ephemeral=True)
                return
            await self.db.plant(self.user_id, empty, crop_key)
            self.farms = await self.db.farms(self.user_id)
            self._build()
            item = config.ITEMS[crop_key]
            embed = discord.Embed(title=f"🌱 Planted!", color=0x22C55E,
                                  description=f"Planted **{item['name']}** on plot {empty + 1}. Ready in {u.fmt_time(crop['grow'])}.")
            await interaction.response.edit_message(embed=embed, view=self)
        return cb

    def _make_refresh_cb(self):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("This isn't your farm!", ephemeral=True)
                return
            self.farms = await self.db.farms(self.user_id)
            self._build()
            await interaction.response.edit_message(embed=self._embed_for(self.farms), view=self)
        return cb

    def _embed_for(self, farms: dict) -> discord.Embed:
        embed = discord.Embed(title="🚜 Bloopian Farm", color=0x22C55E)
        now = datetime.now(timezone.utc)
        for plot in range(config.PLOTS):
            f = farms.get(plot)
            if not f:
                embed.add_field(name=f"Plot {plot + 1} 🌱", value="Empty — plant a seed!", inline=True)
            else:
                item = config.ITEMS[f["crop_key"]]
                crop = config.CROPS[f["crop_key"]]
                planted = datetime.strptime(f["planted_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                remaining = crop["grow"] - (now - planted).total_seconds()
                if remaining <= 0:
                    embed.add_field(name=f"Plot {plot + 1} {item['emoji']}", value=f"**{item['name']}** — ready!", inline=True)
                else:
                    embed.add_field(name=f"Plot {plot + 1} {item['emoji']}", value=f"**{item['name']}** — {u.fmt_time(int(remaining))} left", inline=True)
        return embed


async def setup(bot: commands.Bot):
    await bot.add_cog(Money(bot))
