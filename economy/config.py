"""All game data for the Bloop economy. Every name, line and number is original."""

RARITY_ORDER = ["Common", "Rare", "Epic", "Legendary", "Mythic"]
RARITY_COLORS = {
    "Common": 0x9CA3AF,
    "Rare": 0x3B82F6,
    "Epic": 0xA855F7,
    "Legendary": 0xF59E0B,
    "Mythic": 0xEC4899,
}
RARITY_EMOJI = {
    "Common": "⚪",
    "Rare": "🔵",
    "Epic": "🟣",
    "Legendary": "🟠",
    "Mythic": "🔴",
}

BASE_COLOR = 0x4FD1C5  # Bloop teal

# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------
# cats: tool, consumable, seed, crop, fish, ore, animal, dig, collectible, egg, petfood, title, misc
ITEMS = {
    # Tools (single instance, track durability)
    "fishing_rod": {"name": "Fishing Rod", "rarity": "Common", "cat": "tool", "price": 500, "sell": 200, "emoji": "🎣", "durability": 100},
    "pickaxe": {"name": "Pickaxe", "rarity": "Common", "cat": "tool", "price": 800, "sell": 320, "emoji": "⛏️", "durability": 100},
    "shovel": {"name": "Shovel", "rarity": "Common", "cat": "tool", "price": 700, "sell": 280, "emoji": "🪏", "durability": 100},
    "hunting_bow": {"name": "Hunting Bow", "rarity": "Common", "cat": "tool", "price": 1000, "sell": 400, "emoji": "🏹", "durability": 100},

    # Consumables
    "repair_kit": {"name": "Repair Kit", "rarity": "Rare", "cat": "consumable", "price": 450, "sell": 110, "emoji": "🔧", "usable": True, "effect": "repair"},
    "xp_elixir": {"name": "XP Elixir", "rarity": "Rare", "cat": "consumable", "price": 700, "sell": 175, "emoji": "🧪", "usable": True, "effect": "xp", "xp": 200},
    "luck_charm": {"name": "Luck Charm", "rarity": "Epic", "cat": "consumable", "price": 1500, "sell": 375, "emoji": "🍀", "usable": True, "effect": "boost", "boost": "luck", "duration": 1800},
    "coin_magnet": {"name": "Coin Magnet", "rarity": "Epic", "cat": "consumable", "price": 2000, "sell": 500, "emoji": "🧲", "usable": True, "effect": "boost", "boost": "coins", "duration": 1800},
    "pet_treat": {"name": "Pet Treat", "rarity": "Common", "cat": "consumable", "price": 150, "sell": 40, "emoji": "🦴", "usable": True, "effect": "pet_food", "xp": 60},
    "lottery_ticket": {"name": "Lottery Ticket", "rarity": "Rare", "cat": "consumable", "price": 100, "sell": 0, "emoji": "🎟️", "usable": True, "effect": "lottery"},
    "scratch_card": {"name": "Scratch Card", "rarity": "Rare", "cat": "consumable", "price": 200, "sell": 0, "emoji": "🎫", "usable": True, "effect": "scratch"},

    # Seeds & crops
    "wheat_seed": {"name": "Wheat Seeds", "rarity": "Common", "cat": "seed", "price": 25, "sell": 0, "emoji": "🌱"},
    "carrot_seed": {"name": "Carrot Seeds", "rarity": "Common", "cat": "seed", "price": 50, "sell": 0, "emoji": "🌱"},
    "tomato_seed": {"name": "Tomato Seeds", "rarity": "Common", "cat": "seed", "price": 120, "sell": 0, "emoji": "🌱"},
    "pumpkin_seed": {"name": "Pumpkin Seeds", "rarity": "Rare", "cat": "seed", "price": 300, "sell": 0, "emoji": "🌱"},
    "melon_seed": {"name": "Golden Melon Seeds", "rarity": "Epic", "cat": "seed", "price": 1000, "sell": 0, "emoji": "🌱"},
    "orchid_seed": {"name": "Rare Orchid Seeds", "rarity": "Legendary", "cat": "seed", "price": 4000, "sell": 0, "emoji": "🌱"},
    "berry_seed": {"name": "Starlight Berry Seeds", "rarity": "Mythic", "cat": "seed", "price": 15000, "sell": 0, "emoji": "🌱"},

    "wheat": {"name": "Wheat", "rarity": "Common", "cat": "crop", "sell": 12, "emoji": "🌾"},
    "carrot": {"name": "Carrot", "rarity": "Common", "cat": "crop", "sell": 25, "emoji": "🥕"},
    "tomato": {"name": "Tomato", "rarity": "Common", "cat": "crop", "sell": 60, "emoji": "🍅"},
    "pumpkin": {"name": "Pumpkin", "rarity": "Rare", "cat": "crop", "sell": 150, "emoji": "🎃"},
    "golden_melon": {"name": "Golden Melon", "rarity": "Epic", "cat": "crop", "sell": 500, "emoji": "🍈"},
    "rare_orchid": {"name": "Rare Orchid", "rarity": "Legendary", "cat": "crop", "sell": 1200, "emoji": "🌸"},
    "starlight_berry": {"name": "Starlight Berry", "rarity": "Mythic", "cat": "crop", "sell": 3000, "emoji": "🫐"},

    # Fish
    "minnow": {"name": "Bloopminnow", "rarity": "Common", "cat": "fish", "sell": 12, "emoji": "🐟"},
    "silver_shimmer": {"name": "Silver Shimmer", "rarity": "Common", "cat": "fish", "sell": 20, "emoji": "🐠"},
    "river_ruffian": {"name": "River Ruffian", "rarity": "Common", "cat": "fish", "sell": 30, "emoji": "🐡"},
    "ember_carp": {"name": "Ember Carp", "rarity": "Rare", "cat": "fish", "sell": 60, "emoji": "🐟"},
    "moonlight_bass": {"name": "Moonlight Bass", "rarity": "Rare", "cat": "fish", "sell": 85, "emoji": "🎏"},
    "golden_grouper": {"name": "Golden Grouper", "rarity": "Epic", "cat": "fish", "sell": 150, "emoji": "🐠"},
    "stormfin": {"name": "Stormfin", "rarity": "Epic", "cat": "fish", "sell": 200, "emoji": "🐉"},
    "abyss_angler": {"name": "Abyss Angler", "rarity": "Legendary", "cat": "fish", "sell": 400, "emoji": "🦈"},
    "spectral_salmon": {"name": "Spectral Salmon", "rarity": "Legendary", "cat": "fish", "sell": 550, "emoji": "🐲"},
    "leviathan_scale": {"name": "Leviathan's Scale", "rarity": "Mythic", "cat": "fish", "sell": 1200, "emoji": "🐋"},
    "void_eel": {"name": "Void Eel", "rarity": "Mythic", "cat": "fish", "sell": 1500, "emoji": "🪼"},

    # Ores & minerals
    "pebble": {"name": "Pebble", "rarity": "Common", "cat": "ore", "sell": 5, "emoji": "🪨"},
    "copper_ore": {"name": "Copper Ore", "rarity": "Common", "cat": "ore", "sell": 15, "emoji": "🥉"},
    "iron_ore": {"name": "Iron Ore", "rarity": "Common", "cat": "ore", "sell": 30, "emoji": "⚙️"},
    "gold_ore": {"name": "Gold Ore", "rarity": "Rare", "cat": "ore", "sell": 120, "emoji": "🟨"},
    "amethyst": {"name": "Amethyst", "rarity": "Rare", "cat": "ore", "sell": 250, "emoji": "🟪"},
    "sapphire": {"name": "Sapphire", "rarity": "Epic", "cat": "ore", "sell": 450, "emoji": "🔷"},
    "ruby": {"name": "Ruby", "rarity": "Epic", "cat": "ore", "sell": 500, "emoji": "🔴"},
    "diamond": {"name": "Diamond", "rarity": "Legendary", "cat": "ore", "sell": 900, "emoji": "💎"},
    "starforged_ore": {"name": "Starforged Ore", "rarity": "Legendary", "cat": "ore", "sell": 1400, "emoji": "🌠"},
    "meteorite_shard": {"name": "Meteorite Shard", "rarity": "Mythic", "cat": "ore", "sell": 2500, "emoji": "☄️"},

    # Animals
    "rabbit_pelt": {"name": "Rabbit Pelt", "rarity": "Common", "cat": "animal", "sell": 25, "emoji": "🐇"},
    "fox_pelt": {"name": "Fox Pelt", "rarity": "Common", "cat": "animal", "sell": 45, "emoji": "🦊"},
    "deer_hide": {"name": "Deer Hide", "rarity": "Common", "cat": "animal", "sell": 70, "emoji": "🦌"},
    "boar_tusk": {"name": "Boar Tusk", "rarity": "Rare", "cat": "animal", "sell": 90, "emoji": "🐗"},
    "wolf_pelt": {"name": "Wolf Pelt", "rarity": "Rare", "cat": "animal", "sell": 150, "emoji": "🐺"},
    "bear_paw": {"name": "Bear Claw", "rarity": "Epic", "cat": "animal", "sell": 260, "emoji": "🐻"},
    "panther_pelt": {"name": "Panther Pelt", "rarity": "Epic", "cat": "animal", "sell": 420, "emoji": "🐆"},
    "dragonhawk_feather": {"name": "Dragonhawk Feather", "rarity": "Legendary", "cat": "animal", "sell": 800, "emoji": "🦅"},
    "yeti_fur": {"name": "Yeti Fur", "rarity": "Legendary", "cat": "animal", "sell": 1100, "emoji": "❄️"},
    "phoenix_plume": {"name": "Phoenix Plume", "rarity": "Mythic", "cat": "animal", "sell": 2000, "emoji": "🔥"},

    # Dig finds
    "rusty_coin": {"name": "Rusty Coin", "rarity": "Common", "cat": "dig", "sell": 15, "emoji": "🪙"},
    "old_boot": {"name": "Mud-Caked Boot", "rarity": "Common", "cat": "dig", "sell": 5, "emoji": "🥾"},
    "clay_pot": {"name": "Clay Pot", "rarity": "Common", "cat": "dig", "sell": 40, "emoji": "🏺"},
    "ancient_coin": {"name": "Ancient Coin", "rarity": "Rare", "cat": "dig", "sell": 120, "emoji": "🪙"},
    "fossil_fragment": {"name": "Fossil Fragment", "rarity": "Rare", "cat": "dig", "sell": 180, "emoji": "🦴"},
    "dino_tooth": {"name": "Dinosaur Tooth", "rarity": "Epic", "cat": "dig", "sell": 350, "emoji": "🦖"},
    "golden_idol": {"name": "Golden Idol", "rarity": "Legendary", "cat": "dig", "sell": 700, "emoji": "🗿"},
    "bloopian_relic": {"name": "Bloopian Relic", "rarity": "Legendary", "cat": "dig", "sell": 900, "emoji": "📜"},
    "crystal_skull": {"name": "Crystal Skull", "rarity": "Mythic", "cat": "dig", "sell": 1500, "emoji": "💀"},

    # Collectibles (not sold in shop; found or crafted)
    "comet_dust": {"name": "Comet Dust", "rarity": "Rare", "cat": "collectible", "sell": 60, "emoji": "✨"},
    "lucky_horseshoe": {"name": "Lucky Horseshoe", "rarity": "Epic", "cat": "collectible", "sell": 300, "emoji": "🧲"},
    "gold_ticket": {"name": "Gold Ticket", "rarity": "Epic", "cat": "collectible", "sell": 400, "emoji": "🎫"},
    "ancient_tablet": {"name": "Ancient Tablet", "rarity": "Legendary", "cat": "collectible", "sell": 1000, "emoji": "🪦"},
    "bloopian_crown": {"name": "Bloopian Crown", "rarity": "Mythic", "cat": "collectible", "sell": 0, "emoji": "👑"},
    "prestige_medallion": {"name": "Prestige Medallion", "rarity": "Mythic", "cat": "collectible", "sell": 0, "emoji": "🏅"},
    "crystal_key": {"name": "Crystal Key", "rarity": "Legendary", "cat": "collectible", "sell": 0, "emoji": "🗝️", "usable": True, "effect": "crystal_key"},

    # Pet eggs
    "pet_egg_common": {"name": "Common Pet Egg", "rarity": "Common", "cat": "egg", "price": 1500, "sell": 0, "emoji": "🥚", "usable": True, "effect": "egg", "pool": "common"},
    "pet_egg_rare": {"name": "Rare Pet Egg", "rarity": "Rare", "cat": "egg", "price": 4500, "sell": 0, "emoji": "🥚", "usable": True, "effect": "egg", "pool": "rare"},
    "pet_egg_epic": {"name": "Epic Pet Egg", "rarity": "Epic", "cat": "egg", "price_gems": 20, "sell": 0, "emoji": "🥚", "usable": True, "effect": "egg", "pool": "epic"},
    "pet_egg_legendary": {"name": "Legendary Pet Egg", "rarity": "Legendary", "cat": "egg", "price_gems": 50, "sell": 0, "emoji": "🥚", "usable": True, "effect": "egg", "pool": "legendary"},
    "pet_egg_mythic": {"name": "Mythic Pet Egg", "rarity": "Mythic", "cat": "egg", "price_gems": 120, "sell": 0, "emoji": "🥚", "usable": True, "effect": "egg", "pool": "mythic"},

    # Cosmetic titles (purchased with gems)
    "title_merchant": {"name": "Title: The Merchant", "rarity": "Epic", "cat": "title", "price_gems": 150, "sell": 0, "emoji": "💼"},
    "title_high_roller": {"name": "Title: High Roller", "rarity": "Epic", "cat": "title", "price_gems": 300, "sell": 0, "emoji": "🎰"},
    "title_bloopian_lord": {"name": "Title: Bloopian Lord", "rarity": "Mythic", "cat": "title", "price_gems": 800, "sell": 0, "emoji": "👑"},
    "title_star_gazer": {"name": "Title: Star Gazer", "rarity": "Legendary", "cat": "title", "price_gems": 500, "sell": 0, "emoji": "🔭"},
}

