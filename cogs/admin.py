# cogs/admin.py

import discord
from discord.ext import commands
import json
from core.database import get_db_pool
from core.skills import get_skill_info, list_all_skills

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="add_skill")
    @commands.is_owner() # Only the bot owner can use this
    async def add_skill(self, ctx, anilist_id: int, skill_name: str):
        """
        Assigns a skill to a character in the global cache.
        Usage: !add_skill 12345 Surge
        """
        skill = get_skill_info(skill_name)
        if not skill:
            await ctx.send(f"❌ Invalid skill. Choose from: `{', '.join(list_all_skills())}`")
            return

        pool = await get_db_pool()
        async with pool.acquire() as conn:
            # 1. Check if character exists in cache
            char = await conn.fetchrow("SELECT name, ability_tags FROM characters_cache WHERE anilist_id = $1", anilist_id)
            
            if not char:
                await ctx.send(f"❌ Character with AniList ID `{anilist_id}` not found in cache. Pull them first!")
                return

            # 2. Prepare the update
            current_tags = json.loads(char['ability_tags'])
            target_skill = skill_name.title()

            if target_skill in current_tags:
                await ctx.send(f"⚠️ **{char['name']}** already has the **{target_skill}** skill.")
                return

            current_tags.append(target_skill)
            
            # 3. Apply DB Update
            # If it's Anchor, we also update the squash_resistance column
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

async def setup(bot):
    await bot.add_cog(Admin(bot))