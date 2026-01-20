import discord
from discord.ext import commands
import aiohttp
import random
import os
import asyncio

from core.database import get_user, batch_add_to_inventory, batch_cache_characters, get_db_pool
from core.game_math import calculate_effective_power
from core.image_gen import generate_10_pull_image
from core.economy import Economy, GEMS_PER_PULL

class Gacha(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.anilist_url = os.getenv("ANILIST_URL", "https://graphql.anilist.co")

    def get_rarity_and_page(self, guaranteed_ssr=False):
        """Rolls rarity tier first, then selects a rank/page within that range."""
        if guaranteed_ssr:
            return "SSR", random.randint(1, 250)
            
        roll = random.random() * 100
        if roll < 1:  return "SSR", random.randint(1, 250)
        if roll < 11: return "SR", random.randint(251, 1500)
        return "R", random.randint(1501, 10000)

    async def fetch_character_by_rank(self, session, rarity, page):
        """Fetches character from AniList and applies the Battle Power Logic."""
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
        try:
            async with session.post(self.anilist_url, json={'query': query, 'variables': {'page': page}}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    chars = data['data']['Page']['characters']
                    if chars:
                        char = chars[0]
                        true_p = calculate_effective_power(char['favourites'], rarity, page)
                        return {
                            'id': char['id'],
                            'name': char['name']['full'],
                            'image_url': char['image']['large'],
                            'favs': char['favourites'],
                            'rarity': rarity,
                            'page': page,
                            'true_power': true_p
                        }
        except Exception as e:
            print(f"AniList API Error: {e}")
        return None

    @commands.command(name="pull")
    async def pull_character(self, ctx, amount: int = 1):
        if amount not in [1, 10]:
            await ctx.send("❌ You can only pull **1** or **10** times.")
            return

        user_data = await get_user(ctx.author.id)
        cost = amount * GEMS_PER_PULL
        is_free = await Economy.is_free_pull(ctx.author, self.bot)

        # Economy Check
        if not is_free and user_data['gacha_gems'] < cost:
            await ctx.send(f"❌ You need **{cost:,} Gems** for this. Your balance: **{user_data['gacha_gems']:,}**")
            return

        loading_msg = await ctx.send(f"🎰 *Initiating {amount}-Pull Protocol...*")
        
        try:
            # Deduct gems if not free
            if not is_free:
                pool = await get_db_pool()
                await pool.execute("UPDATE users SET gacha_gems = gacha_gems - $1 WHERE user_id = $2", cost, str(ctx.author.id))

            async with aiohttp.ClientSession() as session:
                tasks = []
                for _ in range(amount):
                    rarity, page = self.get_rarity_and_page()
                    tasks.append(self.fetch_character_by_rank(session, rarity, page))
                
                pulled_chars = [c for c in await asyncio.gather(*tasks) if c]

            if not pulled_chars:
                return await loading_msg.edit(content="❌ Connection to database failed.")

            await batch_cache_characters(pulled_chars)
            await batch_add_to_inventory(ctx.author.id, [c['id'] for c in pulled_chars])

            if amount == 1:
                char = pulled_chars[0]
                embed = discord.Embed(title=f"✨ {char['name']}", color=0x00ff00)
                embed.description = f"**{char['rarity']}** | Rank: `#{char['page']}`\nPower: `{char['true_power']:,}`"
                embed.set_image(url=char['image_url'])
                await loading_msg.delete()
                await ctx.send(embed=embed)
            else:
                image_data = await generate_10_pull_image(pulled_chars)
                await loading_msg.delete()
                await ctx.send(file=discord.File(fp=image_data, filename="10pull.png"))

        except Exception as e:
            await ctx.send(f"⚠️ An internal error occurred: `{e}`")

    @commands.command(name="starter")
    async def starter_pull(self, ctx):
        """New player special: 10 pulls with 1 guaranteed SSR."""
        user_data = await get_user(ctx.author.id)

        if user_data.get('has_claimed_starter'):
            await ctx.send("❌ You have already claimed your Starter Pack!")
            return

        loading_msg = await ctx.send("🎁 *Opening your Legendary Starter Pack...*")

        try:
            async with aiohttp.ClientSession() as session:
                tasks = []
                # First character is a guaranteed SSR
                r, p = self.get_rarity_and_page(guaranteed_ssr=True)
                tasks.append(self.fetch_character_by_rank(session, r, p))
                
                # Remaining 9 are normal rolls
                for _ in range(9):
                    r, p = self.get_rarity_and_page()
                    tasks.append(self.fetch_character_by_rank(session, r, p))
                
                pulled_chars = [c for c in await asyncio.gather(*tasks) if c]

            if len(pulled_chars) < 10:
                return await loading_msg.edit(content="❌ Data sync error. Try again.")

            # Save data
            await batch_cache_characters(pulled_chars)
            await batch_add_to_inventory(ctx.author.id, [c['id'] for c in pulled_chars])
            
            # Update starter flag
            pool = await get_db_pool()
            await pool.execute("UPDATE users SET has_claimed_starter = TRUE WHERE user_id = $1", str(ctx.author.id))

            # Display
            image_data = await generate_10_pull_image(pulled_chars)
            await loading_msg.delete()
            await ctx.send(content="🎉 **Welcome to the game!** Here are your first 10 characters (including one guaranteed SSR!):", 
                           file=discord.File(fp=image_data, filename="starter_pull.png"))

        except Exception as e:
            await ctx.send(f"⚠️ Error: `{e}`")

async def setup(bot):
    await bot.add_cog(Gacha(bot))