TOOLS = {"fishing_rod", "pickaxe", "shovel", "hunting_bow"}
TOOL_ACTIVITY = {"fishing_rod": "fish", "pickaxe": "mine", "shovel": "dig", "hunting_bow": "hunt"}

# ---------------------------------------------------------------------------
# Crops: key -> (grow seconds, harvest yield qty, xp)
# ---------------------------------------------------------------------------
CROPS = {
    "wheat": {"seed": "wheat_seed", "grow": 120, "yield": (2, 4), "xp": 15},
    "carrot": {"seed": "carrot_seed", "grow": 300, "yield": (1, 3), "xp": 30},
    "tomato": {"seed": "tomato_seed", "grow": 720, "yield": (1, 3), "xp": 60},
    "pumpkin": {"seed": "pumpkin_seed", "grow": 1800, "yield": (1, 2), "xp": 120},
    "golden_melon": {"seed": "melon_seed", "grow": 7200, "yield": (1, 2), "xp": 300},
    "rare_orchid": {"seed": "orchid_seed", "grow": 21600, "yield": (1, 1), "xp": 700},
    "starlight_berry": {"seed": "berry_seed", "grow": 43200, "yield": (1, 2), "xp": 1500},
}
PLOTS = 5

# ---------------------------------------------------------------------------
# Jobs (work)
# ---------------------------------------------------------------------------
JOBS = [
    {"key": "dev", "name": "Developer", "emoji": "💻", "pay": (150, 260), "chance": 0.92, "xp": 40,
     "success": [
         "You squashed a legendary bug that had haunted the codebase since 2019. The client tips you out of pure relief.",
         "You shipped a feature so clean it compiled on the first try. The ghost of good practices nods approvingly.",
         "You refactored 2,000 lines of spaghetti into a work of art. Your coworkers silently fear you now.",
     ],
     "fail": [
         "You deployed on a Friday and the prod server sneezed. The rollback is your hourly wage.",
         "You wrote a regex. Two engineers quit and a third filed a complaint with HR.",
     ]},
    {"key": "chef", "name": "Chef", "emoji": "👨‍🍳", "pay": (110, 210), "chance": 0.9, "xp": 35,
     "success": [
         "Your signature dish got a standing ovation. A food critic secretly slips you a generous envelope.",
         "You turned three sad ingredients into a feast. The kitchen staff worships your spatula.",
     ],
     "fail": [
         "You added 'a pinch' of salt. The dish is now legally classified as a hazard.",
         "The souffle collapsed like your dreams. You eat the evidence in the walk-in.",
     ]},
    {"key": "teacher", "name": "Teacher", "emoji": "📚", "pay": (90, 170), "chance": 0.95, "xp": 30,
     "success": [
         "Your student finally understood fractions and cried tears of joy. Their parents reward you generously.",
         "You ran a trivia day so good that the principal paid you overtime out of respect.",
     ],
     "fail": [
         "You taught the lesson on Tuesday. The exam was Thursday. The children remember neither.",
         "A fire drill interrupted your class 40 minutes early and the janitor found your coffee on the roof.",
     ]},
    {"key": "farmer", "name": "Farmer", "emoji": "🚜", "pay": (80, 160), "chance": 0.88, "xp": 28,
     "success": [
         "Your scarecrow unionised and negotiated a record yield. The fields are thriving.",
         "You sold a prize pumpkin at the county fair. A tourist paid double just for the photo.",
     ],
     "fail": [
         "The goats broke into the barn and held your harvest for ransom. You paid in grain.",
         "You planted the seeds upside down. Somehow half of them still grew. The other half have trust issues.",
     ]},
    {"key": "police", "name": "Police Officer", "emoji": "👮", "pay": (120, 220), "chance": 0.85, "xp": 38,
     "success": [
         "You solved the mystery of the disappearing doughnuts. The station chipped in for your good work.",
         "You talked a runaway balloon down from a tree and the town threw a parade in your honour.",
     ],
     "fail": [
         "You tried to catch a jaywalking pigeon and ended up in a fountain. The paperwork took hours.",
         "Your patrol car got stuck behind a parade of ducks. The chief makes you pay for the tow.",
     ]},
    {"key": "artist", "name": "Artist", "emoji": "🎨", "pay": (100, 240), "chance": 0.75, "xp": 45,
     "success": [
         "Your latest painting was mistaken for a masterpiece. A collector paid just to own the story.",
         "You drew a portrait of a Bloopian noble and they tipped you in style.",
     ],
     "fail": [
         "Your abstract piece was auctioned as 'recyclable material' by the janitor. He framed it.",
         "You spilt paint on a client's rug and the cleaning bill ate your commission.",
     ]},
    {"key": "doctor", "name": "Doctor", "emoji": "🩺", "pay": (200, 320), "chance": 0.9, "xp": 55,
     "success": [
         "You cured a case of the hiccups that had lasted eleven years. The patient showers you with gratitude.",
         "Your diagnosis was so sharp that a rival clinic offered to buy your stethoscope. You haggled up.",
     ],
     "fail": [
         "You prescribed 'more sleep' to a robot. It short-circuited. The repair bill is on you.",
         "You checked a patient's pulse with a stethoscope. On a plant. The malpractice insurance is furious.",
     ]},
    {"key": "pilot", "name": "Pilot", "emoji": "✈️", "pay": (180, 300), "chance": 0.85, "xp": 50,
     "success": [
         "You landed a cargo plane in a crosswind so nasty the tower clapped. A grateful shipping guild pays a bonus.",
         "You found a shortcut route that saved 40 minutes of fuel. The airline splits the savings with you.",
     ],
     "fail": [
         "You flew a detour around a cloud of butterflies and the extra fuel came out of your pocket.",
         "Your layover snack cost more than your flight pay. Aviation is glamorous.",
     ]},
    {"key": "streamer", "name": "Streamer", "emoji": "📺", "pay": (60, 400), "chance": 0.55, "xp": 60,
     "success": [
         "A clip of you sneezing funny went viral. The donations crash your stream and your wallet.",
         "You won a speedrun by 0.2 seconds. Viewers gamble on your skill and share the winnings.",
     ],
     "fail": [
         "You streamed for six hours to two viewers, one of whom was your own alt.",
         "Your sponsored segment glitched and played backwards. The sponsor demands a refund.",
     ]},
    {"key": "inventor", "name": "Inventor", "emoji": "🤖", "pay": (140, 280), "chance": 0.8, "xp": 48,
     "success": [
         "Your self-watering umbrella prototype actually works. A hedge fund buys the rights on the spot.",
         "You improved the classic paperclip. The patent office sends a thank-you card.",
     ],
     "fail": [
         "Your invention exploded politely. The lab manager charges you for the 'excitement'.",
         "You invented a machine that turns coffee into more coffee. The wiring cost a fortune.",
     ]},
    {"key": "writer", "name": "Writer", "emoji": "✍️", "pay": (90, 190), "chance": 0.85, "xp": 32,
     "success": [
         "Your short story about a sentient vending machine won a prize and a small fortune.",
         "A publisher advances you a chunk for a trilogy about a coin-obsessed dragon.",
     ],
     "fail": [
         "You wrote 50,000 words and accidentally deleted the file. The keyboard is now a crime scene.",
         "Your article got rejected for being 'too honest'. You burn the rejection letter dramatically.",
     ]},
    {"key": "astronaut", "name": "Astronaut", "emoji": "🚀", "pay": (250, 400), "chance": 0.82, "xp": 70,
     "success": [
         "You recovered a rogue satellite using only a broom and willpower. The space agency pays handsomely.",
         "You spotted a glittering asteroid. The salvage crew splits the find with you.",
     ],
     "fail": [
         "You floated off during a spacewalk and drifted for 45 minutes. The rescue fee is deducted from your pay.",
         "Your moon boots got stuck in lunar cheese. The extraction took four hours.",
     ]},
]

