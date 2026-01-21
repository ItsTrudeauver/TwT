import discord
from discord.ext import commands
import json
import time
import re
import aiohttp
import asyncio
from core.database import get_db_pool, batch_cache_characters
from core.skills import get_skill_info, list_all_skills
from core.image_gen import generate_banner_image

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="add_skill")
    @commands.is_owner()
    async def add_skill(self, ctx, anilist_id: int, *, skill_name: str):
        skill = get_skill_info(skill_name)
        if not skill:
            await ctx.send(f"❌ Invalid skill. Choose from: `{', '.join(list_all_skills())}`")
            return

        pool = await get_db_pool()
        async with pool.acquire() as conn:
            char = await conn.fetchrow("SELECT name, ability_tags FROM characters_cache WHERE anilist_id = $1", anilist_id)
            
            if not char:
                gacha_cog = self.bot.get_cog("Gacha")
                if not gacha_cog: return await ctx.send("❌ Gacha system is offline.")

                loading = await ctx.send(f"🔍 ID `{anilist_id}` not in cache. Fetching from AniList...")
                async with aiohttp.ClientSession() as session:
                    # Default fetch without forced rarity
                    api_data = await gacha_cog.fetch_character_by_id(session, anilist_id)
                
                if not api_data: return await loading.edit(content="❌ Could not find that character or AniList is down.")
                
                await batch_cache_characters([api_data])
                await loading.delete()
                char = await conn.fetchrow("SELECT name, ability_tags FROM characters_cache WHERE anilist_id = $1", anilist_id)

            current_tags = json.loads(char['ability_tags'])
            target_skill = skill_name.title()

            if target_skill in current_tags:
                return await ctx.send(f"⚠️ **{char['name']}** already has the **{target_skill}** skill.")

            current_tags.append(target_skill)
            
            if target_skill == "Anchor":
                await conn.execute("UPDATE characters_cache SET ability_tags=$1, squash_resistance=$2 WHERE anilist_id=$3", 
                                 json.dumps(current_tags), skill['value'], anilist_id)
            else:
                await conn.execute("UPDATE characters_cache SET ability_tags=$1 WHERE anilist_id=$2", 
                                 json.dumps(current_tags), anilist_id)

            await ctx.send(f"✅ Added **{target_skill}** to **{char['name']}**!")

    @commands.command(name="set_banner")
    @commands.is_owner()
    async def set_banner(self, ctx):
        """
        Sets the active banner using bracket syntax.
        Usage: !set_banner [days] [Banner Name] [id:rarity] [id:rarity]...
        Example: !set_banner [14] [Winter Holiday] [176754:SSR] [183965:SR]
        """
        # 1. Custom Parsing with Regex
        content = ctx.message.content
        # Finds all text inside [brackets]
        matches = re.findall(r'\[(.*?)\]', content)

        if len(matches) < 3:
            return await ctx.send("❌ Invalid Format.\nUsage: `!set_banner [days] [Name] [ID:RARITY] ...`")

        try:
            days = int(matches[0])
            name = matches[1]
            unit_args = matches[2:] # List of "ID:RARITY" strings
        except ValueError:
            return await ctx.send("❌ 'Days' must be a number.")

        end_time = int(time.time() + (days * 86400))
        gacha_cog = self.bot.get_cog("Gacha")
        
        # 2. Processing Units
        banner_ids = []
        char_data_list = []

        async with aiohttp.ClientSession() as session:
            for item in unit_args:
                if ":" not in item:
                    return await ctx.send(f"❌ Invalid Unit Format: `{item}`. Use `ID:RARITY` (e.g., `12345:SSR`)")
                
                try:
                    cid_str, rarity_str = item.split(":")
                    cid = int(cid_str.strip())
                    rarity = rarity_str.strip().upper()
                except:
                    return await ctx.send(f"❌ Parse error on `{item}`.")

                if rarity not in ["SSR", "SR", "R"]:
                    return await ctx.send(f"❌ Invalid Rarity `{rarity}`. Use SSR, SR, or R.")

                # Delay to prevent rate limits
                await asyncio.sleep(0.5)

                # Fetch with FORCED RARITY
                data = await gacha_cog.fetch_character_by_id(session, cid, forced_rarity=rarity)
                
                if data:
                    char_data_list.append(data)
                    banner_ids.append(cid)
                    # IMPORTANT: Cache immediately so the database knows this ID = this Rarity
                    await batch_cache_characters([data])
                else:
                    return await ctx.send(f"❌ Could not fetch ID `{cid}` from AniList.")

        if not char_data_list:
            return await ctx.send("❌ No valid characters found.")

        # 3. Generate Banner Image
        banner_img = await generate_banner_image(char_data_list, name, end_time)
        
        # 4. Save to Database
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE banners SET is_active = FALSE")
            await conn.execute("""
                INSERT INTO banners (name, rate_up_ids, is_active, end_timestamp)
                VALUES ($1, $2, TRUE, $3)
            """, name, banner_ids, end_time)
        
        display_time = f"<t:{end_time}:F> (<t:{end_time}:R>)"
        await ctx.send(
            f"✅ **Banner Active: {name}**\nParsed {len(banner_ids)} units.\n📅 **Ends:** {display_time}", 
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
                await conn.execute("DELETE FROM inventory WHERE id = ANY($1)", [c['id'] for c in chars])
                await conn.execute("UPDATE users SET scrap = scrap + $1 WHERE user_id = $2", total_scrap, user_id)
                await ctx.send(f"Scrapped {len(chars)} characters for {total_scrap} scrap.")

    @commands.command(name="override_unit")
    @commands.is_owner()
    async def override_unit(self, ctx, anilist_id: int, rarity: str, power: int):
        """Manually sets rarity and power for a unit and locks it from being updated by standard logic."""
        rarity = rarity.upper()
        if rarity not in ["SSR", "SR", "R"]:
            return await ctx.send("❌ Rarity must be SSR, SR, or R.")

        pool = await get_db_pool()
        async with pool.acquire() as conn:
            # Check if character exists in cache, otherwise fetch basic info first
            char = await conn.fetchrow("SELECT name FROM characters_cache WHERE anilist_id = $1", anilist_id)
            
            # 1. If not in cache, fetch metadata from AniList first
            if not char:
                gacha_cog = self.bot.get_cog("Gacha")
                async with aiohttp.ClientSession() as session:
                    api_data = await gacha_cog.fetch_character_by_id(session, anilist_id)
                if not api_data: 
                    return await ctx.send("❌ Could not find that unit on AniList.")
                
                # Use a direct UPSERT to create the record with the override flag set
                await conn.execute("""
                    INSERT INTO characters_cache (anilist_id, name, image_url, rarity, true_power, is_overridden)
                    VALUES ($1, $2, $3, $4, $5, TRUE)
                    ON CONFLICT (anilist_id) DO UPDATE 
                    SET rarity = EXCLUDED.rarity, 
                        true_power = EXCLUDED.true_power, 
                        is_overridden = TRUE
                """, anilist_id, api_data['name'], api_data['image_url'], rarity, power)
                name = api_data['name']
            else:
                # 2. If it is already in cache, just update the existing row
                await conn.execute("""
                    UPDATE characters_cache 
                    SET rarity = $1, true_power = $2, is_overridden = TRUE 
                    WHERE anilist_id = $3
                """, rarity, power, anilist_id)
                name = char['name']
            
            name = char['name'] if char else data['name']
            await ctx.send(f"✅ **{name}** (ID: {anilist_id}) overridden to **{rarity}** with **{power:,} Power**.")

async def setup(bot):
    await bot.add_cog(Admin(bot))