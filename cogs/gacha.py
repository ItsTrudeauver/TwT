import discord
from discord.ext import commands
import aiosqlite
import aiohttp
import random
import os

# Custom Modules
from core.database import DB_PATH, add_character_to_inventory, cache_character
from core.game_math import calculate_effective_power
from core.image_gen import generate_10_pull_image

class Gacha(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.anilist_url = os.getenv("ANILIST_URL")

    def roll_rarity(self):
        """
        The Dice Roll.
        Rates: SSR (1%), SR (9%), R (90%)
        """
        roll = random.uniform(0, 100)
        if roll <= 1.0:   return "SSR"
        elif roll <= 10.0: return "SR"
        else:              return "R"

    def get_rank_by_rarity(self, rarity):
        """
        Maps Rarity to Global AniList Rank.
        """
        if rarity == "SSR":
            # The Elite: Top 250 Characters
            return random.randint(1, 250)
        elif rarity == "SR":
            # The Strong Popular Tier
            return random.randint(251, 6000)
        else:
            # The Deep Cuts
            return random.randint(6001, 25000)

    async def fetch_character_by_rank(self, rank):
        """
        Fetches the specific character at that Global Rank from AniList.
        """
        query = '''
        query ($rank: Int) {
            Page (page: $rank, perPage: 1) {
                characters (sort: FAVOURITES_DESC) {
                    id
                    name { full }
                    image { large }
                    favourites
                    siteUrl
                }
            }
        }
        '''
        variables = {'rank': rank}

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(self.anilist_url, json={'query': query, 'variables': variables}) as resp:
                    if resp.status != 200:
                        print(f"⚠️ API Error: {resp.status}")
                        return None
                    data = await resp.json()
                    if not data.get('data', {}).get('Page', {}).get('characters'):
                        return None
                    return data['data']['Page']['characters'][0]
            except Exception as e:
                print(f"⚠️ Network Error: {e}")
                return None

    @commands.command(name="pull")
    async def pull_character(self, ctx, amount: int = 1):
        """
        Performs a Gacha Pull.
        Usage: !pull (Single) or !pull 10 (Multi)
        """
        # 1. Validation
        if amount not in [1, 10]:
            await ctx.send("❌ You can only pull **1** or **10** times.")
            return

        # 2. Feedback Message
        if amount == 1:
            loading_msg = await ctx.send("🎲 *Rolling the die...*")
        else:
            loading_msg = await ctx.send(f"🎰 *Initiating 10-Pull Protocol...*")

        pulled_chars = []
        
        # 3. The Pull Loop
        for _ in range(amount):
            # Roll Rarity -> Determine Rank -> Fetch Data
            rarity = self.roll_rarity()
            rank = self.get_rank_by_rarity(rarity)
            data = await self.fetch_character_by_rank(rank)
            
            if data:
                # Add to local list for display
                pulled_chars.append({
                    'id': data['id'],
                    'name': data['name']['full'],
                    'image_url': data['image']['large'],
                    'favs': data['favourites'],
                    'rarity': rarity,
                    'rank': rank
                })
                
                # Save to Database (Cache Metadata + Add Instance to Inventory)
                # Note: We save immediately to prevent data loss if the bot crashes mid-loop
                await cache_character(
                    data['id'], 
                    data['name']['full'], 
                    data['image']['large'], 
                    data['favourites']
                )
                await add_character_to_inventory(str(ctx.author.id), data['id'])

        # 4. The Display Logic
        if not pulled_chars:
            await loading_msg.edit(content="❌ The Summoning Circle failed (API Error). Try again.")
            return

        if amount == 1:
            # --- SINGLE PULL (Standard Embed) ---
            char = pulled_chars[0]
            power = calculate_effective_power(char['favs'])
            
            color_map = {
                "SSR": discord.Color.gold(), 
                "SR": discord.Color.purple(), 
                "R": discord.Color.blue()
            }
            
            embed = discord.Embed(
                title=f"✨ {char['rarity']} Summon!",
                description=f"**{char['name']}**\nGlobal Rank: #{char['rank']}\nFavorites: {char['favs']:,}\n**Power: {power:,}**",
                color=color_map.get(char['rarity'], discord.Color.default())
            )
            embed.set_image(url=char['image_url'])
            embed.set_footer(text=f"ID: {char['id']}")