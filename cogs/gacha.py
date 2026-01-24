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
            await pool.execute("UPDATE banners SET is_active = FALSE WHERE is_active = TRUE AND end_timestamp <= $1", current_time)
            
        return banner

    async def process_spark_points(self, user_id, banner_id, amount):
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            user = await conn.fetchrow("SELECT banner_points, last_banner_id FROM users WHERE user_id = $1", str(user_id))
            
            current_points = user['banner_points'] if user else 0
            last_id = user['last_banner_id'] if user else -1
            
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
        rarity, page = self.get_rarity_and_page()
        
        if rarity in ["SSR", "SR"] and random.random() < banner['rate_up_chance']:
            pool = await get_db_pool()
            possible_hits = await pool.fetch("""
                SELECT anilist_id FROM characters_cache 
                WHERE anilist_id = ANY($1) AND rarity = $2
            """, banner['rate_up_ids'], rarity)
            
            if possible_hits:
                target_id = random.choice(possible_hits)['anilist_id']
                return await self.fetch_character_by_id(session, target_id)

        return await self.fetch_character_by_rank(session, rarity, page)

    async def fetch_character_by_id(self, session, anilist_id: int, forced_rarity=None):
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

            from core.image_gen import generate_banner_image
            img_output = await generate_banner_image(character_list, banner['name'], banner['end_timestamp'])
            
            await loading.delete()
            await ctx.reply(file=discord.File(fp=img_output, filename="banner.png"))
        except Exception as e:
            await ctx.reply(f"⚠️ Error displaying banner: `{e}`")
        
    @commands.command(name="pull", aliases=["summon"])
    async def pull_character(self, ctx, amount: int = 1):
        if amount not in [1, 10]: return await ctx.reply("❌ Only 1 or 10 pulls allowed.")
        user_data = await get_user(ctx.author.id)
        cost = amount * GEMS_PER_PULL
        is_free = await Economy.is_free_pull(ctx.author, self.bot)

        if not is_free and user_data['gacha_gems'] < cost:
            return await ctx.reply(f"❌ Need **{cost:,} {Emotes.GEMS}**. Balance: **{user_data['gacha_gems']:,}**")

        loading = await ctx.reply(f"🎰 *Pulling {amount}x...*")
        try:
            banner = await self.get_active_banner()
            pool = await get_db_pool()
            
            # --- CURRENCY & SPARK LOGIC ---
            spark_points_now = 0
            
            # 1. Fetch current points (for display) even if free
            if banner:
                user_spark = await pool.fetchrow("SELECT banner_points, last_banner_id FROM users WHERE user_id = $1", str(ctx.author.id))
                if user_spark and user_spark['last_banner_id'] == banner['id']:
                    spark_points_now = user_spark['banner_points']
                else:
                    spark_points_now = 0 # Will be 0 or reset

            # 2. Consume Gems & Add Points (if not free)
            if not is_free:
                await pool.execute("UPDATE users SET gacha_gems = gacha_gems - $1 WHERE user_id = $2", cost, str(ctx.author.id))
                if banner:
                    spark_points_now = await self.process_spark_points(ctx.author.id, banner['id'], amount)

            # --- API FETCHING ---
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
            scrapped_gems = await batch_add_to_inventory(ctx.author.id, pulled_chars)
            
            # --- FOOTER TEXT GENERATION ---
            footer_text = ""
            if banner:
                spark_emote = getattr(Emotes, "SPARK", "✨") 
                footer_text = f"{spark_emote} Spark Points: {spark_points_now}/200"

            # --- SINGLE PULL RESPONSE ---
            if amount == 1:
                c = pulled_chars[0]
                row = await pool.fetchrow("SELECT dupe_level FROM inventory WHERE user_id = $1 AND anilist_id = $2", str(ctx.author.id), c['id'])
                dupe_lv = row['dupe_level'] if row else 0
                boosted_power = int(c['true_power'] * (1 + (dupe_lv * 0.05)))
                
                desc = f"**{c['rarity']}** | Power: **{boosted_power:,}** (Lv.{dupe_lv})"
                if scrapped_gems > 0:
                    desc += f"\n♻️ **Max Dupes!** Scrapped for **{scrapped_gems:,} {Emotes.GEMS}**"
                
                embed = discord.Embed(title=f"✨ {c['name']}", description=desc, color=0xFFD700)
                embed.set_image(url=c['image_url'])
                if footer_text: embed.set_footer(text=footer_text)
                
                await loading.delete()
                await ctx.reply(embed=embed)
            
            # --- 10-PULL RESPONSE (FIXED) ---
            else:
                img = await generate_10_pull_image(pulled_chars)
                await loading.delete()
                
                # We always create an embed now to hold the image + footer
                embed = discord.Embed(color=0x2ECC71)
                embed.set_image(url="attachment://10pull.png")
                
                if scrapped_gems > 0:
                    embed.description = f"♻️ **Auto-scrapped extras for {scrapped_gems:,} {Emotes.GEMS}!**"
                
                if footer_text:
                    embed.set_footer(text=footer_text)
                
                # Send File + Embed together
                file = discord.File(fp=img, filename="10pull.png")
                await ctx.reply(file=file, embed=embed)

        except Exception as e:
            await ctx.reply(f"⚠️ Error: `{e}`")

    @commands.command(name="starter")
    async def starter_pull(self, ctx):
        user_data = await get_user(ctx.author.id)
        if user_data.get('has_claimed_starter'): return await ctx.reply("❌ Already claimed!")

        loading = await ctx.reply("🎁 *Opening Starter Pack...*")
        try:
            async with aiohttp.ClientSession() as session:
                tasks = [self.fetch_character_by_rank(session, *self.get_rarity_and_page(guaranteed_ssr=True))]
                for _ in range(9):
                    tasks.append(self.fetch_character_by_rank(session, *self.get_rarity_and_page()))
                
                chars = [c for c in await asyncio.gather(*tasks) if c]

            if len(chars) < 10: return await loading.edit(content="❌ Sync Error.")

            await batch_cache_characters(chars)
            scrapped_gems = await batch_add_to_inventory(ctx.author.id, chars)
            pool = await get_db_pool()
            await pool.execute("UPDATE users SET has_claimed_starter = TRUE WHERE user_id = $1", str(ctx.author.id))
            
            img = await generate_10_pull_image(chars)
            await loading.delete()
            await ctx.reply(content="🎉 **Starter Pack Opened!**", file=discord.File(fp=img, filename="starter.png"))
        except Exception as e:
            await ctx.reply(f"⚠️ Error: `{e}`")

async def setup(bot):
    await bot.add_cog(Gacha(bot))