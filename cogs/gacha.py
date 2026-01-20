import discord
from discord.ext import commands
import aiosqlite
import aiohttp
import random
import os

from core.database import DB_PATH, add_character_to_inventory, cache_character
from core.game_math import calculate_effective_power

class Gacha(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.anilist_url = os.getenv("ANILIST_URL")

    def roll_rarity(self):
        """
        The Dice Roll.
        """
        roll = random.uniform(0, 100)
        if roll <= 1.0:   return "SSR"  # 1%
        elif roll <= 10.0: return "SR"  # 9%
        else:              return "R"   # 90%

    def get_rank_by_rarity(self, rarity):
        """
        Maps Rarity to Global AniList Rank.
        """
        if rarity == "SSR":
            # The Elite. Top 250 Characters.
            # Range: Rank 1 to 250
            return random.randint(1, 250)
            
        elif rarity == "SR":
            # The Strong Popular Tier.
            # Range: Rank 251 to 6,000
            return random.randint(251, 1500)
            
        else:
            # The Sea of Content.
            # Range: Rank 6,001 to 25,000
            return random.randint(1501, 250000)

    async def fetch_character_by_rank(self, rank):
        """
        Fetches the specific character at that Global Rank.
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
                    # AniList might have gaps, but usually rank queries are safe
                    if not data['data']['Page']['characters']:
                        return None
                    return data['data']['Page']['characters'][0]
            except Exception as e:
                print(f"⚠️ Network Error: {e}")
                return None

    @commands.command(name="pull")
    async def pull_character(self, ctx):
        # 1. Feedback
        loading_msg = await ctx.send("🎲 *Rolling the stars...*")

        # 2. Determine Rarity & Rank
        rarity_pool = self.roll_rarity()
        target_rank = self.get_rank_by_rarity(rarity_pool)
        
        # 3. Fetch
        # We append the rarity to the loading msg so the user feels the hype (or despair)
        await loading_msg.edit(content=f"✨ **{rarity_pool}** Triggered! Summoning Rank #{target_rank}...")
        
        char_data = await self.fetch_character_by_rank(target_rank)
        
        if not char_data:
            await loading_msg.edit(content="❌ The Leylines are clogged (API Error). Try again.")
            return

        # 4. Process Data
        anilist_id = char_data['id']
        name = char_data['name']['full']
        image_url = char_data['image']['large']
        favs = char_data['favourites']
        
        # Power Calc (Using your Aggressive Math)
        power = calculate_effective_power(favs)

        # 5. Save
        await cache_character(anilist_id, name, image_url, favs)
        await add_character_to_inventory(str(ctx.author.id), anilist_id)

        # 6. Display
        color_map = {
            "SSR": discord.Color.gold(),
            "SR": discord.Color.purple(),
            "R": discord.Color.blue()
        }
        
        embed = discord.Embed(
            title=f"💫 {rarity_pool} Summon",
            description=f"**{name}**\n Global Rank: #{target_rank}\nFavorites: {favs:,}\n**Power: {power:,}**",
            color=color_map.get(rarity_pool, discord.Color.default())
        )
        embed.set_image(url=image_url)
        embed.set_footer(text=f"ID: {anilist_id} • System: {rarity_pool}")

        await loading_msg.edit(content=None, embed=embed)

async def setup(bot):
    await bot.add_cog(Gacha(bot))