# ---------------------------------------------------------------------------
# Search locations
# ---------------------------------------------------------------------------
LOCATIONS = [
    {"key": "park", "name": "the Whispering Park", "emoji": "🌳", "low": 15, "high": 80, "risk": 0.05,
     "loot": [("rusty_coin", 0.08), ("comet_dust", 0.02), ("lucky_horseshoe", 0.01)],
     "lines": ["You check under a bench and find", "A squirrel directs you to a stash of"]},
    {"key": "mall", "name": "the Abandoned Mall", "emoji": "🏬", "low": 40, "high": 200, "risk": 0.2,
     "loot": [("gold_ore", 0.08), ("ancient_coin", 0.05), ("gold_ticket", 0.02)],
     "lines": ["You rummage through a dead arcade machine and find", "Behind a dusty fountain you find"]},
    {"key": "sewer", "name": "the Glittering Sewers", "emoji": "🕳️", "low": 50, "high": 260, "risk": 0.3,
     "loot": [("sapphire", 0.06), ("fossil_fragment", 0.05), ("bloopian_relic", 0.015)],
     "lines": ["You wade through questionable water and find", "A rat family offers you"]},
    {"key": "rooftop", "name": "the Rain-Slick Rooftops", "emoji": "🏙️", "low": 60, "high": 300, "risk": 0.25,
     "loot": [("gold_ore", 0.08), ("starforged_ore", 0.02), ("comet_dust", 0.04)],
     "lines": ["Behind an air vent you find", "A pigeon with a briefcase tips you off about"]},
    {"key": "spaceport", "name": "the Old Spaceport", "emoji": "🛸", "low": 120, "high": 500, "risk": 0.35,
     "loot": [("meteorite_shard", 0.03), ("starforged_ore", 0.05), ("ancient_tablet", 0.02)],
     "lines": ["Inside a decommissioned shuttle you find", "A retired pilot tells you to grab"]},
    {"key": "haunted", "name": "the Haunted Mansion", "emoji": "👻", "low": 100, "high": 450, "risk": 0.4,
     "loot": [("golden_idol", 0.04), ("crystal_skull", 0.015), ("ancient_coin", 0.07)],
     "lines": ["Behind a painting of a suspiciously familiar ghost you find", "A spectral butler hands you"]},
]

