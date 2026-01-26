import discord
from discord.ext import commands
import random
import os
from core.economy import get_item_display_name
from core.database import get_db_pool
from core.game_math import calculate_effective_power
from core.image_gen import generate_team_image

class RPG(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def get_team_data(self, user_id):
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT slot_1, slot_2, slot_3, slot_4, slot_5 FROM teams WHERE user_id = $1", str(user_id))
            
            if not row:
                return 0, [None] * 5

            team_list = []
            total_power = 0
            slot_ids = [row['slot_1'], row['slot_2'], row['slot_3'], row['slot_4'], row['slot_5']]
            
            for char_id in slot_ids:
                if char_id is None:
                    team_list.append(None)
                    continue
                
                # UPDATED: This query now pulls dupe_level from inventory to calculate boosted power
                #
                # UPDATED SQL
                char_data = await conn.fetchrow("""
                    SELECT 
                        c.name, 
                        c.image_url, 
                        FLOOR(
                            c.true_power 
                            * (1 + (i.dupe_level * 0.05)) 
                            * (1 + (u.team_level * 0.01)) -- Team Level Bonus
                        )::int as true_power, 
                        c.rarity, 
                        c.rarity_override, 
                        c.ability_tags 
                    FROM inventory i
                    JOIN characters_cache c ON i.anilist_id = c.anilist_id
                    JOIN users u ON i.user_id = u.user_id
                    WHERE i.id = $1
                """, char_id)
                
                if char_data:
                    power = int(char_data['true_power'])
                    total_power += power
                    team_list.append({
                        'name': char_data['name'], 
                        'image_url': char_data['image_url'], 
                        'rarity': char_data['rarity_override'] or char_data['rarity'], 
                        'power': power,
                        'ability_tags': char_data['ability_tags']
                    })
                else:
                    team_list.append(None)

            return total_power, team_list

    @commands.command(name="set_team_battle", aliases=['stb', 'sbt', 'st'])
    async def set_team(self, ctx, s1: int, s2: int = None, s3: int = None, s4: int = None, s5: int = None):
        slots = [s1, s2, s3, s4, s5]
        clean_slots = [s for s in slots if s is not None]
        
        if len(set(clean_slots)) != len(clean_slots):
            await ctx.reply("❌ Duplicate IDs detected!")
            return

        pool = await get_db_pool()
        async with pool.acquire() as conn:
            owned = await conn.fetch("SELECT id FROM inventory WHERE user_id = $1 AND id = ANY($2)", 
                                    str(ctx.author.id), clean_slots)
            
            if len(owned) != len(clean_slots):
                await ctx.reply("❌ You do not own one of those IDs.")
                return

            final_slots = clean_slots + [None] * (5 - len(clean_slots))
            await conn.execute("""
                INSERT INTO teams (user_id, slot_1, slot_2, slot_3, slot_4, slot_5)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT(user_id) DO UPDATE SET
                    slot_1=EXCLUDED.slot_1, slot_2=EXCLUDED.slot_2,
                    slot_3=EXCLUDED.slot_3, slot_4=EXCLUDED.slot_4,
                    slot_5=EXCLUDED.slot_5
            """, str(ctx.author.id), *final_slots)
            
            await ctx.reply(f"✅ Squad composition updated.")

    @commands.command(name="team")
    async def view_team(self, ctx, user: discord.Member = None):
        target = user or ctx.author
        loading = await ctx.reply("🛡️ *Analyzing Squad Composition...*")
        power, team_list = await self.get_team_data(target.id)
        
        try:
            image_data = await generate_team_image(team_list)
            file = discord.File(fp=image_data, filename="team_banner.png")
            await loading.delete()
            await ctx.reply(content=f"**Officer:** {target.name} | **Power:** {power:,}", file=file)
        except Exception as e:
            await loading.edit(content=f"⚠️ Visual Error: {e}")

async def setup(bot):
    await bot.add_cog(RPG(bot))