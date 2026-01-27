import discord
from discord.ext import commands
import aiohttp
import random
import os
import asyncio
import json
import time

# Internal imports (Ensure these match your folder structure)
from core.database import get_user, batch_add_to_inventory, batch_cache_characters, get_db_pool
from core.game_math import calculate_effective_power
from core.image_gen import generate_10_pull_image, generate_banner_image
from core.economy import Economy, GEMS_PER_PULL
from core.emotes import Emotes

class Gacha(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.anilist_url = os.getenv("ANILIST_URL", "https://graphql.anilist.co")
        self.rank_map = {}
        self.load_rankings()

    def load_rankings(self):
        try:
            with open("data/rankings.json", "r") as f:
                self.rank_map = json.load(f)
            print(f"✅ [Gacha] Loaded {len(self.rank_map)} characters from rankings.json")
        except FileNotFoundError:
            print("⚠️ [Gacha] 'data/rankings.json' not found. Please run scripts/update_ranks.py")

    def get_cached_rank(self, anilist_id):
        return self.rank_map.get(str(anilist_id), 10001)

    def determine_rarity(self, rank):
        if rank <= 250: return "SSR"
        if rank <= 1500: return "SR"
        return "R"

    def get_rarity_and_page(self, guaranteed_ssr=False):
        if guaranteed_ssr: return "SSR", random.randint(1, 250)
        
        roll = random.random() * 100
        if roll < 2:  return "SSR", random.randint(1, 250)
        if roll < 13: return "SR", random.randint(251, 1500)
        return "R", random.randint(1501, 10000)

    async def get_active_banner(self):
        pool = await get_db_pool()
        current_time = int(time.time())
        banner = await pool.fetchrow("SELECT * FROM banners WHERE is_active = TRUE AND end_timestamp > $1 LIMIT 1", current_time)
        
        if not banner:
            # Auto-close expired banners
            await pool.execute("UPDATE banners SET is_active = FALSE WHERE is_active = TRUE AND end_timestamp <= $1", current_time)
            return None
            
        return banner

    async def process_spark_points(self, user_id, banner_id, amount):
        """Adds spark points and resets if the banner has changed."""
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            user = await conn.fetchrow("SELECT banner_points, last_banner_id FROM users WHERE user_id = $1", str(user_id))
            
            current_points = user['banner_points'] if user and user['banner_points'] is not None else 0
            last_id = user['last_banner_id'] if user and user['last_banner_id'] is not None else -1
            
            if last_id != banner_id:
                current_points = 0
            
            new_points = current_points + amount
            
            await conn.execute("""
                UPDATE users 
                SET banner_points = $1, last_banner_id = $2 
                WHERE user_id = $3
            """, new_points, banner_id, str(user_id))
            
            return new_points

    async def fetch_banner_pull(self, session, banner):
        """Logic for pulling from a specific banner (handling rate-ups)."""
        rarity, page = self.get_rarity_and_page()
        
        # Check Rate-up Chance
        if rarity in ["SSR", "SR"] and random.random() < banner['rate_up_chance']:
            pool = await get_db_pool()
            possible_hits = await pool.fetch("""
                SELECT anilist_id FROM characters_cache 
                WHERE anilist_id = ANY($1) AND rarity = $2
            """, banner['rate_up_ids'], rarity)
            
            if possible_hits:
                target_id = random.choice(possible_hits)['anilist_id']
                return await self.fetch_character_by_id(session, target_id)

        # Fallback to standard pool
        return await self.fetch_character_by_rank(session, rarity, page)

    async def fetch_character_by_id(self, session, anilist_id: int, forced_rarity=None):
        """Fetches character data from AniList by ID."""
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
                
                if forced_rarity:
                    rarity = forced_rarity
                    rank = 1 if rarity == "SSR" else 500
                else:
                    rank = self.get_cached_rank(anilist_id)
                    rarity = self.determine_rarity(rank)
                
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
        """Fetches a character from AniList by rank/page."""
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
        banner = await self.get_active_banner()
        if not banner:
            return await ctx.reply("🎫 No banner is currently active.")

        loading = await ctx.reply("🔍 *Retrieving banner details...*")
        try:
            async with aiohttp.ClientSession() as session:
                tasks = [self.fetch_character_by_id(session, cid) for cid in banner['rate_up_ids']]
                character_list = [c for c in await asyncio.gather(*tasks) if c]

            if not character_list:
                return await loading.edit(content="❌ Could not fetch character data from the API.")

            img_output = await generate_banner_image(character_list, banner['name'], banner['end_timestamp'])
            
            await loading.delete()
            await ctx.reply(file=discord.File(fp=img_output, filename="banner.png"))
        except Exception as e:
            await loading.delete()
            await ctx.reply(f"⚠️ Error displaying banner: `{e}`")
        
    @commands.command(name="pull", aliases=["summon"])
    async def pull_character(self, ctx, amount: int = 1):
        """Pulls 1 or 10 characters from the gacha."""
        if amount not in [1, 10]: return await ctx.reply("❌ Only 1 or 10 pulls allowed.")
        
        # 1. Calculate Cost
        cost = amount * GEMS_PER_PULL
        
        # 2. ATOMIC DEDUCTION (Solves Negative Balance / Spam)
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            # This query will return None if they don't have enough gems, effectively blocking the pull
            deduction = await conn.fetchrow("""
                UPDATE users 
                SET gacha_gems = gacha_gems - $1 
                WHERE user_id = $2 AND gacha_gems >= $1 
                RETURNING gacha_gems
            """, cost, str(ctx.author.id))

        if not deduction:
            # Fetch actual balance only to display the error message
            user_data = await get_user(ctx.author.id) 
            return await ctx.reply(f"❌ Need **{cost:,} {Emotes.GEMS}**. Balance: **{user_data['gacha_gems']:,}**")

        loading = await ctx.reply(f"🎰 *Pulling {amount}x...*")
        
        # 3. SAFETY BLOCK (Solves API Errors & Refunds)
        try:
            banner = await self.get_active_banner()
            
            # --- PROCESS SPARK ---
            spark_points_now = 0
            spark_status = ""

            if banner:
                spark_points_now = await self.process_spark_points(ctx.author.id, banner['id'], amount)
                spark_status = f"{Emotes.SPARK} **Spark:** {spark_points_now}/300"
            else:
                spark_status = "⚠️ Standard Pool (No Spark)"

            # --- API FETCHING (Parallelized for Speed) ---
            async with aiohttp.ClientSession() as session:
                tasks = []
                for _ in range(amount):
                    if banner: 
                        tasks.append(self.fetch_banner_pull(session, banner))
                    else:
                        r, p = self.get_rarity_and_page()
                        tasks.append(self.fetch_character_by_rank(session, r, p))
                
                # Run all fetches at once
                pulled_chars = [c for c in await asyncio.gather(*tasks) if c]

            # If the list is empty, the API likely failed completely
            if not pulled_chars: 
                raise Exception("API returned no characters (Rate Limit or Downtime).")

            # Save to database
            await batch_cache_characters(pulled_chars)
            scrapped_gems, scrapped_coins = await batch_add_to_inventory(ctx.author.id, pulled_chars)
            
            # --- SINGLE PULL RESPONSE ---
            if amount == 1:
                c = pulled_chars[0]
                row = await pool.fetchrow("SELECT dupe_level FROM inventory WHERE user_id = $1 AND anilist_id = $2", str(ctx.author.id), c['id'])
                dupe_lv = row['dupe_level'] if row else 0
                boosted_power = int(c['true_power'] * (1 + (dupe_lv * 0.05)))
                
                desc = f"**{c['rarity']}** | Power: **{boosted_power:,}** (Lv.{dupe_lv})"
                
                if scrapped_gems > 0 or scrapped_coins > 0:
                    rewards = []
                    if scrapped_gems > 0: rewards.append(f"**{scrapped_gems:,} {Emotes.GEMS}**")
                    if scrapped_coins > 0: rewards.append(f"**{scrapped_coins:,} {Emotes.COINS}**")
                    desc += f"\n♻️ **Max Dupes!** Scrapped for {' and '.join(rewards)}"
                
                title_text = f"{spark_status} | {c['name']}" if spark_status else f"✨ {c['name']}"

                embed = discord.Embed(title=title_text, description=desc, color=0xFFD700)
                embed.set_image(url=c['image_url'])
                
                await loading.delete()
                await ctx.reply(embed=embed)
            
            # --- 10-PULL RESPONSE ---
            else:
                # Generate the composite image
                img = await generate_10_pull_image(pulled_chars)
                await loading.delete()
                
                embed = discord.Embed(color=0x2ECC71)
                embed.title = f"{spark_status}"
                embed.set_image(url="attachment://10pull.png")
                
                if scrapped_gems > 0 or scrapped_coins > 0:
                    rewards = []
                    if scrapped_gems > 0: rewards.append(f"**{scrapped_gems:,} {Emotes.GEMS}**")
                    if scrapped_coins > 0: rewards.append(f"**{scrapped_coins:,} {Emotes.COINS}**")
                    embed.description = f"♻️ **Auto-scrapped extras for {' and '.join(rewards)}!**"
                
                file = discord.File(fp=img, filename="10pull.png")
                await ctx.reply(file=file, embed=embed)

        except Exception as e:
            # 4. AUTO-REFUND ON FAILURE
            # If anything in the 'try' block fails, we give the money back.
            await pool.execute("UPDATE users SET gacha_gems = gacha_gems + $1 WHERE user_id = $2", cost, str(ctx.author.id))
            print(f"⚠️ Refunded {cost} gems to {ctx.author.id} due to error: {e}")
            
            try: await loading.delete()
            except: pass
            
            await ctx.reply(f"⚠️ **Error:** `{e}`\n💎 **Your gems have been automatically refunded.**")

    @commands.command(name="starter")
    async def starter_pull(self, ctx):
        """Claims the one-time starter pack (10 characters, 1 guaranteed SSR)."""
        user_data = await get_user(ctx.author.id)
        if user_data.get('has_claimed_starter'): return await ctx.reply("❌ Already claimed!")

        loading = await ctx.reply("🎁 *Opening Starter Pack...*")
        try:
            async with aiohttp.ClientSession() as session:
                tasks = [self.fetch_character_by_rank(session, *self.get_rarity_and_page(guaranteed_ssr=True))]
                for _ in range(9):
                    tasks.append(self.fetch_character_by_rank(session, *self.get_rarity_and_page()))
                
                chars = [c for c in await asyncio.gather(*tasks) if c]

            if len(chars) < 10: return await loading.edit(content="❌ Sync Error. Please try again.")

            await batch_cache_characters(chars)
            await batch_add_to_inventory(ctx.author.id, chars)
            
            pool = await get_db_pool()
            await pool.execute("UPDATE users SET has_claimed_starter = TRUE WHERE user_id = $1", str(ctx.author.id))
            
            img = await generate_10_pull_image(chars)
            await loading.delete()
            await ctx.reply(content="🎉 **Starter Pack Opened!**", file=discord.File(fp=img, filename="starter.png"))
        except Exception as e:
            await ctx.reply(f"⚠️ Error: `{e}`")

# --- MANDATORY SETUP FUNCTION ---
async def setup(bot):
    await bot.add_cog(Gacha(bot))