# ---------------------------------------------------------------------------
# Crimes
# ---------------------------------------------------------------------------
CRIMES = [
    {"key": "pickpocket", "name": "Pickpocket a tourist", "emoji": "🪝", "chance": 0.7, "pay": (80, 200), "fine": 80, "jail": 45, "xp": 20,
     "success": ["You lift a fat wallet during a street parade. The owner is too busy waving to notice.", "You dip into a coat pocket on the tram. Easiest coins of your life."],
     "fail": ["The tourist is a retired spy. You wake up handcuffed to a lamppost.", "You grab a wallet that was a decoy. The real one is on the inside of a very angry dog."]},
    {"key": "smash", "name": "Smash-and-grab", "emoji": "🧱", "chance": 0.55, "pay": (200, 500), "fine": 250, "jail": 90, "xp": 35,
     "success": ["You grab the till and vanish into a crowd of cosplayers. Perfect camouflage.", "The alarm was a raccoon. You take what you can and tip the raccoon for security services."],
     "fail": ["The glass was reinforced. Your forehead has a new opinion about that.", "A shopkeeper with a broom and a grudge ends your career."]},
    {"key": "hacker", "name": "Hacker gig", "emoji": "💻", "chance": 0.5, "pay": (300, 700), "fine": 400, "jail": 120, "xp": 50,
     "success": ["You drain fractions of a cent from a million accounts. Nobody notices, but the law of averages loves you.", "You ransom a spreadsheet that was already public. The company pays to look competent."],
     "fail": ["You typed 'hack the planet' and the firewall answered. Badly.", "The 'crypto vault' was a decoy honeypot. The bees are real."]},
    {"key": "heist", "name": "Bank heist (night shift)", "emoji": "🏦", "chance": 0.4, "pay": (600, 1200), "fine": 800, "jail": 300, "xp": 80,
     "success": ["You crack the vault with a stolen keycard and a paperclip. Security thanks you for not making a mess.", "You tunnel in from the cafe next door. The barista rats you out, but only after you've left."],
     "fail": ["The vault was a prop. The real vault was behind you. It was filming.", "You trip the silent alarm by existing too loudly. SWAT enjoys the show."]},
    {"key": "shady", "name": "Shady market deal", "emoji": "🕶️", "chance": 0.65, "pay": (120, 300), "fine": 150, "jail": 60, "xp": 25,
     "success": ["You sell 'genuine' moon rocks to a tourist. The moon was a balloon, but the profit is real.", "You broker a deal between two criminals who both think they won. You definitely won."],
     "fail": ["The buyer pays you in expired coupons. The vig takes your shoes as a fee.", "You're the mark. The 'rare artifact' is a painted toaster."]},
]

