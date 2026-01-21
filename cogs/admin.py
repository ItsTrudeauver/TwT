import discord
from discord.ext import commands
import json
import time
import aiohttp
import asyncio  # <--- Added for sleep
from core.database import get_db_pool, batch_cache_characters
from core.skills import get_skill_info, list_all_skills
from core.image_gen import generate_banner_image

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="add_skill")
    @commands.is_owner()
    async def add_skill(self, ctx, anilist_id: int, skill_name: str):
        skill = get_skill_info(skill_name)
        if not skill:
            await ctx.send(f"❌ Invalid skill. Choose from: `{', '.join(list_all_skills())}`")
            return

        pool = await get_db_pool()
        async with pool.acquire() as conn:
            # 1. Check if character exists in cache
            char = await conn.fetchrow("SELECT name, ability_tags FROM characters_cache WHERE anilist_id = $1", anilist_id)
            
            # 2. If MISSING, fetch and cache immediately
            if not char:
                gacha_cog = self.bot.get_cog("Gacha")
                if not gacha_cog:
                    return await ctx.send("❌ Gacha system is offline.")

                loading = await ctx.send(f"🔍 ID `{anilist_id}` not in cache. Fetching from AniList...")
                
                async with aiohttp.ClientSession() as session:
                    api_data = await gacha_cog.fetch_character_by_id(session, anilist_id)
                
                if not api_data:
                    return await loading.edit(content="❌ Could not find that character or AniList is down.")
                
                # Cache them globally
                await batch_cache_characters([api_data])
                await loading.delete()
                
                # Retrieve the newly cached row
                char = await conn.fetchrow("SELECT name, ability_tags FROM characters_cache WHERE anilist_id = $1", anilist_id)

            # 3. Apply DB Update
            current_tags = json.loads(char['ability_tags'])
            target_skill = skill_name.title()

            if target_skill in current_tags:
                await ctx.send(f"⚠️ **{char['name']}** already has the **{target_skill}** skill.")
                return

            current_tags.append(target_skill)
            
            if target_skill == "Anchor":
                await conn.execute("""
                    UPDATE characters_cache 
                    SET ability_tags = $1, squash_resistance = $2 
                    WHERE anilist_id = $3
                """, json.dumps(current_tags), skill['value'], anilist_id)
            else:
                await conn.execute("""
                    UPDATE characters_cache 
                    SET ability_tags = $1 
                    WHERE anilist_id = $2
                """, json.dumps(current_tags), anilist_id)

            await ctx.send(f"✅ Added **{target_skill}** to **{char['name']}**!")

    @add_skill.error
    async def add_skill_error(self, ctx, error):
        if isinstance(error, commands.NotOwner):
            await ctx.send("🚫 This command is reserved for the bot administrator.")

    @commands.command(name="set_banner")
    @commands.is_owner()
    async def set_banner(self, ctx, days: int, name: str, *anilist_ids: int):
        """
        Sets the active banner.
        Usage: !set_banner <days> <name> <id1> <id2> ...
        """
        # 1. Calculate Unix Timestamp
        end_time = int(time.time() + (days * 86400))
        
        gacha_cog = self.bot.get_cog("Gacha")
        async with aiohttp.ClientSession() as session:
            char_data = []
            for cid in anilist_ids:
                # --- SAFETY DELAY ---
                # Waits 0.5s between requests to prevent AniList rate limits/burst errors
                await asyncio.sleep(0.5) 
                
                data = await gacha_cog.fetch_character_by_id(session, cid)
                if data:
                    char_data.append(data)
                    # Ensure they are in the global cache for pulls
                    await batch_cache_characters([data])
                else:
                    await ctx.send(f"⚠️ Warning: Could not fetch ID `{cid}`. Skipping...")
            
            if not char_data:
                return await ctx.send("❌ Could not fetch data for any provided IDs.")

            # 2. Generate Banner Image (Pillow)
            banner_img = await generate_banner_image(char_data, name, end_time)
            
            # 3. Update Database
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                # Deactivate current banners
                await conn.execute("UPDATE banners SET is_active = FALSE")
                # Insert new banner
                await conn.execute("""
                    INSERT INTO banners (name, rate_up_ids, is_active, end_timestamp)
                    VALUES ($1, $2, TRUE, $3)
                """, name, list(anilist_ids), end_time)
            
            # 4. Success Message with Discord Unix Formatting
            display_time = f"<t:{end_time}:F> (<t:{end_time}:R>)"
            
            await ctx.send(
                f"✅ **Banner Active: {name}**\n📅 **Ends:** {display_time}", 
                file=discord.File(fp=banner_img, filename="banner.png")
            )

    @commands.command()
    @commands.is_owner()
    async def mass_scrap_r_rarity(self, ctx, user_id: str):
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                chars = await conn.fetch("""
                    SELECT i.id, c.true_power FROM inventory i 
                    JOIN characters_cache c ON i.anilist_id = c.anilist_id 
                    WHERE i.user_id = $1 AND c.rarity = 'R' AND i.is_locked = FALSE
                """, user_id)
                if not chars:
                    return await ctx.send("No scrapable R characters found.")
                
                total_scrap = sum(int(c['true_power'] * 0.1) for c in chars)
                
                # Delete items
                await conn.execute("DELETE FROM inventory WHERE id = ANY($1)", [c['id'] for c in chars])
                # Add scrap
                await conn.execute("UPDATE users SET scrap = scrap + $1 WHERE user_id = $2", total_scrap, user_id)
                
                await ctx.send(f"Scrapped {len(chars)} characters for {total_scrap} scrap.")

async def setup(bot):
    await bot.add_cog(Admin(bot))