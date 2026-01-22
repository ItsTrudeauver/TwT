import discord
from discord.ext import commands
import aiohttp
import random
import os
import asyncio
import json
import time

from core.database import get_user, batch_add_to_inventory, batch_cache_characters, get_db_pool
from core.game_math import calculate_effective_power
from core.image_gen import generate_10_pull_image
from core.economy import Economy, GEMS_PER_PULL

class Gacha(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.anilist_url = os.getenv("ANILIST_URL", "https://graphql.anilist.co")
        self.rank_map = {}
        self.load_rankings()

    def load_rankings(self):
        """Loads the scraped ID -> Rank map from JSON."""
        try:
            with open("data/rankings.json", "r") as f:
                self.rank_map = json.load(f)
            print(f"✅ [Gacha] Loaded {len(self.rank_map)} characters from rankings.json")
        except FileNotFoundError:
            print("⚠️ [Gacha] 'data/rankings.json' not found. Please run scripts/update_ranks.py")

    def get_cached_rank(self, anilist_id):
        """
        Returns the exact rank from the JSON file.
        If the character isn't in the top 10,000, we treat them as Rank 10,001.
        """
        return self.rank_map.get(str(anilist_id), 10001)

    def determine_rarity(self, rank):
        if rank <= 250: return "SSR"
        if rank <= 1500: return "SR"
        return "R"

    def get_rarity_and_page(self, guaranteed_ssr=False):
        """
        Determines which 'Page' (Rank) to pull from.
        """
        if guaranteed_ssr: return "SSR", random.randint(1, 250)
        
        roll = random.random() * 100
        if roll < 1:  return "SSR", random.randint(1, 250)
        if roll < 10: return "SR", random.randint(251, 1500)
        # Pulls from the remainder of your 10k database
        return "R", random.randint(1501, 10000)

    async def get_active_banner(self):
        pool = await get_db_pool()
        current_time = int(time.time())
        banner = await pool.fetchrow("SELECT * FROM banners WHERE is_active = TRUE AND end_timestamp > $1 LIMIT 1", current_time)
        
        # Auto-close expired banners
        if not banner:
            await pool.execute("UPDATE banners SET is_active = FALSE WHERE is_active = TRUE AND end_timestamp <= $1", current_time)
            
        return banner

    async def fetch_banner_pull(self, session, banner):
        """
        If a user rolls SSR/SR, check if they get a banner unit.
        """
        rarity, page = self.get_rarity_and_page()
        
        if rarity in ["SSR", "SR"] and random.random() < banner['rate_up_chance']:
            pool = await get_db_pool()
            # Find banner IDs that match the rolled rarity
            possible_hits = await pool.fetch("""
                SELECT anilist_id FROM characters_cache 
                WHERE anilist_id = ANY($1) AND rarity = $2
            """, banner['rate_up_ids'], rarity)
            
            if possible_hits:
                target_id = random.choice(possible_hits)['anilist_id']
                # Fetch specific ID using our JSON lookup
                return await self.fetch_character_by_id(session, target_id)

        # Fallback to random pull
        return await self.fetch_character_by_rank(session, rarity, page)

    async def fetch_character_by_id(self, session, anilist_id: int, forced_rarity=None):
        """
        Fetches character metadata (Name/Image) from API, 
        but gets Rank/Rarity/Power directly from JSON.
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
                if not data.get('data') or not data['data'].get('Character'): return None

                char_data = data['data']['Character']
                
                # --- BACKWARDS LOOKUP ---
                if forced_rarity:
                    rarity = forced_rarity
                    rank = 1 if rarity == "SSR" else 500
                else:
                    # Look up the ID in our JSON map
                    rank = self.get_cached_rank(anilist_id)
                    rarity = self.determine_rarity(rank)
                
                # Check for existing manual override in DB
                pool = await get_db_pool()
                override = await pool.fetchrow("SELECT rarity, true_power, is_overridden FROM characters_cache WHERE anilist_id = $1", char_data['id'])
                
                if override and override['is_overridden']:
                    rarity = override['rarity']
                    true_p = override['true_power']
                else:
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
            print(f"❌ Error fetching ID {anilist_id}: {e}")
            return None

    async def fetch_character_by_rank(self, session, rarity, page):
        """
        Fetches a character by their Rank (Page) from AniList.
        Double-checks the rank against our JSON to be consistent.
        """
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
                        
                        # Check for existing manual override in DB
                        pool = await get_db_pool()
                        override = await pool.fetchrow("SELECT rarity, true_power, is_overridden FROM characters_cache WHERE anilist_id = $1", char['id'])
                        
                        if override and override['is_overridden']:
                            rarity = override['rarity']
                            true_p = override['true_power']
                        else:
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

    @commands.command(name="banner")
    async def current_banner(self, ctx):
        """Displays the currently active gacha banner."""
        # 1. Retrieve the active banner record from the database
        banner = await self.get_active_banner()
        if not banner:
            return await ctx.send("🎫 No banner is currently active.")

        loading = await ctx.send("🔍 *Retrieving banner details...*")
        
        try:
            # 2. Fetch metadata (especially image URLs) for each rate-up ID
            async with aiohttp.ClientSession() as session:
                tasks = [self.fetch_character_by_id(session, cid) for cid in banner['rate_up_ids']]
                # fetch_character_by_id returns a dict with 'image_url'
                character_list = [c for c in await asyncio.gather(*tasks) if c]

            if not character_list:
                return await loading.edit(content="❌ Could not fetch character data from the API.")

            # 3. Generate the image using the existing image_gen utility
            # Ensure generate_banner_image is imported from core.image_gen
            from core.image_gen import generate_banner_image
            img_output = await generate_banner_image(
                character_list, 
                banner['name'], 
                banner['end_timestamp']
            )
            
            # 4. Clean up and send the image
            await loading.delete()
            await ctx.send(file=discord.File(fp=img_output, filename="banner.png"))
            
        except Exception as e:
            await ctx.send(f"⚠️ Error displaying banner: `{e}`")
        
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
                    if banner: tasks.append(self.fetch_banner_pull(session, banner))
                    else:
                        r, p = self.get_rarity_and_page()
                        tasks.append(self.fetch_character_by_rank(session, r, p))
                
                pulled_chars = [c for c in await asyncio.gather(*tasks) if c]

            if not pulled_chars: return await loading.edit(content="❌ Database/API Error.")

            await batch_cache_characters(pulled_chars)
            # Pass full objects to handle scrap logic
            scrapped_gems = await batch_add_to_inventory(ctx.author.id, pulled_chars)

            if amount == 1:
                c = pulled_chars[0]
                # Fetch new dupe level to show "Boosted Power"
                pool = await get_db_pool()
                row = await pool.fetchrow("SELECT dupe_level FROM inventory WHERE user_id = $1 AND anilist_id = $2", str(ctx.author.id), c['id'])
                dupe_lv = row['dupe_level'] if row else 0
                boosted_power = int(c['true_power'] * (1 + (dupe_lv * 0.05)))
                
                desc = f"**{c['rarity']}** | Power: **{boosted_power:,}** (Lv.{dupe_lv})"
                if scrapped_gems > 0:
                    desc += f"\n♻️ **Max Dupes!** Scrapped for **{scrapped_gems:,} Gems**"
                
                embed = discord.Embed(title=f"✨ {c['name']}", description=desc, color=0xFFD700)
                embed.set_image(url=c['image_url'])
                await loading.delete()
                await ctx.send(embed=embed)
            else:
                img = await generate_10_pull_image(pulled_chars)
                await loading.delete()
                msg = f"♻️ **Auto-scrapped extras for {scrapped_gems:,} Gems!**" if scrapped_gems > 0 else ""
                await ctx.send(content=msg, file=discord.File(fp=img, filename="10pull.png"))

        except Exception as e:
            await ctx.send(f"⚠️ Error: `{e}`")

    @commands.command(name="starter")
    async def starter_pull(self, ctx):
        user_data = await get_user(ctx.author.id)
        if user_data.get('has_claimed_starter'): return await ctx.send("❌ Already claimed!")

        loading = await ctx.send("🎁 *Opening Starter Pack...*")
        try:
            async with aiohttp.ClientSession() as session:
                # 1 Guaranteed SSR + 9 Random
                tasks = [self.fetch_character_by_rank(session, *self.get_rarity_and_page(guaranteed_ssr=True))]
                for _ in range(9):
                    tasks.append(self.fetch_character_by_rank(session, *self.get_rarity_and_page()))
                
                chars = [c for c in await asyncio.gather(*tasks) if c]

            if len(chars) < 10: return await loading.edit(content="❌ Sync Error.")

            await batch_cache_characters(chars)
            # Pass full objects to handle potential scrap logic (though unlikely for starter)
            scrapped_gems = await batch_add_to_inventory(ctx.author.id, chars)
            pool = await get_db_pool()
            await pool.execute("UPDATE users SET has_claimed_starter = TRUE WHERE user_id = $1", str(ctx.author.id))
            
            img = await generate_10_pull_image(chars)
            await loading.delete()
            await ctx.send(content="🎉 **Starter Pack Opened!**", file=discord.File(fp=img, filename="starter.png"))
        except Exception as e:
            await ctx.send(f"⚠️ Error: `{e}`")

async def setup(bot):
    await bot.add_cog(Gacha(bot))