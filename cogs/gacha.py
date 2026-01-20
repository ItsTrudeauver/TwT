import discord
from discord.ext import commands
import aiohttp
import random
import os
import asyncio

# Custom Modules
from core.database import get_user, batch_add_to_inventory, batch_cache_characters
from core.game_math import calculate_effective_power
from core.image_gen import generate_10_pull_image

class Gacha(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.anilist_url = os.getenv("ANILIST_URL", "https://graphql.anilist.co")

    def get_rarity_and_page(self):
        """
        Logic: SSR (rank 1-250), SR (rank 251-1500), R (rank 1501-10000).
        Rolls rarity first, then selects a page within that range.
        """
        roll = random.random() * 100
        if roll < 1:  # 1% SSR
            return "SSR", random.randint(1, 250)
        if roll < 11: # 10% SR (next 10%)
            return "SR", random.randint(251, 1500)
        # 89% R
        return "R", random.randint(1501, 10000)

    def get_rank_by_rarity(self, rarity):
        ranks = {"SSR": "S", "SR": "A", "R": "B"}
        return ranks.get(rarity, "C")

    async def fetch_character_by_rank(self, session, rarity, page):
        """Fetches character data from AniList and applies battle power logic."""
        query = """
        query ($page: Int) {
            Page(page: $page, perPage: 1) {
                characters(sort: FAVOURITES_DESC) {
                    id
                    name { full }
                    image { large }
                    favourites
                }
            }
        }
        """
        variables = {'page': page}
        try:
            async with session.post(self.anilist_url, json={'query': query, 'variables': variables}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    chars = data['data']['Page']['characters']
                    if chars:
                        char = chars[0]
                        # Calculate power based on the newly implemented tier/squash logic
                        true_p = calculate_effective_power(char['favourites'], rarity, page)
                        return {
                            'id': char['id'],
                            'name': char['name']['full'],
                            'image_url': char['image']['large'],
                            'favs': char['favourites'],
                            'rarity': rarity,
                            'page': page,
                            'true_power': true_p,
                            'rank': self.get_rank_by_rarity(rarity)
                        }
        except Exception as e:
            print(f"AniList API Error for page {page}: {e}")
        return None

    async def get_valid_character(self, session):
        """Handles the logic of rolling rarity and fetching with retries."""
        for _ in range(3):
            rarity, page = self.get_rarity_and_page()
            data = await self.fetch_character_by_rank(session, rarity, page)
            if data:
                return data
        return None

    @commands.command(name="pull")
    async def pull_character(self, ctx, amount: int = 1):
        if amount not in [1, 10]:
            await ctx.send("❌ You can only pull **1** or **10** times.")
            return

        # Ensure user exists in the database
        await get_user(ctx.author.id)

        loading_msg = await ctx.send(f"🎰 *Initiating {amount}-Pull Protocol...*")
        
        try:
            # PERFORMANCE FIX: Use a single session and fetch all characters concurrently
            async with aiohttp.ClientSession() as session:
                tasks = [self.get_valid_character(session) for _ in range(amount)]
                pulled_chars = await asyncio.gather(*tasks)
                
                # Filter out any failed fetches
                pulled_chars = [c for c in pulled_chars if c is not None]

            if not pulled_chars:
                await loading_msg.edit(content="❌ Failed to connect to character database.")
                return

            # Pity Mechanic for 10-pulls (Guaranteed SR+)
            if amount == 10:
                has_good_pull = any(c['rarity'] in ["SR", "SSR"] for c in pulled_chars)
                if not has_good_pull:
                    # Force the last slot to be at least an SR
                    async with aiohttp.ClientSession() as session:
                        _, page = "SR", random.randint(251, 1500)
                        sr_char = await self.fetch_character_by_rank(session, "SR", page)
                        if sr_char:
                            pulled_chars[-1] = sr_char

            # BATCH DB FIX: Save all results with rank and power in one trip
            await batch_cache_characters(pulled_chars)
            await batch_add_to_inventory(ctx.author.id, [c['id'] for c in pulled_chars])

            if amount == 1:
                char = pulled_chars[0]
                embed = discord.Embed(title=f"✨ {char['name']}", color=0x00ff00)
                embed.add_field(name="Rarity", value=f"**{char['rarity']}**", inline=True)
                embed.add_field(name="Rank", value=f"#{char['page']}", inline=True)
                embed.add_field(name="Power", value=f"`{char['true_power']:,}`", inline=True)
                embed.set_image(url=char['image_url'])
                await loading_msg.delete()
                await ctx.send(embed=embed)
            else:
                await loading_msg.edit(content="🎨 *Generating results image...*")
                image_data = await generate_10_pull_image(pulled_chars)
                file = discord.File(fp=image_data, filename="10pull.png")
                await loading_msg.delete()
                await ctx.send(f"💫 **{ctx.author.name}'s 10-Pull Results**", file=file)

        except Exception as e:
            print(f"CRITICAL ERROR in !pull: {e}")
            await ctx.send(f"⚠️ An internal error occurred: `{e}`")

async def setup(bot):
    await bot.add_cog(Gacha(bot))