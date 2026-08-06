"""Profile, stats, inventory, shop, buy, sell, use."""

import random

import discord
from discord import app_commands
from discord.ext import commands

from economy import config, db as dbm, utils as u


class Profile(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db: dbm.Database = bot.db

    # ------------------------------------------------------------- profile

    async def _profile(self, ctx, member: discord.Member = None):
        member = member or u.author_of(ctx)
        user = await self.db.get_user(member.id)
        stats = await self.db.get_stats(member.id)
        pets = await self.db.pets(member.id)
        embed = discord.Embed(color=u.rarity_color("Legendary"))
        embed.set_author(name=f"{member.display_name}", icon_url=member.display_avatar.url)
        title = user["equipped_title"] or "New Arrival"
        embed.title = f"📋 {title} — Level {user['level']}"
        need = u.xp_needed(user["level"])
        embed.description = f"**Prestige:** {user['prestige']}   **XP:** {u.fmt(user['xp'])}/{u.fmt(need)}"
        embed.add_field(name="Wallet", value=f"{u.CURRENCY} {u.fmt(user['wallet'])}", inline=True)
        embed.add_field(name="Bank", value=f"{u.CURRENCY} {u.fmt(user['bank'])}", inline=True)
        embed.add_field(name="Gems", value=f"{u.GEM} {u.fmt(user['gems'])}", inline=True)
        embed.add_field(name="Titles", value=f"{len(user['titles'])} owned", inline=True)
        embed.add_field(name="Badges", value=f"{len(await self.db.achievements(member.id))} unlocked", inline=True)
        embed.add_field(name="Pets", value=f"{len(pets)} owned", inline=True)
        embed.add_field(
            name="Lifetime earnings",
            value=f"{u.CURRENCY} {u.fmt(stats.get('earned_total', 0))}",
            inline=True,
        )
        embed.add_field(
            name="Lifetime gambling",
            value=f"{u.fmt(stats.get('gambles_placed', 0))} gambles · {u.fmt(stats.get('gambles_won', 0))} wins",
            inline=True,
        )
        active = user.get("active_pet")
        if active:
            pet = config.PETS[active]
            embed.add_field(name="Active pet", value=f"{pet['emoji']} {pet['name']} (Lv {pets[active]['level']})", inline=False)
        await u.reply(ctx, embed=embed)

    @commands.command(name="profile", aliases=["me"], help="Show your player profile.", usage="b.profile [@user]")
    async def profile(self, ctx, member: discord.Member = None):
        await self._profile(ctx, member)

    @app_commands.command(name="profile", description="Show a player profile.")
    @app_commands.describe(member="Who to inspect (defaults to you)")
    async def slash_profile(self, interaction: discord.Interaction, member: discord.Member = None):
        await self._profile(interaction, member)

    # ------------------------------------------------------------- stats

    async def _stats(self, ctx):
        s = await self.db.get_stats(u.user_id_of(ctx))
        embed = discord.Embed(title="📊 Lifetime statistics", color=config.BASE_COLOR)
        embed.add_field(name="Earnings", value=f"{u.CURRENCY} {u.fmt(s.get('earned_total', 0))}", inline=True)
        embed.add_field(name="Spending", value=f"{u.CURRENCY} {u.fmt(s.get('spent_total', 0))}", inline=True)
        embed.add_field(name="Banked", value=f"{u.CURRENCY} {u.fmt(s.get('banked_total', 0))}", inline=True)
        embed.add_field(name="Jobs worked", value=f"{u.fmt(s.get('work_count', 0))}", inline=True)
        embed.add_field(name="Searches", value=f"{u.fmt(s.get('search_count', 0))}", inline=True)
        embed.add_field(name="Crimes committed", value=f"{u.fmt(s.get('crime_count', 0))} · {u.fmt(s.get('crimes_success', 0))} succeeded", inline=True)
        embed.add_field(name="Times jailed", value=f"{u.fmt(s.get('times_jailed', 0))}", inline=True)
        embed.add_field(name="Fish caught", value=f"{u.fmt(s.get('fish_count', 0))} · {u.fmt(s.get('mythic_fish', 0))} mythic", inline=True)
        embed.add_field(name="Ores mined", value=f"{u.fmt(s.get('mine_count', 0))} · {u.fmt(s.get('gems_mined', 0))} gems", inline=True)
        embed.add_field(name="Animals hunted", value=f"{u.fmt(s.get('hunt_count', 0))}", inline=True)
        embed.add_field(name="Digs", value=f"{u.fmt(s.get('dig_count', 0))}", inline=True)
        embed.add_field(name="Crops harvested", value=f"{u.fmt(s.get('harvest_count', 0))}", inline=True)
        embed.add_field(name="Gambles", value=f"{u.fmt(s.get('gambles_placed', 0))} · {u.fmt(s.get('gambles_won', 0))} wins", inline=True)
        embed.add_field(name="Gambling profit", value=f"{u.CURRENCY} {u.fmt(s.get('gamble_profit', 0))}", inline=True)
        embed.add_field(name="Best single win", value=f"{u.CURRENCY} {u.fmt(s.get('best_gamble_win', 0))}", inline=True)
        embed.add_field(name="Items crafted", value=f"{u.fmt(s.get('items_crafted', 0))}", inline=True)
        embed.add_field(name="Items bought", value=f"{u.fmt(s.get('items_bought', 0))}", inline=True)
        embed.add_field(name="Items sold", value=f"{u.fmt(s.get('items_sold', 0))}", inline=True)
        embed.add_field(name="Trades completed", value=f"{u.fmt(s.get('trades_done', 0))}", inline=True)
        embed.add_field(name="Market sales", value=f"{u.fmt(s.get('market_sold', 0))}", inline=True)
        embed.add_field(name="Lottery tickets", value=f"{u.fmt(s.get('lottery_tickets', 0))}", inline=True)
        await u.reply(ctx, embed=embed)

    @commands.command(name="stats", help="Show your lifetime economy statistics.", usage="b.stats")
    async def stats(self, ctx):
        await self._stats(ctx)

    @app_commands.command(name="stats", description="Show your lifetime economy statistics.")
    async def slash_stats(self, interaction: discord.Interaction):
        await self._stats(interaction)

    # ------------------------------------------------------------- inventory

    async def _inventory(self, ctx):
        user_id = u.user_id_of(ctx)
        inv = await self.db.inventory(user_id)
        tools = await self.db.get_tools(user_id)
        if not inv and not tools:
            await u.reply(ctx, embed=discord.Embed(title="🎒 Inventory", description="Empty! Check `/shop` to buy something.", color=config.BASE_COLOR))
            return
        embed = discord.Embed(title="🎒 Inventory", color=config.BASE_COLOR)
        cats = ["collectible", "crop", "fish", "ore", "animal", "dig", "consumable", "seed", "egg", "title", "misc"]
        cat_names = {"collectible": "Collectibles", "crop": "Crops", "fish": "Fish", "ore": "Ores & Minerals",
                     "animal": "Trophies", "dig": "Dig Finds", "consumable": "Consumables", "seed": "Seeds",
                     "egg": "Eggs", "title": "Titles", "misc": "Misc"}
        grouped = {}
        for key, qty in inv.items():
            item = config.ITEMS.get(key)
            if not item:
                continue
            grouped.setdefault(item["cat"], []).append((key, item, qty))
        for cat in cats:
            if cat not in grouped:
                continue
            lines = []
            for key, item, qty in sorted(grouped[cat], key=lambda x: config.RARITY_ORDER.index(x[1]["rarity"])):
                lines.append(f"{u.rarity_emoji(item['rarity'])} {item['emoji']} **{item['name']}** ×{u.fmt(qty)}")
            embed.add_field(name=cat_names.get(cat, cat.title()), value="\n".join(lines), inline=True)
        if tools:
            lines = []
            for t in tools:
                item = config.ITEMS[t["tool_key"]]
                dur = "🔋" * max(0, (t["durability"] + 9) // 25)
                lines.append(f"{item['emoji']} **{item['name']}** — durability {t['durability']}/100 {dur}")
            embed.add_field(name="Tools", value="\n".join(lines), inline=False)
        await u.reply(ctx, embed=embed)

    @commands.command(name="inventory", aliases=["inv"], help="View all items you own.", usage="b.inventory")
    async def inventory(self, ctx):
        await self._inventory(ctx)

    @app_commands.command(name="inventory", description="View all items you own.")
    async def slash_inventory(self, interaction: discord.Interaction):
        await self._inventory(interaction)

    # ------------------------------------------------------------- shop

    def _shop_embed(self, category: str) -> discord.Embed:
        cats = ["tool", "seed", "consumable", "egg", "title"]
        names = {"tool": "🛠️ Tools", "seed": "🌱 Seeds", "consumable": "🧪 Consumables", "egg": "🥚 Pet Eggs", "title": "👑 Titles"}
        embed = discord.Embed(title="🏪 Bloopian General Store", description=f"Category: **{names[category]}** — use `/buy <item>`", color=config.BASE_COLOR)
        for key, item in config.ITEMS.items():
            if item["cat"] != category or "price" not in item and "price_gems" not in item:
                continue
            price = f"{u.GEM} {item['price_gems']}" if "price_gems" in item else f"{u.CURRENCY} {u.fmt(item['price'])}"
            embed.add_field(name=f"{u.rarity_emoji(item['rarity'])} {item['emoji']} {item['name']}", value=f"`{key}` — {price}", inline=True)
        return embed

    async def _shop(self, ctx, category: str = "tool"):
        category = (category or "tool").lower()
        if category not in ["tool", "seed", "consumable", "egg", "title"]:
            await u.reply(ctx, embed=discord.Embed(title="🚫 Unknown category", description="Use: `tool`, `seed`, `consumable`, `egg`, `title`.", color=0xE11D48))
            return
        await u.reply(ctx, embed=self._shop_embed(category))

    @commands.command(name="shop", aliases=["store"], help="Browse the shop. Categories: tool, seed, consumable, egg, title.", usage="b.shop [category]")
    async def shop(self, ctx, category: str = "tool"):
        await self._shop(ctx, category)

    @app_commands.command(name="shop", description="Browse the shop.")
    @app_commands.describe(category="tool, seed, consumable, egg, or title")
    async def slash_shop(self, interaction: discord.Interaction, category: str = "tool"):
        await self._shop(interaction, category)

    # ------------------------------------------------------------- buy

    async def _buy(self, ctx, item_key: str, qty: int = 1):
        item = config.ITEMS.get(item_key.lower())
        user_id = u.user_id_of(ctx)
        if not item:
            await u.reply(ctx, embed=discord.Embed(title="🚫 Unknown item", description=f"Try `/shop` to see items. You said `{item_key}`.", color=0xE11D48))
            return
        if "price" not in item and "price_gems" not in item:
            await u.reply(ctx, embed=discord.Embed(title="🚫 Not for sale", description="That item can't be bought from the shop.", color=0xE11D48))
            return
        if item["cat"] == "tool":
            qty = 1
        if qty < 1 or qty > 100:
            await u.reply(ctx, embed=discord.Embed(title="🚫 Quantity", description="Quantity must be between 1 and 100.", color=0xE11D48))
            return
        try:
            if "price_gems" in item:
                await self.db.try_remove_gems(user_id, item["price_gems"] * qty, note=f"Bought {item['name']}")
            else:
                await self.db.try_remove_coins(user_id, item["price"] * qty, note=f"Bought {item['name']}")
        except dbm.InsufficientFunds:
            await u.reply(ctx, embed=discord.Embed(title="🚫 Insufficient funds", description="You can't afford that.", color=0xE11D48))
            return
        if item["cat"] == "tool":
            await self.db.add_tool(user_id, item_key.lower(), item["durability"])
            await self.db.bump_stat(user_id, "items_bought", 1)
            await self.db.log_tx(user_id, "buy", -item["price"], item_key=item_key, note=f"Bought {item['name']}")
            await u.reply(ctx, embed=discord.Embed(title="🛒 Purchase complete", description=f"Bought **{item['emoji']} {item['name']}** (full durability).", color=0x22C55E))
            return
        await self.db.add_item(user_id, item_key.lower(), qty)
        await self.db.bump_stat(user_id, "items_bought", qty)
        await u.reply(ctx, embed=discord.Embed(title="🛒 Purchase complete", description=f"Bought **{item['emoji']} {item['name']}** ×{qty}.", color=0x22C55E))

    @commands.command(name="buy", help="Purchase items from the shop.", usage="b.buy <item_key> [qty]")
    async def buy(self, ctx, item_key: str, qty: int = 1):
        await self._buy(ctx, item_key, qty)

    @app_commands.command(name="buy", description="Purchase items from the shop.")
    @app_commands.describe(item_key="Item key from /shop", qty="How many")
    async def slash_buy(self, interaction: discord.Interaction, item_key: str, qty: int = 1):
        await self._buy(interaction, item_key, qty)

    # ------------------------------------------------------------- sell

    async def _sell(self, ctx, item_key: str, qty: int = 1):
        item = config.ITEMS.get(item_key.lower())
        user_id = u.user_id_of(ctx)
        if not item:
            await u.reply(ctx, embed=discord.Embed(title="🚫 Unknown item", description=f"I don't know a `{item_key}`.", color=0xE11D48))
            return
        if qty < 1 or qty > 1000:
            await u.reply(ctx, embed=discord.Embed(title="🚫 Quantity", description="Quantity must be between 1 and 1000.", color=0xE11D48))
            return
        sell_price = item.get("sell", 0)
        if sell_price <= 0:
            await u.reply(ctx, embed=discord.Embed(title="🚫 Not sellable", description="The shop refuses to buy this. Some things are priceless.", color=0xE11D48))
            return
        if item["cat"] == "tool":
            tools = await self.db.get_tools(user_id)
            mine = [t for t in tools if t["tool_key"] == item_key.lower()]
            if not mine:
                await u.reply(ctx, embed=discord.Embed(title="🚫 Nothing to sell", description=f"You don't own **{item['name']}**.", color=0xE11D48))
                return
            tool = mine[0]
            await self.db.remove_tool(tool["id"])
            payout = int(item["price"] * 0.4)
            await self.db.try_add_coins(user_id, payout, note=f"Sold {item['name']}")
            await self.db.bump_stat(user_id, "items_sold", 1)
            await u.reply(ctx, embed=discord.Embed(title="💰 Sold!", description=f"Traded in **{item['emoji']} {item['name']}** for {u.CURRENCY} **{u.fmt(payout)}**.", color=0x22C55E))
            return
        if not await self.db.remove_item(user_id, item_key.lower(), qty):
            await u.reply(ctx, embed=discord.Embed(title="🚫 Nothing to sell", description=f"You only own {u.fmt(await self.db.item_count(user_id, item_key.lower()))} **{item['name']}**.", color=0xE11D48))
            return
        payout = sell_price * qty
        await self.db.try_add_coins(user_id, payout, note=f"Sold {item['name']} ×{qty}")
        await self.db.bump_stat(user_id, "items_sold", qty)
        await u.track_activity(self.db, user_id, "sell", qty)
        await u.reply(ctx, embed=discord.Embed(title="💰 Sold!", description=f"Sold **{item['emoji']} {item['name']}** ×{qty} for {u.CURRENCY} **{u.fmt(payout)}**.", color=0x22C55E))

    @commands.command(name="sell", help="Sell items back to the shop.", usage="b.sell <item_key> [qty]")
    async def sell(self, ctx, item_key: str, qty: int = 1):
        await self._sell(ctx, item_key, qty)

    @app_commands.command(name="sell", description="Sell items back to the shop.")
    @app_commands.describe(item_key="Item key", qty="How many")
    async def slash_sell(self, interaction: discord.Interaction, item_key: str, qty: int = 1):
        await self._sell(interaction, item_key, qty)

    # ------------------------------------------------------------- use

    async def _use(self, ctx, item_key: str):
        item = config.ITEMS.get(item_key.lower())
        user_id = u.user_id_of(ctx)
        if not item or not item.get("usable"):
            await u.reply(ctx, embed=discord.Embed(title="🚫 Can't use that", description=f"`{item_key}` is not a usable item.", color=0xE11D48))
            return
        if not await self.db.remove_item(user_id, item_key.lower(), 1):
            await u.reply(ctx, embed=discord.Embed(title="🚫 Nothing to use", description=f"You don't own **{item['name']}**.", color=0xE11D48))
            return
        effect = item["effect"]
        text = ""
        if effect == "repair":
            await self.db.repair_tools(user_id, 50, 100)
            text = "🔧 All your tools are repaired by 50 durability."
        elif effect == "xp":
            levels = await u.grant_xp(self.db, user_id, item["xp"])
            text = f"🧪 You drink the elixir and gain **{item['xp']} XP**." + (f" Level up! → **{levels[-1]}**" if levels else "")
        elif effect == "boost":
            await self.db.set_boost(user_id, item["boost"], item["duration"])
            name = "Luck Charm" if item["boost"] == "luck" else "Coin Magnet"
            text = f"🍀 {name} active for **30 minutes**."
        elif effect == "pet_food":
            user = await self.db.get_user(user_id)
            active = user.get("active_pet")
            if not active:
                text = "🦴 You try to feed a pet but you don't have one equipped. The treat stares back at you."
            else:
                lv = await self.db.pet_xp(user_id, active, item["xp"])
                pet = config.PETS[active]
                text = f"{pet['emoji']} {pet['name']} gobbles the treat (+{item['xp']} pet XP)." + (" It grew stronger! **Level up!**" if lv else "")
        elif effect == "egg":
            pool = item["pool"]
            pet_key = u.weighted_pick([(k, w) for k, w in config.PET_EGG_POOLS[pool].items()])
            pet = config.PETS[pet_key]
            new = await self.db.add_pet(user_id, pet_key)
            await self.db.bump_stat(user_id, "pets_adopted", 1)
            if new:
                text = f"{pet['emoji']} The egg hatches! You adopt **{pet['name']}** ({u.rarity_emoji(pet['rarity'])} {pet['rarity']})!"
            else:
                text = f"{pet['emoji']} The egg hatches... a duplicate **{pet['name']}**! It seems very familiar."
            user = await self.db.get_user(user_id)
            if not user.get("active_pet"):
                await self.db.execute("UPDATE users SET active_pet = ? WHERE user_id = ?", (pet_key, user_id))
        elif effect == "lottery":
            await self.db.add_item(user_id, "lottery_ticket", 1)
            await self.db.log_tx(user_id, "buy", -0, item_key="lottery_ticket", note="Refunded ticket")
            text = "🎟️ Lottery tickets are bought with `/lottery`. Your ticket was refunded."
        elif effect == "scratch":
            await self.db.add_item(user_id, "scratch_card", 1)
            text = "🎫 Scratch cards are used with `/scratch`. Your card was refunded."
        elif effect == "crystal_key":
            roll = random.random()
            if roll < 0.5:
                coins = random.randint(3000, 8000)
                await self.db.try_add_coins(user_id, coins, note="Crystal key treasure")
                text = f"🗝️ The Crystal Key unlocks a vault of memories! You find {u.CURRENCY} **{u.fmt(coins)}**."
            elif roll < 0.8:
                gems = random.randint(2, 6)
                await self.db.add_gems(user_id, gems, note="Crystal key treasure")
                text = f"🗝️ The Crystal Key opens a shimmering chest — **{gems} gems** tumble out!"
            else:
                item_k = u.weighted_pick([(k, w) for k, w in config.DIG_POOL])
                await self.db.add_item(user_id, item_k, 1)
                text = f"🗝️ The Crystal Key reveals a hidden compartment: {u.item_display(item_k, config.ITEMS[item_k])}!"
        await u.reply(ctx, embed=discord.Embed(title=f"{item['emoji']} {item['name']}", description=text, color=0x22C55E))

    @commands.command(name="use", help="Use a consumable item, tool, or booster.", usage="b.use <item_key>")
    async def use(self, ctx, item_key: str):
        await self._use(ctx, item_key)

    @app_commands.command(name="use", description="Use a consumable item, tool, or booster.")
    @app_commands.describe(item_key="Item key to use")
    async def slash_use(self, interaction: discord.Interaction, item_key: str):
        await self._use(interaction, item_key)


async def setup(bot: commands.Bot):
    await bot.add_cog(Profile(bot))