# ---------------------------------------------------------------------------
# Begging NPCs
# ---------------------------------------------------------------------------
NPCS = [
    {"name": "Old Greta", "emoji": "👵", "type": "friendly", "pool": (8, 45), "lines": [
        "Old Greta squints at you, chuckles, and presses coins into your hand. 'Buy yourself something foolish, dear.'",
        "Old Greta was about to buy yarn. She gives you the change instead. 'Knitting can wait.'"]},
    {"name": "Captain Barks", "emoji": "🐕", "type": "friendly", "pool": (10, 60), "lines": [
        "Captain Barks digs up an old bone-shaped coin pouch and nudges it toward you.",
        "Captain Barks trades you pocket lint for your dignity, and a few coins for good measure."]},
    {"name": "Mx. Glimmer", "emoji": "✨", "type": "rich", "pool": (40, 150), "lines": [
        "Mx. Glimmer waves a hand dismissively and tosses a stack of coins. 'Shiny things love company.'",
        "Mx. Glimmer was about to buy a third yacht. You get the leftovers. They are substantial."]},
    {"name": "Grumpy Gord", "emoji": "🧔", "type": "grumpy", "pool": (0, 15), "lines": [
        "Grumpy Gord gives you 5 coins and a lecture about 'the youth'. You feel older now.",
        "Grumpy Gord mutters something about hedges and hands you a single coin with deep reluctance."]},
    {"name": "Professor Plume", "emoji": "🦉", "type": "weird", "pool": (5, 40), "lines": [
        "Professor Plume pays you for 'participating in the economy'. He writes it down in a notebook.",
        "Professor Plume mistakes you for a research subject and pays you an hourly rate for standing there."]},
    {"name": "Whisper the Fox", "emoji": "🦊", "type": "grumpy", "pool": (0, 10), "lines": [
        "Whisper the Fox says 'no' with such elegance that you almost thank them.",
        "Whisper the Fox trades you a mushroom for your last bit of dignity. The mushroom is also gone."]},
]

