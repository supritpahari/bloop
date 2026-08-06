"""Gambling commands: coinflip, dice, slots, blackjack, roulette, lottery, scratch, wheel."""

import asyncio
import random
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from economy import config, db as dbm, utils as u


class Gambling(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db: dbm.Database = bot.db

    # ------------------------------------------------------------- shared helpers

    async def _start_gamble(self, ctx, amount: int, min_bet: int, max_bet: int, name: str):
        """Validate + set gamble cooldown. Returns user_id or None."""
        user_id = u.user_id_of(ctx)
        if await u.check_cooldown(self.db, ctx, "gamble", config.GAMBLE_COOLDOWN, "gamble again"):
            return None
        if amount < min_bet or amount > max_bet:
            await u.reply(ctx, embed=discord.Embed(
                title="🚫 Invalid bet",
                description=f"Bet between {u.CURRENCY} **{u.fmt(min_bet)}** and {u.CURRENCY} **{u.fmt(max_bet)}** for {name}.",
                color=0xE11D48,
            ))
            return None
        wallet = await self.db.wallet(user_id)
        if wallet < amount:
            await u.reply(ctx, embed=discord.Embed(
                title="🚫 Insufficient funds",
                description=f"Your wallet holds {u.CURRENCY} **{u.fmt(wallet)}**. This bet needs {u.fmt(amount)}.",
                color=0xE11D48,
            ))
            return None
        await self.db.try_remove_coins(user_id, amount, note=f"{name} bet")
        await self.db.bump_stat(user_id, "gambled_total", amount)
        return user_id

    async def _payout(self, user_id: int, amount: int, name: str):
        await self.db.try_add_coins(user_id, amount, note=f"{name} payout")

    # ------------------------------------------------------------- coinflip

    async def _coinflip(self, ctx, choice: str, amount: int):
        choice = choice.lower()
        if choice not in ("heads", "tails", "h", "t"):
            await u.reply(ctx, embed=discord.Embed(title="🚫 Invalid choice", description="Pick `heads` or `tails`.", color=0xE11D48))
            return
        user_id = await self._start_gamble(ctx, amount, config.COINFLIP_MIN, config.COINFLIP_MAX, "Coin flip")
        if user_id is None:
            return
        result = random.choice(("heads", "tails"))
        picked = "heads" if choice in ("h", "heads") else "tails"
        correct = picked == result
        won = correct and random.random() < 0.99
        if won:
            payout = amount * 2
            await self._payout(user_id, payout, "Coin flip")
            await u.track_gamble(self.db, user_id, True, amount)
            embed = discord.Embed(title="🪙 Coin Flip", color=0x22C55E,
                                  description=f"The coin lands on **{result}**! You won {u.CURRENCY} **{u.fmt(payout)}**!")
        else:
            await u.track_gamble(self.db, user_id, False, -amount)
            embed = discord.Embed(title="🪙 Coin Flip", color=0xE11D48,
                                  description=f"The coin lands on **{result}** ({'wrong call' if not correct else 'the edge cuts against you'}). Your {u.CURRENCY} **{u.fmt(amount)}** is gone with the wind.")
        embed.set_footer(text=f"You bet on: {picked}")
        await u.reply(ctx, embed=embed)

    @commands.command(name="coinflip", aliases=["cf"], help="Flip a coin. Heads or tails.", usage="b.coinflip <heads|tails> <amount>")
    async def coinflip(self, ctx, choice: str, amount: int):
        await self._coinflip(ctx, choice, amount)

    @app_commands.command(name="coinflip", description="Flip a coin. Heads or tails.")
    @app_commands.describe(choice="Heads or tails", amount="How much to bet")
    async def slash_coinflip(self, interaction: discord.Interaction, choice: str, amount: int):
        await self._coinflip(interaction, choice, amount)

    # ------------------------------------------------------------- dice

    async def _dice(self, ctx, bet_type: str, amount: int):
        bet_type = bet_type.lower()
        if bet_type not in ("over", "under", "seven", "7"):
            await u.reply(ctx, embed=discord.Embed(title="🚫 Invalid bet", description="Choose `over`, `under`, or `seven` (two dice).", color=0xE11D48))
            return
        user_id = await self._start_gamble(ctx, amount, config.DICE_MIN, config.DICE_MAX, "Dice")
        if user_id is None:
            return
        d1, d2 = random.randint(1, 6), random.randint(1, 6)
        total = d1 + d2
        pay_mult = {"over": 1.9, "under": 1.9, "seven": 5.5, "7": 5.5}[bet_type]
        result_ok = (total > 7) if bet_type == "over" else (total < 7) if bet_type == "under" else (total == 7)
        embed = discord.Embed(title="🎲 Dice", color=0x22C55E if result_ok else 0xE11D48)
        embed.description = f"You rolled **{d1}** + **{d2}** = **{total}**"
        if result_ok:
            payout = int(amount * pay_mult)
            await self._payout(user_id, payout, "Dice")
            await u.track_gamble(self.db, user_id, True, payout - amount)
            embed.description += f"\n\nBet **{bet_type}** hits! You win {u.CURRENCY} **{u.fmt(payout)}**!"
        else:
            await u.track_gamble(self.db, user_id, False, -amount)
            embed.description += f"\n\nBet **{bet_type}** misses. The dice don't care about feelings."
        await u.reply(ctx, embed=embed)

    @commands.command(name="dice", help="Roll two dice. Bet on over, under, or seven.", usage="b.dice <over|under|seven> <amount>")
    async def dice(self, ctx, bet_type: str, amount: int):
        await self._dice(ctx, bet_type, amount)

    @app_commands.command(name="dice", description="Roll two dice. Bet on over, under, or seven.")
    @app_commands.describe(bet_type="over, under, or seven", amount="How much to bet")
    async def slash_dice(self, interaction: discord.Interaction, bet_type: str, amount: int):
        await self._dice(interaction, bet_type, amount)

    # ------------------------------------------------------------- slots

    async def _slots(self, ctx, amount: int):
        user_id = await self._start_gamble(ctx, amount, config.SLOTS_MIN, config.SLOTS_MAX, "Slots")
        if user_id is None:
            return
        symbols = config.SLOT_SYMBOLS
        grid = [u.weighted_pick([(s["emoji"], s["weight"]) for s in symbols]) for _ in range(9)]
        best_payout = 0
        hits = []
        for line in config.SLOT_LINES:
            emojis = [grid[i] for i in line]
            if len(set(emojis)) == 1:
                sym = next(s for s in symbols if s["emoji"] == emojis[0])
                payout = sym["payout"] * amount
                if payout > best_payout:
                    best_payout = payout
                hits.append(f"{sym['emoji']} ×{sym['payout']}")
        rows = ["".join(grid[0:3]), "".join(grid[3:6]), "".join(grid[6:9])]
        embed = discord.Embed(title="🎰 Slots", color=0x22C55E if best_payout else 0xE11D48)
        embed.description = "```\n" + "\n".join(rows) + "\n```"
        if best_payout:
            await self._payout(user_id, best_payout, "Slots")
            await u.track_gamble(self.db, user_id, True, best_payout - amount)
            embed.add_field(name="🎉 Jackpot line!", value=f"You win {u.CURRENCY} **{u.fmt(best_payout)}** ({', '.join(hits)})!")
        else:
            await u.track_gamble(self.db, user_id, False, -amount)
            embed.add_field(name="No line", value="The reels laugh at you softly.")
        embed.set_footer(text="Lines: rows, diagonals. Same symbol pays.")
        await u.reply(ctx, embed=embed)

    @commands.command(name="slots", aliases=["spin"], help="Spin the slot machine.", usage="b.slots <amount>")
    async def slots(self, ctx, amount: int):
        await self._slots(ctx, amount)

    @app_commands.command(name="slots", description="Spin the slot machine.")
    @app_commands.describe(amount="How much to bet")
    async def slash_slots(self, interaction: discord.Interaction, amount: int):
        await self._slots(interaction, amount)

    # ------------------------------------------------------------- blackjack

    async def _blackjack(self, ctx, amount: int):
        user_id = await self._start_gamble(ctx, amount, config.BJ_MIN, config.BJ_MAX, "Blackjack")
        if user_id is None:
            return
        game = BlackjackGame(self.db, user_id, amount)
        view = BlackjackView(self.db, user_id, game)
        await u.reply(ctx, embed=game.render(False), view=view)

    @commands.command(name="blackjack", aliases=["bj"], help="Play blackjack against the dealer.", usage="b.blackjack <amount>")
    async def blackjack(self, ctx, amount: int):
        await self._blackjack(ctx, amount)

    @app_commands.command(name="blackjack", description="Play blackjack against the dealer.")
    @app_commands.describe(amount="How much to bet")
    async def slash_blackjack(self, interaction: discord.Interaction, amount: int):
        await self._blackjack(interaction, amount)

    # ------------------------------------------------------------- roulette

    async def _roulette(self, ctx, amount: int, bet_type: str = None, value: str = None):
        user_id = await self._start_gamble(ctx, amount, config.ROULETTE_MIN, config.ROULETTE_MAX, "Roulette")
        if user_id is None:
            return
        bet_type = (bet_type or "").lower()
        value = (value or "").lower()
        if bet_type not in ("number", "color", "parity", "range", "dozen") or not value:
            view = RouletteView(self.db, user_id, amount)
            await u.reply(ctx, embed=discord.Embed(
                title="🎡 Roulette",
                description=f"Pick your bet ({u.CURRENCY} **{u.fmt(amount)}** on the line).",
                color=config.BASE_COLOR,
            ), view=view)
            return
        number = random.randint(0, 36)
        red = number in config.ROULETTE_REDS and number != 0
        color = "red" if red else "black" if number != 0 else "green"
        result_ok = False
        if bet_type == "number":
            try:
                result_ok = int(value) == number
            except ValueError:
                result_ok = False
        elif bet_type == "color":
            result_ok = color == value
        elif bet_type == "parity":
            result_ok = number != 0 and value in ("odd", "even") and (value == "odd") == (number % 2 == 1)
        elif bet_type == "range":
            result_ok = (value == "low" and 1 <= number <= 18) or (value == "high" and 19 <= number <= 36)
        elif bet_type == "dozen":
            try:
                d = int(value)
                result_ok = 1 <= d <= 3 and (d - 1) * 12 + 1 <= number <= d * 12
            except ValueError:
                result_ok = False
        mult = {"number": 36, "color": 2, "parity": 2, "range": 2, "dozen": 3}[bet_type]
        embed = discord.Embed(title="🎡 Roulette", color=0x22C55E if result_ok else 0xE11D48)
        embed.description = f"The ball lands on **{number}** ({color})."
        if result_ok:
            payout = amount * mult
            await self._payout(user_id, payout, "Roulette")
            await u.track_gamble(self.db, user_id, True, payout - amount)
            embed.description += f"\n\nBet **{value}** hits ({mult}×)! You win {u.CURRENCY} **{u.fmt(payout)}**!"
        else:
            await u.track_gamble(self.db, user_id, False, -amount)
            embed.description += f"\n\nBet **{value}** misses. The ball has no favourites."
        await u.reply(ctx, embed=embed)

    @commands.command(name="roulette", aliases=["wheel2"], help="Bet on roulette. Types: number 0-36, color red/black, parity odd/even, range low/high, dozen 1-3.", usage="b.roulette <amount> [type] [value]")
    async def roulette(self, ctx, amount: int, bet_type: str = None, value: str = None):
        await self._roulette(ctx, amount, bet_type, value)

    @app_commands.command(name="roulette", description="Bet on roulette. Types: number 0-36, color, parity, range, dozen.")
    @app_commands.describe(amount="How much to bet", bet_type="number, color, parity, range, or dozen", value="The bet value")
    async def slash_roulette(self, interaction: discord.Interaction, amount: int, bet_type: str = None, value: str = None):
        await self._roulette(interaction, amount, bet_type, value)

    # ------------------------------------------------------------- lottery

    async def _maybe_draw(self) -> dict | None:
        next_draw = await self.db.lottery_next_draw()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        if next_draw and next_draw > now:
            return None
        entries = await self.db.lottery_entries()
        pool = await self.db.lottery_pool()
        win_num = random.randint(0, 999)
        winners = {}
        for e in entries:
            if e["number"] == win_num:
                winners[e["user_id"]] = winners.get(e["user_id"], 0) + e["tickets"]
        prize_pool = int(pool * config.LOTTERY_POOL_PERCENT)
        total_tickets = sum(winners.values())
        for uid, tickets in winners.items():
            share = int(prize_pool * tickets / total_tickets) if total_tickets else 0
            await self.db.try_add_coins(uid, share, "Lottery win")
            await self.db.bump_stat(uid, "lottery_wins", 1)
        rollover = pool - prize_pool if winners else pool
        await self.db.lottery_clear()
        next_draw_str = (datetime.now(timezone.utc) + timedelta(hours=config.LOTTERY_DRAW_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
        await self.db.lottery_update(rollover, next_draw_str)
        return {"num": win_num, "winners": len(winners), "prize": prize_pool, "rollover": rollover, "total_tickets": total_tickets}

    async def _lottery(self, ctx):
        draw = await self._maybe_draw()
        pool = await self.db.lottery_pool()
        next_draw = await self.db.lottery_next_draw()
        user_id = u.user_id_of(ctx)
        tickets = await self.db.fetchall("SELECT number, tickets FROM lottery_entries WHERE user_id = ?", (user_id,))
        embed = discord.Embed(title="🎟️ Bloop Lottery", color=0xF59E0B)
        desc = f"**Prize pool:** {u.CURRENCY} **{u.fmt(pool)}**\n**Next draw:** <t:{int(datetime.strptime(next_draw, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp())}:R>\n\n"
        desc += f"Tickets cost {u.CURRENCY} **{config.LOTTERY_TICKET_PRICE}** each. Pick a number from **000** to **999** — exact match wins a share of the pool!\n\n"
        desc += "**Your tickets:**\n" if tickets else "You have no tickets. Buy one with `/lottery buy <number> [qty]`."
        for row in tickets:
            desc += f"• `{row['number']:03d}` ×{row['tickets']}\n"
        embed.description = desc
        if draw:
            embed.add_field(name="📢 Previous draw", value=f"Number **{draw['num']:03d}** — {draw['winners']} winner(s), prize {u.CURRENCY} {u.fmt(draw['prize'])}. {u.CURRENCY} {u.fmt(draw['rollover'])} rolled over.", inline=False)
        await u.reply(ctx, embed=embed)

    async def _lottery_buy(self, ctx, number: int, qty: int = 1):
        user_id = u.user_id_of(ctx)
        await self._maybe_draw()
        if number < 0 or number > 999:
            await u.reply(ctx, embed=discord.Embed(title="🚫 Invalid number", description="Pick a number between 000 and 999.", color=0xE11D48))
            return
        if qty < 1 or qty > 10:
            await u.reply(ctx, embed=discord.Embed(title="🚫 Quantity", description="Buy between 1 and 10 tickets at a time.", color=0xE11D48))
            return
        cost = config.LOTTERY_TICKET_PRICE * qty
        wallet = await self.db.wallet(user_id)
        if wallet < cost:
            await u.reply(ctx, embed=discord.Embed(title="🚫 Insufficient funds", description=f"Tickets cost {u.CURRENCY} **{u.fmt(cost)}**.", color=0xE11D48))
            return
        await self.db.try_remove_coins(user_id, cost, note="Lottery tickets")
        await self.db.lottery_buy(user_id, number, qty)
        await self.db.bump_stat(user_id, "lottery_tickets", qty)
        pool = await self.db.lottery_pool()
        await self.db.lottery_update(pool + cost, await self.db.lottery_next_draw())
        embed = discord.Embed(title="🎟️ Tickets bought!", color=0x22C55E)
        embed.description = f"Bought **{qty}** ticket(s) for number **{number:03d}**. Good luck!"
        embed.set_footer(text="Draw happens every 24h. Exact matches split the pool.")
        await u.reply(ctx, embed=embed)

    @commands.command(name="lottery", help="Check lottery status and pool.", usage="b.lottery")
    async def lottery(self, ctx):
        await self._lottery(ctx)

    @commands.command(name="lotterybuy", help="Buy lottery tickets for a 3-digit number.", usage="b.lotterybuy <number> [qty]")
    async def lotterybuy(self, ctx, number: int, qty: int = 1):
        await self._lottery_buy(ctx, number, qty)

    @app_commands.command(name="lottery", description="Check lottery status and pool.")
    async def slash_lottery(self, interaction: discord.Interaction):
        await self._lottery(interaction)

    @app_commands.command(name="lotterybuy", description="Buy lottery tickets for a 3-digit number.")
    @app_commands.describe(number="Number from 000 to 999", qty="How many tickets")
    async def slash_lotterybuy(self, interaction: discord.Interaction, number: int, qty: int = 1):
        await self._lottery_buy(interaction, number, qty)

    # ------------------------------------------------------------- scratch

    async def _scratch(self, ctx):
        user_id = u.user_id_of(ctx)
        if await u.check_cooldown(self.db, ctx, "scratch", config.GAMBLE_COOLDOWN, "scratch again"):
            return
        wallet = await self.db.wallet(user_id)
        if wallet < config.SCRATCH_PRICE:
            await u.reply(ctx, embed=discord.Embed(title="🚫 Insufficient funds", description=f"Cards cost {u.CURRENCY} **{config.SCRATCH_PRICE}**.", color=0xE11D48))
            return
        await self.db.try_remove_coins(user_id, config.SCRATCH_PRICE, note="Scratch card")
        card = [u.weighted_pick([(s["emoji"], s["weight"]) for s in config.SCRATCH_SYMBOLS]) for _ in range(9)]
        view = ScratchView(self.db, user_id, card, config.SCRATCH_PRICE)
        await u.reply(ctx, embed=view.embed(), view=view)

    @commands.command(name="scratch", help="Buy and scratch a lottery-style card.", usage="b.scratch")
    async def scratch(self, ctx):
        await self._scratch(ctx)

    @app_commands.command(name="scratch", description="Buy and scratch a lottery-style card.")
    async def slash_scratch(self, interaction: discord.Interaction):
        await self._scratch(interaction)

    # ------------------------------------------------------------- wheel

    async def _wheel(self, ctx, amount: int):
        user_id = await self._start_gamble(ctx, amount, config.WHEEL_MIN, config.WHEEL_MAX, "Wheel of Fortune")
        if user_id is None:
            return
        view = WheelView(self.db, user_id, amount)
        await u.reply(ctx, embed=view.embed(0), view=view)

    @commands.command(name="wheel", help="Spin the Wheel of Fortune.", usage="b.wheel <amount>")
    async def wheel(self, ctx, amount: int):
        await self._wheel(ctx, amount)

    @app_commands.command(name="wheel", description="Spin the Wheel of Fortune.")
    @app_commands.describe(amount="How much to bet")
    async def slash_wheel(self, interaction: discord.Interaction, amount: int):
        await self._wheel(interaction, amount)


# --------------------------------------------------------------------------- blackjack

CARD_RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
CARD_SUITS = ["♠", "♥", "♦", "♣"]


def hand_value(cards) -> int:
    value = 0
    aces = 0
    for rank, _ in cards:
        if rank == "A":
            aces += 1
            value += 11
        elif rank in ("K", "Q", "J"):
            value += 10
        else:
            value += int(rank)
    while value > 21 and aces:
        value -= 10
        aces -= 1
    return value


def hand_display(cards) -> str:
    return " ".join(f"{rank}{suit}" for rank, suit in cards)


class BlackjackGame:
    def __init__(self, db, user_id: int, bet: int):
        self.db = db
        self.user_id = user_id
        self.bet = bet
        self.player = []
        self.dealer = []
        self.over = False

    def draw(self):
        return (random.choice(CARD_RANKS), random.choice(CARD_SUITS))

    def deal(self):
        self.player = [self.draw(), self.draw()]
        self.dealer = [self.draw()]

    def render(self, final: bool) -> discord.Embed:
        if final:
            p = hand_display(self.player)
            d = hand_display(self.dealer) + (f"  ({hand_value(self.dealer)})")
            color = 0x22C55E
        else:
            p = hand_display(self.player) + f"  ({hand_value(self.player)})"
            d = hand_display([self.dealer[0]]) + " ❓❓"
            color = config.BASE_COLOR
        embed = discord.Embed(title=f"🃏 Blackjack — bet {u.CURRENCY} {u.fmt(self.bet)}", color=color)
        embed.add_field(name="Dealer", value=d, inline=False)
        embed.add_field(name="You", value=p, inline=False)
        return embed

    async def finish(self, interaction: discord.Interaction, view) -> discord.Embed:
        """Run dealer draws and settle the bet."""
        while hand_value(self.dealer) < 17:
            self.dealer.append(self.draw())
        player_v = hand_value(self.player)
        dealer_v = hand_value(self.dealer)
        natural = len(self.player) == 2 and player_v == 21
        if player_v > 21:
            result, payout = "bust", 0
        elif dealer_v > 21:
            result, payout = "dealer_bust", self.bet * 2
        elif dealer_v == player_v:
            result, payout = "push", self.bet
        elif natural:
            result, payout = "blackjack", int(self.bet * 2.5)
        elif player_v > dealer_v:
            result, payout = "win", self.bet * 2
        else:
            result, payout = "loss", 0
        self.over = True
        if payout:
            await self.db.try_add_coins(self.user_id, payout, note="Blackjack payout")
        await u.track_gamble(self.db, self.user_id, payout > 0, payout - self.bet)
        msg = {
            "bust": "💥 Bust! You went over 21.",
            "dealer_bust": "🎉 The dealer busts! You win!",
            "push": "🤝 Push. Your bet returns.",
            "blackjack": "🌟 Natural blackjack! 3:2 payout!",
            "win": "🎉 You win!",
            "loss": "💀 The dealer wins.",
        }[result]
        embed = self.render(True)
        if payout > 0:
            text = f"{msg}\nYou take {u.CURRENCY} **{u.fmt(payout)}**."
        else:
            text = f"{msg}\nYou lose {u.CURRENCY} **{u.fmt(self.bet)}**."
        embed.add_field(name="Result", value=text, inline=False)
        for child in view.children:
            child.disabled = True
        return embed


class BlackjackView(discord.ui.View):
    def __init__(self, db, user_id: int, game: BlackjackGame):
        super().__init__(timeout=90)
        self.db = db
        self.user_id = user_id
        self.game = game
        game.deal()

        self.hit = discord.ui.Button(label="Hit", style=discord.ButtonStyle.success, emoji="🃏", custom_id="bj_hit")
        self.hit.callback = self._hit
        self.stand = discord.ui.Button(label="Stand", style=discord.ButtonStyle.danger, emoji="✋", custom_id="bj_stand")
        self.stand.callback = self._stand
        self.double = discord.ui.Button(label="Double", style=discord.ButtonStyle.blurple, emoji="2️⃣", custom_id="bj_double")
        self.double.callback = self._double
        self.add_item(self.hit)
        self.add_item(self.stand)
        self.add_item(self.double)

    async def _ensure(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your hand!", ephemeral=True)
            return False
        if self.game.over:
            return False
        return True

    async def _hit(self, interaction: discord.Interaction):
        if not await self._ensure(interaction):
            return
        self.game.player.append(self.game.draw())
        if hand_value(self.game.player) >= 21:
            embed = await self.game.finish(interaction, self)
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=self.game.render(False), view=self)

    async def _stand(self, interaction: discord.Interaction):
        if not await self._ensure(interaction):
            return
        embed = await self.game.finish(interaction, self)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _double(self, interaction: discord.Interaction):
        if not await self._ensure(interaction):
            return
        if len(self.game.player) != 2:
            await interaction.response.send_message("You can only double on your first two cards.", ephemeral=True)
            return
        wallet = await self.db.wallet(self.user_id)
        if wallet < self.game.bet:
            await interaction.response.send_message("You can't afford to double.", ephemeral=True)
            return
        await self.db.try_remove_coins(self.user_id, self.game.bet, note="Blackjack double")
        self.game.bet *= 2
        self.game.player.append(self.game.draw())
        embed = await self.game.finish(interaction, self)
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


# --------------------------------------------------------------------------- roulette view

class RouletteView(discord.ui.View):
    def __init__(self, db, user_id: int, amount: int):
        super().__init__(timeout=90)
        self.db = db
        self.user_id = user_id
        self.amount = amount
        select = discord.ui.Select(placeholder="🎯 Pick your bet...", options=[
            discord.SelectOption(label="Red", value="color:red", emoji="🔴"),
            discord.SelectOption(label="Black", value="color:black", emoji="⚫"),
            discord.SelectOption(label="Odd", value="parity:odd", emoji="🔢"),
            discord.SelectOption(label="Even", value="parity:even", emoji="🔢"),
            discord.SelectOption(label="Low 1-18", value="range:low", emoji="⬇️"),
            discord.SelectOption(label="High 19-36", value="range:high", emoji="⬆️"),
            discord.SelectOption(label="Dozen 1", value="dozen:1", emoji="1️⃣"),
            discord.SelectOption(label="Dozen 2", value="dozen:2", emoji="2️⃣"),
            discord.SelectOption(label="Dozen 3", value="dozen:3", emoji="3️⃣"),
            discord.SelectOption(label="Number 0", value="number:0", emoji="0️⃣"),
        ], custom_id="roulette_pick")
        select.callback = self._pick
        self.add_item(select)

    async def _pick(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your spin!", ephemeral=True)
            return
        bet_type, value = interaction.data["values"][0].split(":")
        number = random.randint(0, 36)
        red = number in config.ROULETTE_REDS and number != 0
        color = "red" if red else "black" if number != 0 else "green"
        result_ok = False
        if bet_type == "number":
            result_ok = number == int(value)
        elif bet_type == "color":
            result_ok = color == value
        elif bet_type == "parity":
            result_ok = number != 0 and (value == "odd") == (number % 2 == 1)
        elif bet_type == "range":
            result_ok = (value == "low" and 1 <= number <= 18) or (value == "high" and 19 <= number <= 36)
        elif bet_type == "dozen":
            d = int(value)
            result_ok = (d - 1) * 12 + 1 <= number <= d * 12
        mult = {"number": 36, "color": 2, "parity": 2, "range": 2, "dozen": 3}[bet_type]
        embed = discord.Embed(title="🎡 Roulette", color=0x22C55E if result_ok else 0xE11D48)
        embed.description = f"The ball lands on **{number}** ({color})."
        if result_ok:
            payout = self.amount * mult
            await self.db.try_add_coins(self.user_id, payout, note="Roulette payout")
            await u.track_gamble(self.db, self.user_id, True, payout - self.amount)
            embed.description += f"\n\nBet **{value}** hits ({mult}×)! You win {u.CURRENCY} **{u.fmt(payout)}**!"
        else:
            await u.track_gamble(self.db, self.user_id, False, -self.amount)
            embed.description += f"\n\nBet **{value}** misses. The ball has no favourites."
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)


# --------------------------------------------------------------------------- scratch view

class ScratchView(discord.ui.View):
    def __init__(self, db, user_id: int, card: list, price: int):
        super().__init__(timeout=120)
        self.db = db
        self.user_id = user_id
        self.card = card
        self.price = price
        self.revealed = [False] * 9
        self._build()

    def _build(self):
        self.clear_items()
        for i in range(9):
            button = discord.ui.Button(label="❓", style=discord.ButtonStyle.secondary, custom_id=f"scratch:{i}")
            button.callback = self._make_cb(i)
            self.add_item(button)
        reveal = discord.ui.Button(label="Scratch all", style=discord.ButtonStyle.blurple, emoji="💨", custom_id="scratch_all")
        reveal.callback = self._reveal_all
        self.add_item(reveal)

    def _payout(self) -> int:
        total = 0
        lines = [(0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6)]
        for a, b, c in lines:
            if self.card[a] == self.card[b] == self.card[c]:
                sym = next(s for s in config.SCRATCH_SYMBOLS if s["emoji"] == self.card[a])
                total += int(self.price * sym["mult"])
        return total

    def embed(self) -> discord.Embed:
        cells = []
        for i in range(9):
            cells.append(self.card[i] if self.revealed[i] else "❓")
        grid = "\n".join(" ".join(cells[i:i + 3]) for i in range(0, 9, 3))
        embed = discord.Embed(title="🎫 Scratch Card", color=0xF59E0B)
        embed.description = f"```\n{grid}\n```"
        embed.set_footer(text="Match 3 in a row! 🍀 x10 · 💎 x5 · ⭐ x2 · 🍒 x1.5")
        return embed

    def _make_cb(self, i: int):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("Not your card!", ephemeral=True)
                return
            if self.revealed[i]:
                await interaction.response.defer()
                return
            self.revealed[i] = True
            if all(self.revealed):
                await self._finish(interaction)
            else:
                await interaction.response.edit_message(embed=self.embed(), view=self)
        return cb

    async def _reveal_all(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not your card!", ephemeral=True)
            return
        self.revealed = [True] * 9
        await self._finish(interaction)

    async def _finish(self, interaction: discord.Interaction):
        payout = self._payout()
        embed = self.embed()
        if payout > 0:
            await self.db.try_add_coins(self.user_id, payout, note="Scratch card win")
            await u.track_gamble(self.db, self.user_id, True, payout - self.price)
            embed.color = 0x22C55E
            embed.add_field(name="🎉 Winner!", value=f"You win {u.CURRENCY} **{u.fmt(payout)}**!")
        else:
            await u.track_gamble(self.db, self.user_id, False, -self.price)
            embed.add_field(name="💩 Nothing", value="Not a single line. The card looks smug.")
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)


# --------------------------------------------------------------------------- wheel view

class WheelView(discord.ui.View):
    def __init__(self, db, user_id: int, amount: int):
        super().__init__(timeout=90)
        self.db = db
        self.user_id = user_id
        self.amount = amount
        self.spun = False
        spin = discord.ui.Button(label="Spin!", style=discord.ButtonStyle.success, emoji="🎡", custom_id="wheel_spin")
        spin.callback = self._spin
        self.add_item(spin)

    def embed(self, pointer: int) -> discord.Embed:
        segs = config.WHEEL_SEGMENTS
        shown = [segs[(pointer + i) % len(segs)] for i in range(5)]
        lines = ["        ▼"]
        for i, s in enumerate(shown):
            lines.append(f"[{s['label']}]" if i == 2 else f" {s['label']} ")
        embed = discord.Embed(title=f"🎡 Wheel of Fortune — {u.CURRENCY} {u.fmt(self.amount)}", color=config.BASE_COLOR)
        embed.description = "```" + "\n".join(lines) + "```"
        embed.set_footer(text="LOSE = lost · ½ = half back · 1× = push · GEMS = gems · JACKPOT = 25×")
        return embed

    async def _spin(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not your wheel!", ephemeral=True)
            return
        if self.spun:
            await interaction.response.defer()
            return
        self.spun = True
        spin = self.children[0]
        spin.disabled = True
        pointer = random.randint(0, len(config.WHEEL_SEGMENTS) - 1)
        await interaction.response.edit_message(embed=self.embed(pointer), view=self)
        for _ in range(5):
            await asyncio.sleep(0.6)
            pointer = (pointer + random.randint(1, 4)) % len(config.WHEEL_SEGMENTS)
            await interaction.edit_original_response(embed=self.embed(pointer), view=self)
        seg = config.WHEEL_SEGMENTS[pointer]
        embed = self.embed(pointer)
        if seg["kind"] == "lose":
            embed.color = 0xE11D48
            embed.add_field(name="💀 Ouch", value=f"You lose your {u.CURRENCY} **{u.fmt(self.amount)}** bet.", inline=False)
            await u.track_gamble(self.db, self.user_id, False, -self.amount)
        elif seg["kind"] == "half":
            back = self.amount // 2
            embed.color = 0xF59E0B
            embed.add_field(name="🫠 Half back", value=f"You recover {u.CURRENCY} **{u.fmt(back)}**.", inline=False)
            await self.db.try_add_coins(self.user_id, back, note="Wheel half-back")
            await u.track_gamble(self.db, self.user_id, False, -self.amount + back)
        elif seg["kind"] == "one":
            embed.color = 0x3B82F6
            embed.add_field(name="😐 Push", value="The wheel returns your bet. Thrilling.", inline=False)
            await self.db.try_add_coins(self.user_id, self.amount, note="Wheel push")
            await u.track_gamble(self.db, self.user_id, False, 0)
        elif seg["kind"] == "gems":
            embed.color = 0xA855F7
            await self.db.add_gems(self.user_id, seg["value"], note="Wheel gems")
            embed.add_field(name="💎 Gems!", value=f"You win **{seg['value']} gems**!", inline=False)
            await u.track_gamble(self.db, self.user_id, True, self.amount)
        else:
            payout = self.amount * seg["value"]
            embed.color = 0x22C55E
            embed.add_field(name=f"🎉 {seg['label']}!", value=f"You win {u.CURRENCY} **{u.fmt(payout)}**!", inline=False)
            await self.db.try_add_coins(self.user_id, payout, note="Wheel win")
            await u.track_gamble(self.db, self.user_id, True, payout - self.amount)
        await interaction.edit_original_response(embed=embed, view=self)


async def setup(bot: commands.Bot):
    await bot.add_cog(Gambling(bot))
