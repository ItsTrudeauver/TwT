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
        """Rolls rarity tier first, then selects a rank/page within that range."""
        if guaranteed_ssr:
            return "SSR", random.randint(1, 250)
            
        roll = random.random() * 100
        if roll < 3:  return "SSR", random.randint(1, 250)
        if roll < 15: return "SR", random.randint(251, 1500)
        return "R", random.randint(1501, 10000)

    async def get_active_banner(self):
        pool = await get_db_pool()
        current_time = int(time.time())
        
        # Only fetch the banner if it is active AND has not expired
        banner = await pool.fetchrow("""
            SELECT * FROM banners 
            WHERE is_active = TRUE AND end_timestamp > $1 
            LIMIT 1
        """, current_time)
        
        # If a banner expired but is still marked 'is_active', clean it up
        if not banner:
            await pool.execute("UPDATE banners SET is_active = FALSE WHERE is_active = TRUE AND end_timestamp <= $1", current_time)
            
        return banner

    async def fetch_banner_pull(self, session, banner):
        """Modified pull logic that accounts for rate-ups."""
        rarity, page = self.get_rarity_and_page()
        
        # If we rolled a high rarity, check for rate-up hit
        if rarity in ["SSR", "SR"] and random.random() < banner['rate_up_chance']:
            # Select a random ID from the rate-up list
            target_id = random.choice(banner['rate_up_ids'])
            # Use fetch_character_by_id logic
            return await self.fetch_character_by_id(session, target_id)
        
        # Otherwise, proceed with a normal random pull
        return await self.fetch_character_by_rank(session, rarity, page)

    async def fetch_character_by_id(self, session, anilist_id: int):
        """Fetches a specific character by ID and calculates their rank and rarity."""
        char_query = """
        query ($id: Int) {
            Character(id: $id) {
                id
                name { full }
                image { large }
                favourites
            }
        }
        """
        rank_query = """
        query ($favs: Int) {
            Page(perPage: 1) {
                pageInfo { total }
                characters(favourites_greater: $favs, sort: FAVOURITES_DESC) { id }
            }
        }
        """
        
        try:
            # --- STEP 1: FETCH CHARACTER ---
            async with session.post(self.anilist_url, json={'query': char_query, 'variables': {'id': anilist_id}}) as resp:
                if resp.status != 200:
                    print(f"⚠️ ID {anilist_id} HTTP Error: {resp.status}")
                    return None
                
                response_json = await resp.json()
                
                if 'errors' in response_json:
                    print(f"⚠️ AniList API Error for ID {anilist_id}: {response_json['errors'][0]['message']}")
                    return None
                
                if not response_json.get('data') or not response_json['data'].get('Character'):
                    print(f"⚠️ ID {anilist_id} returned NULL data.")
                    return None

                char_data = response_json['data']['Character']

            # --- STEP 2: FETCH RANK (With Safety Checks) ---
            async with session.post(self.anilist_url, json={'query': rank_query, 'variables': {'favs': char_data['favourites']}}) as resp:
                if resp.status != 200:
                    print(f"⚠️ Rank Query HTTP Error for ID {anilist_id}: {resp.status}")
                    return None
                
                rank_data = await resp.json()

                # FIX: Check if data exists before accessing it
                if not rank_data.get('data') or not rank_data['data'].get('Page'):
                    print(f"⚠️ Rank Query returned NULL data for ID {anilist_id}. (Likely Rate Limit)")
                    return None

                rank = rank_data['data']['Page']['pageInfo']['total'] + 1

            # --- STEP 3: CALCULATE STATS ---
            if rank <= 250: rarity = "SSR"
            elif rank <= 1500: rarity = "SR"
            else: rarity = "R"

            true_p = calculate_effective_power(char_data['favourites'], rarity, rank)
            
            return {
                'id': char_data['id'],
                'name': char_data['name']['full'],
                'image_url': char_data['image']['large'],
                'favs': char_data['favourites'],
                'rarity': rarity,
                'page': rank,
                'true_power': true_p
            }
        except Exception as e:
            print(f"❌ Crash on ID {anilist_id}: {e}")
            return None

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
            banner = await self.get_active_banner()
            
            # Deduct gems if not free
            if not is_free:
                pool = await get_db_pool()
                await pool.execute("UPDATE users SET gacha_gems = gacha_gems - $1 WHERE user_id = $2", cost, str(ctx.author.id))

            async with aiohttp.ClientSession() as session:
                tasks = []
                for _ in range(amount):
                    if banner:
                        tasks.append(self.fetch_banner_pull(session, banner))
                    else:
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