# ---------------------------------------------------------------------------
# Rarity drop pools for fishing/mining/hunting/digging
# ---------------------------------------------------------------------------
FISH_POOL = [
    ("minnow", 0.30), ("silver_shimmer", 0.22), ("river_ruffian", 0.15),
    ("ember_carp", 0.11), ("moonlight_bass", 0.09),
    ("golden_grouper", 0.06), ("stormfin", 0.04),
    ("abyss_angler", 0.015), ("spectral_salmon", 0.01),
    ("leviathan_scale", 0.004), ("void_eel", 0.001),
]
ORE_POOL = [
    ("pebble", 0.28), ("copper_ore", 0.24), ("iron_ore", 0.18),
    ("gold_ore", 0.12), ("amethyst", 0.08),
    ("sapphire", 0.05), ("ruby", 0.03),
    ("diamond", 0.012), ("starforged_ore", 0.006),
    ("meteorite_shard", 0.002),
]
HUNT_POOL = [
    ("rabbit_pelt", 0.28), ("fox_pelt", 0.20), ("deer_hide", 0.17),
    ("boar_tusk", 0.13), ("wolf_pelt", 0.10),
    ("bear_paw", 0.06), ("panther_pelt", 0.035),
    ("dragonhawk_feather", 0.015), ("yeti_fur", 0.008),
    ("phoenix_plume", 0.002),
]
DIG_POOL = [
    ("rusty_coin", 0.22), ("old_boot", 0.20), ("clay_pot", 0.18),
    ("ancient_coin", 0.15), ("fossil_fragment", 0.12),
    ("dino_tooth", 0.07), ("golden_idol", 0.035),
    ("bloopian_relic", 0.02), ("crystal_skull", 0.005),
]
# rare events that can occur during activities
ACTIVITY_LINES = {
    "fish": [
        ("Something massive tugs the line... and snaps it. The lake keeps its secret.", "miss"),
        ("A fish jumps INTO your boat. You take it personally.", "bonus"),
        ("A mermaid applauds your casting form. You blush and reel in a great catch.", "bonus"),
    ],
    "mine": [
        ("Your pickaxe rings against bedrock. A faint voice whispers 'try the east wall'.", "miss"),
        ("You strike a pocket of glittering stone — the seam glows brighter than expected.", "bonus"),
    ],
    "hunt": [
        ("A deer stares at you judgmentally and walks away. You feel deeply evaluated.", "miss"),
        ("Your shot grazes a tree, startling a whole family of pheasants. Jackpot.", "bonus"),
    ],
    "dig": [
        ("You dig for ten minutes and find... a worm. It wishes you a good day.", "miss"),
        ("Your shovel thunks on something. It thunks back. Gold.", "bonus"),
    ],
}

# ---------------------------------------------------------------------------
# Pets: passive bonuses. bonus keys: work, fish, mine, hunt, dig, gamble, daily, all
# ---------------------------------------------------------------------------
PETS = {
    "slime": {"name": "Bloop Slime", "rarity": "Common", "emoji": "🟢", "bonus": {"work": 0.04}},
    "bunny": {"name": "Cinder Bunny", "rarity": "Common", "emoji": "🐰", "bonus": {"dig": 0.05}},
    "crab": {"name": "Crustacean Critic", "rarity": "Rare", "emoji": "🦀", "bonus": {"fish": 0.06}},
    "moon_fox": {"name": "Moon Fox", "rarity": "Rare", "emoji": "🦊", "bonus": {"hunt": 0.07, "luck": 0.05}},
    "rock_golem": {"name": "Rock Golem", "rarity": "Rare", "emoji": "🗿", "bonus": {"mine": 0.07}},
    "dragon_lizard": {"name": "Pygmy Dragon", "rarity": "Epic", "emoji": "🐉", "bonus": {"all": 0.05}},
    "golden_hamster": {"name": "Golden Hamster", "rarity": "Epic", "emoji": "🐹", "bonus": {"daily": 0.10}},
    "gambling_cat": {"name": "Lucky Shorthair", "rarity": "Epic", "emoji": "🐱", "bonus": {"gamble": 0.08, "luck": 0.08}},
    "phoenix": {"name": "Ember Phoenix", "rarity": "Legendary", "emoji": "🔥", "bonus": {"all": 0.08, "luck": 0.05}},
    "void_pup": {"name": "Void Pup", "rarity": "Mythic", "emoji": "🐺", "bonus": {"all": 0.12, "luck": 0.10}},
}
PET_EGG_POOLS = {
    "common": {"slime": 0.5, "bunny": 0.5},
    "rare": {"crab": 0.4, "moon_fox": 0.3, "rock_golem": 0.3},
    "epic": {"dragon_lizard": 0.4, "golden_hamster": 0.3, "gambling_cat": 0.3},
    "legendary": {"phoenix": 1.0},
    "mythic": {"void_pup": 1.0},
}

# ---------------------------------------------------------------------------
# Crafting recipes
# ---------------------------------------------------------------------------
RECIPES = [
    {"key": "repair_kit_craft", "name": "Repair Kit", "emoji": "🔧", "output": "repair_kit", "qty": 1,
     "cost": {"copper_ore": 2, "iron_ore": 1}, "xp": 30},
    {"key": "superb_lure", "name": "Superb Lure", "emoji": "🪝", "output": "luck_charm", "qty": 1,
     "cost": {"ember_carp": 2, "silver_shimmer": 1}, "xp": 40},
    {"key": "gold_plating", "name": "Gold Plating", "emoji": "🟨", "output": "gold_ticket", "qty": 1,
     "cost": {"gold_ore": 3, "ruby": 1}, "xp": 60},
    {"key": "lucky_coin", "name": "Lucky Coin", "emoji": "🪙", "output": "lucky_horseshoe", "qty": 1,
     "cost": {"ancient_coin": 2, "fossil_fragment": 1}, "xp": 70},
    {"key": "feed_crumbs", "name": "Pet Feed Crumbs", "emoji": "🦴", "output": "pet_treat", "qty": 3,
     "cost": {"wheat": 2, "carrot": 1}, "xp": 15},
    {"key": "exquisite_wine", "name": "Exquisite Berry Wine", "emoji": "🍷", "output": "starlight_berry", "qty": 3,
     "cost": {"starlight_berry": 1, "golden_melon": 1}, "xp": 500},
    {"key": "alloy_chain", "name": "Alloy Chain", "emoji": "⛓️", "output": "golden_idol", "qty": 1,
     "cost": {"iron_ore": 5, "gold_ore": 3}, "xp": 100},
    {"key": "crystal_key_craft", "name": "Crystal Key", "emoji": "🗝️", "output": "crystal_key", "qty": 1,
     "cost": {"diamond": 2, "meteorite_shard": 1}, "xp": 400},
    {"key": "bloopian_crown_craft", "name": "Bloopian Crown", "emoji": "👑", "output": "bloopian_crown", "qty": 1,
     "cost": {"golden_idol": 1, "phoenix_plume": 1, "bloopian_relic": 1}, "xp": 1000, "gems": 10},
]

