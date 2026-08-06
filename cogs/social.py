"""Marketplace, trading, and crafting."""

import asyncio
import json
import random

import discord
from discord import app_commands
from discord.ext import commands

from economy import config, db as dbm, utils as u


class Social(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db: dbm.Database = bot.db

    # ------------------------------------------------------------- market

    async def _market(self, ctx):
        listings = await self.db.market_listings()
        if not listings:
            await u.reply(ctx, embed=discord.Embed(
                title="🏪 Player Market",
                description="Nothing is listed right now. List items with `/market list <item_key> <price> [qty]`.",
                color=config.BASE_COLOR,
            ))
            return
        embed = discord.Embed(title="🏪 Player Market", color=config.BASE_COLOR)
        lines = []
        for l in listings[:15]:
            item = config.ITEMS.get(l["item_key"], {})
            name = item.get("name", l["item_key"])
            emoji = item.get("emoji", "📦")
            lines.append(f"`#{l['id']}` {emoji} **{name}** ×{l['quantity']} — {u.CURRENCY} {u.fmt(l['price_per'])} each")
        embed.description = "\n".join(lines)
        embed.set_footer(text="Buy with the menu below, or /market buy <id> <qty>.")
        view = MarketView(self.db, u.user_id_of(ctx), listings[:25])
        await u.reply(ctx, embed=embed, view=view)

    async def _market_list(self, ctx, item_key: str, price: int, qty: int = 1):
        user_id = u.user_id_of(ctx)
        item = config.ITEMS.get(item_key.lower())
        if not item:
            await u.reply(ctx, embed=discord.Embed(title="🚫 Unknown item", color=0xE11D48))
            return
        if item["cat"] == "tool":
            await u.reply(ctx, embed=discord.Embed(title="🚫 Tools can't be listed", description="Tools are soulbound to their owner. Sell them at the shop instead.", color=0xE11D48))
            return
        if price < 1 or price > 10_000_000:
            await u.reply(ctx, embed=discord.Embed(title="🚫 Price", description="Price between 1 and 10,000,000 coins per unit.", color=0xE11D48))
            return
        if qty < 1 or qty > 100:
            await u.reply(ctx, embed=discord.Embed(title="🚫 Quantity", description="Quantity between 1 and 100.", color=0xE11D48))
            return
        if not await self.db.remove_item(user_id, item_key.lower(), qty):
            await u.reply(ctx, embed=discord.Embed(title="🚫 Not enough", description=f"You only own {u.fmt(await self.db.item_count(user_id, item_key.lower()))} **{item['name']}**.", color=0xE11D48))
            return
        await self.db.list_item(user_id, item_key.lower(), qty, price)
        await u.reply(ctx, embed=discord.Embed(
            title="📦 Listed!",
            description=f"Listed **{item['emoji']} {item['name']}** ×{qty} at {u.CURRENCY} **{u.fmt(price)}** each.",
            color=0x22C55E,
        ))

    async def _market_buy(self, ctx, listing_id: int, qty: int = 1):
        user_id = u.user_id_of(ctx)
        result = await self.db.market_buy(listing_id, user_id, qty)
        if result[0] == "gone":
            await u.reply(ctx, embed=discord.Embed(title="🚫 Listing gone", description="That listing was already bought out.", color=0xE11D48))
        elif result[0] == "short":
            await u.reply(ctx, embed=discord.Embed(title="🚫 Not enough stock", color=0xE11D48))
        elif result[0] == "funds":
            await u.reply(ctx, embed=discord.Embed(title="🚫 Insufficient funds", color=0xE11D48))
        else:
            _, listing, total = result
            item = config.ITEMS.get(listing["item_key"], {})
            await self.db.bump_stat(user_id, "items_bought", qty)
            await self.db.bump_stat(listing["seller_id"], "market_sold", 1)
            await u.reply(ctx, embed=discord.Embed(
                title="🛒 Purchased!",
                description=f"Bought **{item.get('emoji', '📦')} {item.get('name', listing['item_key'])}** ×{qty} for {u.CURRENCY} **{u.fmt(total)}**.",
                color=0x22C55E,
            ))

    async def _market_cancel(self, ctx, listing_id: int):
        user_id = u.user_id_of(ctx)
        if await self.db.market_cancel(listing_id, user_id):
            await u.reply(ctx, embed=discord.Embed(title="↩️ Unlisted", description="Items returned to your inventory.", color=0x22C55E))
        else:
            await u.reply(ctx, embed=discord.Embed(title="🚫 Can't cancel", description="Listing not found or not yours.", color=0xE11D48))

    @commands.command(name="market", help="Browse the player market.", usage="b.market")
    async def market(self, ctx):
        await self._market(ctx)

    @commands.command(name="marketlist", help="List an item for sale.", usage="b.marketlist <item_key> <price> [qty]")
    async def marketlist(self, ctx, item_key: str, price: int, qty: int = 1):
        await self._market_list(ctx, item_key, price, qty)

    @commands.command(name="marketbuy", help="Buy from a market listing.", usage="b.marketbuy <listing_id> [qty]")
    async def marketbuy(self, ctx, listing_id: int, qty: int = 1):
        await self._market_buy(ctx, listing_id, qty)

    @commands.command(name="marketcancel", help="Cancel one of your listings.", usage="b.marketcancel <listing_id>")
    async def marketcancel(self, ctx, listing_id: int):
        await self._market_cancel(ctx, listing_id)

    @app_commands.command(name="market", description="Browse the player market.")
    async def slash_market(self, interaction: discord.Interaction):
        await self._market(interaction)

    @app_commands.command(name="marketlist", description="List an item for sale.")
    @app_commands.describe(item_key="Item key", price="Price per unit", qty="How many to list")
    async def slash_marketlist(self, interaction: discord.Interaction, item_key: str, price: int, qty: int = 1):
        await self._market_list(interaction, item_key, price, qty)

    @app_commands.command(name="marketbuy", description="Buy from a market listing.")
    @app_commands.describe(listing_id="Listing ID", qty="How many to buy")
    async def slash_marketbuy(self, interaction: discord.Interaction, listing_id: int, qty: int = 1):
        await self._market_buy(interaction, listing_id, qty)

    @app_commands.command(name="marketcancel", description="Cancel one of your listings.")
    @app_commands.describe(listing_id="Listing ID")
    async def slash_marketcancel(self, interaction: discord.Interaction, listing_id: int):
        await self._market_cancel(interaction, listing_id)

    # ------------------------------------------------------------- trade

    async def _trade(self, ctx, member: discord.Member, coins: int = 0, items: str = None):
        user_id = u.user_id_of(ctx)
        if member.id == user_id or member.bot:
            await u.reply(ctx, embed=discord.Embed(title="🚫 Nope", description="You can only trade with other human players.", color=0xE11D48))
            return
        if coins < 0 or coins > 10_000_000:
            await u.reply(ctx, embed=discord.Embed(title="🚫 Amount", description="Coins between 0 and 10,000,000.", color=0xE11D48))
            return
        offer_items = {}
        if items:
            for key in [k.strip().lower() for k in items.split(",") if k.strip()]:
                if key not in config.ITEMS:
                    await u.reply(ctx, embed=discord.Embed(title="🚫 Unknown item", description=f"`{key}` isn't an item.", color=0xE11D48))
                    return
                offer_items[key] = offer_items.get(key, 0) + 1
            if len(offer_items) > 5:
                await u.reply(ctx, embed=discord.Embed(title="🚫 Too many items", description="Max 5 distinct item types per trade.", color=0xE11D48))
                return
        if coins == 0 and not offer_items:
            await u.reply(ctx, embed=discord.Embed(title="🚫 Empty offer", description="Offer coins, items, or both.", color=0xE11D48))
            return
        wallet = await self.db.wallet(user_id)
        if coins > wallet:
            await u.reply(ctx, embed=discord.Embed(title="🚫 Insufficient funds", description=f"Your wallet holds {u.fmt(wallet)} {u.CURRENCY}.", color=0xE11D48))
            return
        for key, qty in offer_items.items():
            have = await self.db.item_count(user_id, key)
            if have < qty:
                await u.reply(ctx, embed=discord.Embed(title="🚫 Not enough", description=f"You only own {u.fmt(have)} **{config.ITEMS[key]['name']}**.", color=0xE11D48))
                return
        # deduct immediately so the offer is locked (refunded on decline/timeout)
        await self.db.try_remove_coins(user_id, coins, note="Trade offer locked")
        for key, qty in offer_items.items():
            await self.db.remove_item(user_id, key, qty)
        view = TradeView(self.db, user_id, member.id, coins, offer_items)
        embed = discord.Embed(
            title="🤝 Trade offer",
            color=config.BASE_COLOR,
            description=f"{u.author_of(ctx).mention} offers {member.mention}:\n"
                        f"• {u.CURRENCY} **{u.fmt(coins)}**\n" +
                        "\n".join(f"• {u.item_display(k, config.ITEMS[k])} ×{q}" for k, q in offer_items.items()) +
                        f"\n\n{member.mention}, do you accept?"
        )
        await u.reply(ctx, embed=embed, view=view)

    @commands.command(name="trade", help="Securely trade coins and items with another player.", usage="b.trade <@user> [coins] [items]")
    async def trade(self, ctx, member: discord.Member, coins: int = 0, items: str = None):
        await self._trade(ctx, member, coins, items)

    @app_commands.command(name="trade", description="Securely trade coins and items with another player.")
    @app_commands.describe(member="Who you're trading with", coins="Coins to offer", items="Item keys, comma separated (max 5)")
    async def slash_trade(self, interaction: discord.Interaction, member: discord.Member, coins: int = 0, items: str = None):
        await self._trade(interaction, member, coins, items)

    # ------------------------------------------------------------- craft

    async def _craft(self, ctx, recipe_key: str = None):
        user_id = u.user_id_of(ctx)
        if not recipe_key:
            embed = discord.Embed(title="🔨 Crafting recipes", color=config.BASE_COLOR)
            for r in config.RECIPES:
                out = config.ITEMS[r["output"]]
                mats = ", ".join(f"{config.ITEMS[k]['emoji']} {config.ITEMS[k]['name']} ×{v}" for k, v in r["cost"].items())
                embed.add_field(name=f"{r['emoji']} {r['name']} → {out['emoji']} {out['name']} ×{r['qty']}", value=f"Mats: {mats}", inline=False)
            embed.set_footer(text="Craft with: /craft <recipe_key>")
            await u.reply(ctx, embed=embed)
            return
        recipe = next((r for r in config.RECIPES if r["key"] == recipe_key), None)
        if not recipe:
            await u.reply(ctx, embed=discord.Embed(title="🚫 Unknown recipe", description="Run `/craft` to see recipes.", color=0xE11D48))
            return
        for k, v in recipe["cost"].items():
            if await self.db.item_count(user_id, k) < v:
                await u.reply(ctx, embed=discord.Embed(title="🚫 Missing materials", description=f"You need **{config.ITEMS[k]['name']}** ×{v}.", color=0xE11D48))
                return
        if recipe.get("gems"):
            gems = await self.db.gems(user_id)
            if gems < recipe["gems"]:
                await u.reply(ctx, embed=discord.Embed(title="🚫 Not enough gems", description=f"This recipe costs {u.GEM} **{recipe['gems']}**.", color=0xE11D48))
                return
        for k, v in recipe["cost"].items():
            await self.db.remove_item(user_id, k, v)
        if recipe.get("gems"):
            await self.db.try_remove_gems(user_id, recipe["gems"], note=f"Crafted {recipe['name']}")
        await self.db.add_item(user_id, recipe["output"], recipe["qty"])
        await self.db.bump_stat(user_id, "items_crafted", 1)
        await u.track_activity(self.db, user_id, "craft", 1)
        levels = await u.grant_xp(self.db, user_id, recipe["xp"])
        out = config.ITEMS[recipe["output"]]
        embed = discord.Embed(title=f"🔨 Crafted!", color=0x22C55E,
                              description=f"You forged **{out['emoji']} {out['name']}** ×{recipe['qty']}!")
        if levels:
            embed.add_field(name="🎉 Level up!", value=f"Level **{levels[-1]}**!", inline=False)
        achievements = await u.check_achievements(self.db, user_id)
        for ach in achievements:
            embed.add_field(name=f"🏅 Achievement: {ach['name']}", value=ach["desc"], inline=False)
        await u.reply(ctx, embed=embed)

    @commands.command(name="craft", help="Craft items from collected resources.", usage="b.craft [recipe_key]")
    async def craft(self, ctx, recipe_key: str = None):
        await self._craft(ctx, recipe_key)

    @app_commands.command(name="craft", description="Craft items from collected resources.")
    @app_commands.describe(recipe_key="Recipe key (run /craft to see recipes)")
    async def slash_craft(self, interaction: discord.Interaction, recipe_key: str = None):
        await self._craft(interaction, recipe_key)


class MarketView(discord.ui.View):
    def __init__(self, db, user_id: int, listings: list):
        super().__init__(timeout=120)
        self.db = db
        self.user_id = user_id
        self.listings = listings
        options = []
        for l in listings:
            item = config.ITEMS.get(l["item_key"], {})
            options.append(discord.SelectOption(
                label=f"#{l['id']} {item.get('name', l['item_key'])[:40]}",
                value=str(l["id"]),
                description=f"×{l['quantity']} @ {u.CURRENCY} {l['price_per']} each",
                emoji=item.get("emoji", "📦"),
            ))
        select = discord.ui.Select(placeholder="📦 Choose a listing...", options=options[:25], custom_id="market_pick")
        select.callback = self._pick
        self.add_item(select)

    async def _pick(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not your session!", ephemeral=True)
            return
        listing_id = int(interaction.data["values"][0])
        result = await self.db.market_buy(listing_id, self.user_id, 1)
        if result[0] == "ok":
            _, listing, total = result
            item = config.ITEMS.get(listing["item_key"], {})
            await self.db.bump_stat(self.user_id, "items_bought", 1)
            await self.db.bump_stat(listing["seller_id"], "market_sold", 1)
            embed = discord.Embed(title="🛒 Purchased!",
                                  description=f"Bought **{item.get('emoji', '📦')} {item.get('name', listing['item_key'])}** for {u.CURRENCY} **{u.fmt(total)}**.",
                                  color=0x22C55E)
        elif result[0] == "funds":
            embed = discord.Embed(title="🚫 Insufficient funds", color=0xE11D48)
        else:
            embed = discord.Embed(title="🚫 Listing gone", color=0xE11D48)
        await interaction.response.edit_message(embed=embed, view=None)


class TradeView(discord.ui.View):
    def __init__(self, db, from_id: int, to_id: int, coins: int, items: dict):
        super().__init__(timeout=120)
        self.db = db
        self.from_id = from_id
        self.to_id = to_id
        self.coins = coins
        self.items = items
        self.accepted = set()
        self.settled = False
        a1 = discord.ui.Button(label="Accept", style=discord.ButtonStyle.success, emoji="✅", custom_id="trade_a1")
        a1.callback = self._make_accept(from_id)
        a2 = discord.ui.Button(label="Accept", style=discord.ButtonStyle.success, emoji="✅", custom_id="trade_a2")
        a2.callback = self._make_accept(to_id)
        d1 = discord.ui.Button(label="Decline", style=discord.ButtonStyle.danger, emoji="❌", custom_id="trade_d1")
        d1.callback = self._make_decline()
        self.add_item(a1)
        self.add_item(a2)
        self.add_item(d1)

    def _make_accept(self, user_id: int):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != user_id:
                await interaction.response.send_message("Not your offer!", ephemeral=True)
                return
            self.accepted.add(user_id)
            if len(self.accepted) == 2:
                await self._execute(interaction)
            else:
                await interaction.response.edit_message(content=f"✅ {interaction.user.mention} accepted. Waiting for the other party...", embed=None, view=None)
        return cb

    async def _make_decline(self):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id not in (self.from_id, self.to_id):
                await interaction.response.send_message("Not your offer!", ephemeral=True)
                return
            await self._refund()
            await interaction.response.edit_message(content="❌ Trade declined. Items returned.", embed=None, view=None)
        return cb

    async def _refund(self):
        if self.settled:
            return
        self.settled = True
        if self.coins:
            await self.db.try_add_coins(self.from_id, self.coins, note="Trade declined refund")
        for k, q in self.items.items():
            await self.db.add_item(self.from_id, k, q)

    async def _execute(self, interaction: discord.Interaction):
        if self.settled:
            return
        self.settled = True
        await self.db.try_add_coins(self.to_id, self.coins, note="Trade received")
        await self.db.log_tx(self.from_id, "trade", -self.coins, other_id=self.to_id, note="Trade sent")
        for k, q in self.items.items():
            await self.db.add_item(self.to_id, k, q)
            await self.db.log_tx(self.from_id, "trade", 0, item_key=k, other_id=self.to_id, note="Trade item sent")
        await self.db.bump_stat(self.from_id, "trades_done", 1)
        await self.db.bump_stat(self.to_id, "trades_done", 1)
        parts = [f"{u.CURRENCY} **{u.fmt(self.coins)}**"]
        parts += [f"{u.item_display(k, config.ITEMS[k])} ×{q}" for k, q in self.items.items()]
        embed = discord.Embed(title="🤝 Trade completed!", color=0x22C55E,
                              description=f"<@{self.from_id}> → <@{self.to_id}>:\n" + "\n".join(parts))
        await interaction.response.edit_message(embed=embed, view=None)

    async def on_timeout(self):
        await self._refund()


async def setup(bot: commands.Bot):
    await bot.add_cog(Social(bot))
