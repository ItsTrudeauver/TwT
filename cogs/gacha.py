import discord
from discord.ext import commands
import aiohttp
import random
import os
import asyncio
import time

from core.database import get_user, batch_add_to_inventory, batch_cache_characters, get_db_pool
from core.game_math import calculate_effective_power
from core.image_gen import generate_10_pull_image
from core.economy import Economy, GEMS_PER_PULL

class Gacha(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.anilist_url = os.getenv("ANILIST_URL", "https://graphql.anilist.co")

    def get_rarity_and_page(self, guaranteed_ssr=False):
        if guaranteed_ssr:
            return "SSR", random.randint(1, 250)
        
        roll = random.random() * 100
        if roll < 3:  return "SSR", random.randint(1, 250)
        if roll < 15: return "SR", random.randint(251, 1500)
        return "R", random.randint(1501, 10000)

    async def get_active_banner(self):
        pool = await get_db_pool()
        current_time = int(time.time())
        
        banner = await pool.fetchrow("""
            SELECT * FROM banners 
            WHERE is_active = TRUE AND end_timestamp > $1 
            LIMIT 1
        """, current_time)
        
        if not banner:
            await pool.execute("UPDATE banners SET is_active = FALSE WHERE is_active = TRUE AND end_timestamp <= $1", current_time)
        return banner

    async def fetch_banner_pull(self, session, banner):
        """
        Modified pull logic that checks the DB to find which Banner IDs match the rolled rarity.
        """
        rarity, page = self.get_rarity_and_page()
        
        # Check if we hit the Rate-Up chance
        if rarity in ["SSR", "SR"] and random.random() < banner['rate_up_chance']:
            pool = await get_db_pool()
            
            # Find which IDs in the banner match the rolled rarity
            # We must query the cache because 'rate_up_ids' in banners table is just a list of ints.
            possible_hits = await pool.fetch("""
                SELECT anilist_id FROM characters_cache 
                WHERE anilist_id = ANY($1) AND rarity = $2
            """, banner['rate_up_ids'], rarity)
            
            if possible_hits:
                # Pick one valid ID for this rarity
                target_row = random.choice(possible_hits)
                target_id = target_row['anilist_id']
                
                # Fetch it (using the known rarity to avoid re-calculation)
                return await self.fetch_character_by_id(session, target_id, forced_rarity=rarity)

        # Fallback: Normal random pull
        return await self.fetch_character_by_rank(session, rarity, page)

    async def fetch_character_by_id(self, session, anilist_id: int, forced_rarity=None):
        """
        Fetches basic character data.
        If forced_rarity is provided (from !set_banner), we skip calculations.
        If not, we estimate based on favorites.
        """
        query = """
        query ($id: Int) {
            Character(id: $id) {
                id
                name { full }
                image { large }
                favourites
            }
        }
        """
        try:
            async with session.post(self.anilist_url, json={'query': query, 'variables': {'id': anilist_id}}) as resp:
                if resp.status != 200: return None
                data = await resp.json()
                
                if not data.get('data') or not data['data'].get('Character'):
                    print(f"⚠️ ID {anilist_id} returned NULL.")
                    return None

                char_data = data['data']['Character']
                favs = char_data['favourites']

                if forced_rarity:
                    # TRUST THE USER / BANNER SETTINGS
                    rarity = forced_rarity
                    # Rank is irrelevant for banner units, but we need a number for math
                    rank = 1 if rarity == "SSR" else 500 if rarity == "SR" else 2000
                else:
                    # Fallback estimation
                    if favs >= 15000: rarity, rank = "SSR", 100
                    elif favs >= 2000: rarity, rank = "SR", 1000
                    else: rarity, rank = "R", 5000

                true_p = calculate_effective_power(favs, rarity, rank)
                
                return {
                    'id': char_data['id'],
                    'name': char_data['name']['full'],
                    'image_url': char_data['image']['large'],
                    'favs': favs,
                    'rarity': rarity,
                    'page': rank,
                    'true_power': true_p
                }
        except Exception as e:
            print(f"❌ Error fetching ID {anilist_id}: {e}")
            return None

    async def fetch_character_by_rank(self, session, rarity, page):
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
                    chars = data.get('data', {}).get('Page', {}).get('characters', [])
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
        except: pass
        return None

    @commands.command(name="pull")
    async def pull_character(self, ctx, amount: int = 1):
        if amount not in [1, 10]: return await ctx.send("❌ Only 1 or 10 pulls allowed.")
        
        user_data = await get_user(ctx.author.id)
        cost = amount * GEMS_PER_PULL
        is_free = await Economy.is_free_pull(ctx.author, self.bot)

        if not is_free and user_data['gacha_gems'] < cost:
            return await ctx.send(f"❌ Need **{cost:,} Gems**. Balance: **{user_data['gacha_gems']:,}**")

        loading = await ctx.send(f"🎰 *Pulling {amount}x...*")
        
        try:
            banner = await self.get_active_banner()
            if not is_free:
                pool = await get_db_pool()
                await pool.execute("UPDATE users SET gacha_gems = gacha_gems - $1 WHERE user_id = $2", cost, str(ctx.author.id))

            async with aiohttp.ClientSession() as session:
                tasks = []
                for _ in range(amount):
                    if banner:
                        tasks.append(self.fetch_banner_pull(session, banner))
                    else:
                        r, p = self.get_rarity_and_page()
                        tasks.append(self.fetch_character_by_rank(session, r, p))
                
                pulled_chars = [c for c in await asyncio.gather(*tasks) if c]

            if not pulled_chars: return await loading.edit(content="❌ Database/API Error.")

            await batch_cache_characters(pulled_chars)
            await batch_add_to_inventory(ctx.author.id, [c['id'] for c in pulled_chars])

            if amount == 1:
                c = pulled_chars[0]
                embed = discord.Embed(title=f"✨ {c['name']}", description=f"**{c['rarity']}** | Power: {c['true_power']:,}", color=0xFFD700)
                embed.set_image(url=c['image_url'])
                await loading.delete()
                await ctx.send(embed=embed)
            else:
                img = await generate_10_pull_image(pulled_chars)
                await loading.delete()
                await ctx.send(file=discord.File(fp=img, filename="10pull.png"))

        except Exception as e:
            await ctx.send(f"⚠️ Error: `{e}`")

    @commands.command(name="starter")
    async def starter_pull(self, ctx):
        user_data = await get_user(ctx.author.id)
        if user_data.get('has_claimed_starter'): return await ctx.send("❌ Already claimed!")

        loading = await ctx.send("🎁 *Opening Starter Pack...*")
        try:
            async with aiohttp.ClientSession() as session:
                tasks = [self.fetch_character_by_rank(session, *self.get_rarity_and_page(guaranteed_ssr=True))]
                for _ in range(9):
                    tasks.append(self.fetch_character_by_rank(session, *self.get_rarity_and_page()))
                chars = [c for c in await asyncio.gather(*tasks) if c]

            if len(chars) < 10: return await loading.edit(content="❌ Sync Error.")

            await batch_cache_characters(chars)
            await batch_add_to_inventory(ctx.author.id, [c['id'] for c in chars])
            pool = await get_db_pool()
            await pool.execute("UPDATE users SET has_claimed_starter = TRUE WHERE user_id = $1", str(ctx.author.id))
            
            img = await generate_10_pull_image(chars)
            await loading.delete()
            await ctx.send(content="🎉 **Starter Pack Opened!**", file=discord.File(fp=img, filename="starter.png"))
        except Exception as e:
            await ctx.send(f"⚠️ Error: `{e}`")

async def setup(bot):
    await bot.add_cog(Gacha(bot))