# ---------------------------------------------------------------------------
# Quests
# ---------------------------------------------------------------------------
# track keys: earn (coins earned), work, fish, mine, hunt, dig, harvest, gamble, win, craft, sell, spend
DAILY_QUESTS = [
    {"key": "earn", "name": "Earn {target} coins from any activity", "target": 500, "track": "earn", "reward_coins": 200, "reward_xp": 30},
    {"key": "work", "name": "Work {target} jobs", "target": 3, "track": "work", "reward_coins": 150, "reward_xp": 20},
    {"key": "fish", "name": "Catch {target} fish", "target": 5, "track": "fish", "reward_coins": 150, "reward_xp": 25},
    {"key": "gamble", "name": "Place {target} gambles", "target": 5, "track": "gamble", "reward_coins": 250, "reward_xp": 40},
    {"key": "dig", "name": "Dig {target} times", "target": 2, "track": "dig", "reward_coins": 120, "reward_xp": 20},
    {"key": "harvest", "name": "Harvest {target} crops", "target": 2, "track": "harvest", "reward_coins": 150, "reward_xp": 30},
    {"key": "sell", "name": "Sell {target} items", "target": 3, "track": "sell", "reward_coins": 120, "reward_xp": 20},
    {"key": "win", "name": "Win {target} gambles", "target": 2, "track": "win", "reward_coins": 200, "reward_xp": 35},
]
WEEKLY_QUESTS = [
    {"key": "earn", "name": "Earn {target} coins in total", "target": 10000, "track": "earn", "reward_coins": 1500, "reward_xp": 200, "gems": 2},
    {"key": "fish", "name": "Catch {target} fish", "target": 25, "track": "fish", "reward_coins": 800, "reward_xp": 150},
    {"key": "gamble", "name": "Place {target} gambles", "target": 30, "track": "gamble", "reward_coins": 1200, "reward_xp": 180, "gems": 1},
    {"key": "craft", "name": "Craft {target} items", "target": 3, "track": "craft", "reward_coins": 1000, "reward_xp": 160, "gems": 1},
    {"key": "work", "name": "Work {target} jobs", "target": 20, "track": "work", "reward_coins": 900, "reward_xp": 150},
    {"key": "harvest", "name": "Harvest {target} crops", "target": 10, "track": "harvest", "reward_coins": 900, "reward_xp": 150},
]
MONTHLY_QUESTS = [
    {"key": "earn", "name": "Earn {target} coins in total", "target": 100000, "track": "earn", "reward_coins": 10000, "reward_xp": 1500, "gems": 10},
    {"key": "legendary", "name": "Find {target} Legendary+ items", "target": 3, "track": "legendary", "reward_coins": 8000, "reward_xp": 1200, "gems": 8},
    {"key": "craft", "name": "Craft {target} items", "target": 10, "track": "craft", "reward_coins": 7000, "reward_xp": 1000, "gems": 6},
    {"key": "fish", "name": "Catch {target} fish", "target": 60, "track": "fish", "reward_coins": 6000, "reward_xp": 900, "gems": 5},
]

# ---------------------------------------------------------------------------
# Achievements: key, name, desc, reward (coins, gems, xp), condition (stat checks)
# ---------------------------------------------------------------------------
ACHIEVEMENTS = [
    {"key": "first_coins", "name": "Warm Pockets", "desc": "Earn 1,000 lifetime coins", "coins": 200, "gems": 0, "xp": 50,
     "stat": "earned_total", "need": 1000},
    {"key": "saver", "name": "Bloopian Banker", "desc": "Store 50,000 coins in the bank", "coins": 1500, "gems": 1, "xp": 200,
     "stat": "banked_total", "need": 50000},
    {"key": "level10", "name": "Rising Star", "desc": "Reach level 10", "coins": 500, "gems": 0, "xp": 0, "level": 10},
    {"key": "level25", "name": "Seasoned Bloop", "desc": "Reach level 25", "coins": 1500, "gems": 2, "xp": 0, "level": 25},
    {"key": "level50", "name": "Local Legend", "desc": "Reach level 50", "coins": 4000, "gems": 5, "xp": 0, "level": 50},
    {"key": "level100", "name": "Bloopian Demigod", "desc": "Reach level 100", "coins": 10000, "gems": 15, "xp": 0, "level": 100},
    {"key": "fisher", "name": "Rod Rookie", "desc": "Catch 50 fish", "coins": 500, "gems": 0, "xp": 100, "stat": "fish_caught", "need": 50},
    {"key": "master_fisher", "name": "Legendary Angler", "desc": "Catch 250 fish", "coins": 2000, "gems": 3, "xp": 300, "stat": "fish_caught", "need": 250},
    {"key": "mythic_fisher", "name": "Mythic Hauler", "desc": "Catch 10 Mythic fish", "coins": 5000, "gems": 8, "xp": 600, "stat": "mythic_fish", "need": 10},
    {"key": "miner", "name": "Rock Enthusiast", "desc": "Mine 50 ores", "coins": 500, "gems": 0, "xp": 100, "stat": "ores_mined", "need": 50},
    {"key": "gem_hunter", "name": "Gem Hunter", "desc": "Mine 10 gems", "coins": 1500, "gems": 5, "xp": 200, "stat": "gems_mined", "need": 10},
    {"key": "gambler", "name": "Casual Gambler", "desc": "Place 50 gambles", "coins": 750, "gems": 1, "xp": 150, "stat": "gambles_placed", "need": 50},
    {"key": "high_roller", "name": "High Roller", "desc": "Win 100,000 coins in one gamble", "coins": 5000, "gems": 10, "xp": 500, "stat": "best_gamble_win", "need": 100000},
    {"key": "criminal", "name": "Repeat Offender", "desc": "Survive 20 crimes", "coins": 750, "gems": 1, "xp": 120, "stat": "crimes_success", "need": 20},
    {"key": "jailbird", "name": "Jailbird", "desc": "Be jailed 5 times", "coins": 250, "gems": 1, "xp": 50, "stat": "times_jailed", "need": 5},
    {"key": "craftsman", "name": "Artisan", "desc": "Craft 25 items", "coins": 1500, "gems": 2, "xp": 250, "stat": "items_crafted", "need": 25},
    {"key": "collector", "name": "Curator", "desc": "Own 30 distinct items at once", "coins": 1000, "gems": 2, "xp": 200, "stat": "distinct_items", "need": 30},
    {"key": "pet_lover", "name": "Pet Whisperer", "desc": "Adopt 3 pets", "coins": 750, "gems": 2, "xp": 150, "stat": "pets_adopted", "need": 3},
    {"key": "trader", "name": "Deal Maker", "desc": "Complete 5 trades", "coins": 1000, "gems": 2, "xp": 200, "stat": "trades_done", "need": 5},
    {"key": "marketeer", "name": "Market Mogul", "desc": "Sell 10 market listings", "coins": 1000, "gems": 2, "xp": 200, "stat": "market_sold", "need": 10},
    {"key": "prestiger", "name": "Phoenix Rises", "desc": "Prestige once", "coins": 5000, "gems": 25, "xp": 0, "prestige": 1},
    {"key": "lottery_winner", "name": "Jackpot!", "desc": "Win the lottery", "coins": 0, "gems": 20, "xp": 500, "stat": "lottery_wins", "need": 1},
    {"key": "streak7", "name": "Devotion", "desc": "Reach a 7-day daily streak", "coins": 1000, "gems": 2, "xp": 150, "stat": "best_daily_streak", "need": 7},
    {"key": "streak30", "name": "Unstoppable", "desc": "Reach a 30-day daily streak", "coins": 5000, "gems": 10, "xp": 500, "stat": "best_daily_streak", "need": 30},
]
TITLE_BY_ACHIEVEMENT = {
    "level25": "The Seasoned",
    "level50": "The Local Legend",
    "level100": "The Bloopian Demigod",
    "master_fisher": "The Angler King",
    "high_roller": "The High Roller",
    "prestiger": "The Phoenix",
    "lottery_winner": "The Lucky",
}

