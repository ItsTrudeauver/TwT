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
        """Fetches full team data using stored rarity for power accuracy."""
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT slot_1, slot_2, slot_3, slot_4, slot_5 FROM teams WHERE user_id = ?", (str(user_id),)) as cursor:
                row = await cursor.fetchone()
            
            if not row: return 0, [None] * 5

            team_list = []
            total_power = 0
            
            for char_id in row:
                if char_id is None:
                    team_list.append(None)
                    continue
                
                async with db.execute("""
                    SELECT c.name, c.image_url, c.base_power, c.rarity, c.rarity_override 
                    FROM inventory i
                    JOIN characters_cache c ON i.anilist_id = c.anilist_id
                    WHERE i.id = ?
                """, (char_id,)) as cursor:
                    char_data = await cursor.fetchone()
                
                if char_data:
                    name, img, raw_favs, stored_rarity, rarity_ov = char_data
                    # Priority: Override > Stored Rarity (from Rank)
                    rarity = rarity_ov if rarity_ov else (stored_rarity or "R")
                    
                    power = calculate_effective_power(raw_favs, rarity)
                    total_power += power
                    team_list.append({'name': name, 'image_url': img, 'rarity': rarity, 'power': power})
                else:
                    team_list.append(None)
            return total_power, team_list

    @commands.command(name="set_team")
    async def set_team(self, ctx, s1: int, s2: int = None, s3: int = None, s4: int = None, s5: int = None):
        slots = [s1, s2, s3, s4, s5]
        clean_slots = [s for s in slots if s is not None]
        if len(set(clean_slots)) != len(clean_slots):
            await ctx.send("❌ Duplicate IDs detected.")
            return

        async with aiosqlite.connect(DB_PATH) as db:
            placeholders = ','.join('?' for _ in clean_slots)
            sql = f"SELECT id FROM inventory WHERE user_id = ? AND id IN ({placeholders})"
            async with db.execute(sql, (str(ctx.author.id), *clean_slots)) as cursor:
                owned = await cursor.fetchall()
            if len(owned) != len(clean_slots):
                await ctx.send("❌ Ownership verification failed.")
                return

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
        await ctx.send("✅ Squad Updated.")

    @commands.command(name="team")
    async def view_team(self, ctx, user: discord.Member = None):
        target = user or ctx.author
        loading = await ctx.send("🛡️ *Analyzing Squad...*")
        power, team_list = await self.get_team_data(target.id)
        try:
            image_data = await generate_team_image(team_list)
            file = discord.File(fp=image_data, filename="team.png")
            await loading.delete()
            await ctx.send(content=f"**Commander:** {target.name}\n**Power:** {power:,}", file=file)
        except Exception as e:
            await loading.edit(content=f"⚠️ Visual Error: {e}")

    @commands.command(name="battle")
    async def battle_standoff(self, ctx, opponent: discord.Member):
        if opponent == ctx.author:
            await ctx.send("⚔️ You cannot battle yourself!")
            return
        p1_power, _ = await self.get_team_data(ctx.author.id)
        p2_power, _ = await self.get_team_data(opponent.id)
        if p1_power == 0 or p2_power == 0:
            await ctx.send("❌ Both players must equip a team.")
            return

        winner, chance = simulate_standoff(p1_power, p2_power)
        win_member = ctx.author if winner == "Player A" else opponent
        embed = discord.Embed(title="⚔️ Combat Result", color=0xff0000)
        embed.description = f"**{ctx.author.name}** vs **{opponent.name}**\n\n🏆 **{win_member.name}** wins! ({chance:.1f}%)"
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(RPG(bot))