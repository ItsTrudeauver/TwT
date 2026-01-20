import discord
from discord.ext import commands
import aiosqlite
import random
import os

from core.database import DB_PATH
from core.game_math import calculate_effective_power, simulate_standoff
from core.image_gen import generate_team_image

class RPG(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def get_team_data(self, user_id):
        """
        Fetches full team data for Image Generation + Calculation.
        Returns: (Total Power, List of Character Dicts)
        """
        async with aiosqlite.connect(DB_PATH) as db:
            # 1. Get Slot IDs
            async with db.execute("SELECT slot_1, slot_2, slot_3, slot_4, slot_5 FROM teams WHERE user_id = ?", (str(user_id),)) as cursor:
                row = await cursor.fetchone()
            
            if not row:
                return 0, [None] * 5

            # 2. Build the Team List (preserving empty slots)
            team_list = []
            total_power = 0
            
            for char_id in row:
                if char_id is None:
                    team_list.append(None)
                    continue
                
                # Fetch details for this slot
                # We do individual queries to preserve order (Slot 1, Slot 2...)
                # Optimized approach would use IN clause + Python map, but this is safer for ordering
                async with db.execute("""
                    SELECT c.name, c.image_url, c.base_power, c.rarity_override 
                    FROM inventory i
                    JOIN characters_cache c ON i.anilist_id = c.anilist_id
                    WHERE i.id = ?
                """, (char_id,)) as cursor:
                    char_data = await cursor.fetchone()
                
                if char_data:
                    name, img, raw_favs, rarity_ov = char_data
                    
                    # Calculate Rarity (Fallback logic if not stored)
                    rarity = "R"
                    if raw_favs >= 50000: rarity = "SSR"
                    elif raw_favs >= 10000: rarity = "SR"
                    # Allow override
                    if rarity_ov: rarity = rarity_ov

                    power = calculate_effective_power(raw_favs)
                    total_power += power
                    
                    team_list.append({
                        'name': name,
                        'image_url': img,
                        'rarity': rarity,
                        'power': power
                    })
                else:
                    team_list.append(None) # ID existed but data missing? Treat as empty.

            return total_power, team_list

    @commands.command(name="set_team")
    async def set_team(self, ctx, s1: int, s2: int = None, s3: int = None, s4: int = None, s5: int = None):
        """
        Equips characters by Inventory ID.
        Example: !set_team 14 2 10
        """
        # (Logic remains same as previous version, just ensuring it's robust)
        slots = [s1, s2, s3, s4, s5]
        clean_slots = [s for s in slots if s is not None]
        
        # Check duplicates
        if len(set(clean_slots)) != len(clean_slots):
            await ctx.send("❌ Duplicate IDs detected. You cannot clone characters!")
            return

        async with aiosqlite.connect(DB_PATH) as db:
            # Verify Ownership
            placeholders = ','.join('?' for _ in clean_slots)
            sql = f"SELECT id FROM inventory WHERE user_id = ? AND id IN ({placeholders})"
            async with db.execute(sql, (str(ctx.author.id), *clean_slots)) as cursor:
                owned = await cursor.fetchall()
            
            if len(owned) != len(clean_slots):
                await ctx.send("❌ You do not own one of those IDs. Check `!inventory`.")
                return

            # Save
            final_slots = clean_slots + [None] * (5 - len(clean_slots))
            await db.execute("""
                INSERT INTO teams (user_id, slot_1, slot_2, slot_3, slot_4, slot_5)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    slot_1=excluded.slot_1, slot_2=excluded.slot_2,
                    slot_3=excluded.slot_3, slot_4=excluded.slot_4,
                    slot_5=excluded.slot_5
            """, (str(ctx.author.id), *final_slots))
            await db.commit()
            
        await ctx.send(f"✅ **Squad Updated.** {len(clean_slots)} units ready for deployment.")

    @commands.command(name="team")
    async def view_team(self, ctx, user: discord.Member = None):
        """
        Visual Team Sheet.
        """
        target = user or ctx.author
        loading = await ctx.send("🛡️ *Analyzing Squad Composition...*")
        
        power, team_list = await self.get_team_data(target.id)
        
        # Generate Image
        try:
            image_data = await generate_team_image(team_list)
            file = discord.File(fp=image_data, filename="team_banner.png")
            
            msg = f"**Commanding Officer:** {target.name}\n**Total Combat Power:** {power:,}"
            await loading.delete()
            await ctx.send(content=msg, file=file)
            
        except Exception as e:
            await loading.edit(content=f"⚠️ Visual Error: {e}")

    @commands.command(name="battle")
    async def battle_standoff(self, ctx, opponent: discord.Member):
        # (Keep your existing battle logic here, it works fine!)
        pass

async def setup(bot):
    await bot.add_cog(RPG(bot))