# ---------------------------------------------------------------------------
# Gambling
# ---------------------------------------------------------------------------
COINFLIP_MIN, COINFLIP_MAX = 10, 50000
COINFLIP_WIN_CHANCE = 0.495

DICE_MIN, DICE_MAX = 10, 50000

SLOT_SYMBOLS = [
    {"emoji": "🍒", "weight": 30, "payout": 2},
    {"emoji": "🍋", "weight": 22, "payout": 3},
    {"emoji": "🔔", "weight": 16, "payout": 5},
    {"emoji": "💎", "weight": 12, "payout": 8},
    {"emoji": "⭐", "weight": 10, "payout": 12},
    {"emoji": "👑", "weight": 7, "payout": 20},
    {"emoji": "7️⃣", "weight": 3, "payout": 40},
]
SLOT_LINES = [(0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 4, 8), (2, 4, 6)]
SLOTS_MIN, SLOTS_MAX = 10, 25000

BJ_MIN, BJ_MAX = 10, 50000
ROULETTE_MIN, ROULETTE_MAX = 10, 50000
ROULETTE_REDS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}

LOTTERY_TICKET_PRICE = 100
LOTTERY_POOL_PERCENT = 0.6
LOTTERY_DRAW_HOURS = 24

SCRATCH_PRICE = 200
SCRATCH_SYMBOLS = [
    {"emoji": "🍀", "weight": 10, "mult": 10},
    {"emoji": "💎", "weight": 14, "mult": 5},
    {"emoji": "⭐", "weight": 22, "mult": 2},
    {"emoji": "🍒", "weight": 30, "mult": 1.5},
    {"emoji": "💩", "weight": 24, "mult": 0},
]

WHEEL_SEGMENTS = [
    {"label": "LOSE", "weight": 16, "kind": "lose"},
    {"label": "½", "weight": 12, "kind": "half"},
    {"label": "1×", "weight": 14, "kind": "one"},
    {"label": "2×", "weight": 10, "kind": "mult", "value": 2},
    {"label": "3×", "weight": 7, "kind": "mult", "value": 3},
    {"label": "5×", "weight": 4, "kind": "mult", "value": 5},
    {"label": "GEMS", "weight": 3, "kind": "gems", "value": 2},
    {"label": "JACKPOT", "weight": 1, "kind": "jackpot", "value": 25},
    {"label": "LOSE", "weight": 16, "kind": "lose"},
    {"label": "½", "weight": 12, "kind": "half"},
    {"label": "1×", "weight": 14, "kind": "one"},
    {"label": "2×", "weight": 10, "kind": "mult", "value": 2},
]
WHEEL_MIN, WHEEL_MAX = 10, 25000

GAMBLE_COOLDOWN = 3  # seconds between any gambles

# Daily / weekly / monthly rewards
DAILY_BASE = 150
DAILY_STREAK_BONUS_PER_DAY = 25
DAILY_STREAK_CAP = 2000
WEEKLY_BASE = 1500
WEEKLY_STREAK_BONUS = 300
MONTHLY_BASE = 5000
MONTHLY_GEMS = 5

WORK_COOLDOWN = 45
SEARCH_COOLDOWN = 45
CRIME_COOLDOWN = 90
BEG_COOLDOWN = 90
FISH_COOLDOWN = 60
MINE_COOLDOWN = 60
HUNT_COOLDOWN = 75
DIG_COOLDOWN = 75

EVENT_CHANCE = 0.04
PETS_MAX = 9

PRESTIGE_LEVEL = 100
PRESTIGE_REQUIRED_NET = 100000
PRESTIGE_BONUS_PER = 0.05
