import discord
from discord.ext import commands
import aiosqlite
import random
import os

from core.database import DB_PATH
from core.game_math import calculate_effective_power, simulate_standoff

class RPG(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def get_team_power(self, user_id):
        """
        Calculates the total Effective Power of a user's team.
        """
        async with aiosqlite.connect(DB_PATH) as db:
            # 1. Get Team Slots
            async with db.execute("SELECT slot_1, slot_2, slot_3, slot_4, slot_5 FROM teams WHERE user_id = ?", (str(user_id),)) as cursor:
                team_row = await cursor.fetchone()
            
            if not team_row:
                return 0, []

            # Filter out empty slots (None)
            char_ids = [c for c in team_row if c is not None]
            
            if not char_ids:
                return 0, []

            # 2. Get Stats for these characters from Cache
            # We use "IN" clause to fetch all at once
            placeholders = ','.join('?' for _ in char_ids)
            sql = f"""
                SELECT c.name, c.base_power, c.squash_resistance
                FROM inventory i
                JOIN characters_cache c ON i.anilist_id = c.anilist_id
                WHERE i.id IN ({placeholders})
            """
            
            async with db.execute(sql, char_ids) as cursor:
                rows = await cursor.fetchall()

            # 3. Calculate Total Power using the Math Engine
            total_power = 0
            team_details = []
            
            for row in rows:
                name, raw, res = row
                eff = calculate_effective_power(raw, res)
                total_power += eff
                team_details.append(f"{name} ({eff})")
                
            return total_power, team_details

    @commands.command(name="set_team")
    async def set_team(self, ctx, s1: int, s2: int = None, s3: int = None, s4: int = None, s5: int = None):
        """
        Sets your team using Inventory IDs.
        Usage: !set_team 12 15 4 99 101
        """
        slots = [s1, s2, s3, s4, s5]
        # Remove duplicates and None
        clean_slots = list(set([s for s in slots if s is not None]))
        
        if len(clean_slots) != len([s for s in slots if s is not None]):
            await ctx.send("❌ You cannot equip the same character twice!")
            return

        async with aiosqlite.connect(DB_PATH) as db:
            # Verify Ownership of ALL items
            placeholders = ','.join('?' for _ in clean_slots)
            sql = f"SELECT id FROM inventory WHERE user_id = ? AND id IN ({placeholders})"
            async with db.execute(sql, (str(ctx.author.id), *clean_slots)) as cursor:
                owned = await cursor.fetchall()
            
            if len(owned) != len(clean_slots):
                await ctx.send("❌ You don't own one of those IDs.")
                return

            # Update Team
            # We use specific logic to handle partial teams (less than 5)
            # Pad the list with None up to 5
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
            
        await ctx.send(f"✅ Team updated! ({len(clean_slots)}/5 Members)")

    @commands.command(name="team")
    async def view_team(self, ctx, user: discord.Member = None):
        """View a user's team power."""
        target = user or ctx.author
        power, details = await self.get_team_power(target.id)
        
        if power == 0:
            await ctx.send(f"{target.display_name} has no team set.")
            return

        embed = discord.Embed(
            title=f"🛡️ Team {target.display_name}",
            description=f"**Total Power: {power:,}**\n\n" + "\n".join(details),
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

    @commands.command(name="battle")
    async def battle_standoff(self, ctx, opponent: discord.Member):
        """
        The Standoff.
        """
        if opponent.bot or opponent == ctx.author:
            await ctx.send("You cannot battle bots or yourself.")
            return

        # 1. Calculate Powers
        my_power, _ = await self.get_team_power(ctx.author.id)
        their_power, _ = await self.get_team_power(opponent.id)

        if my_power == 0 or their_power == 0:
            await ctx.send("❌ Both players need a team set via `!set_team`.")
            return

        # 2. Run Simulation
        winner_name, win_chance = simulate_standoff(my_power, their_power)
        
        # Determine actual winner based on probability
        # The simulation function returns a "theoretical" winner, but let's be explicit here
        # Reroll specifically for this instance
        total = my_power + their_power
        roll = random.uniform(0, total)
        
        actual_winner = ctx.author if roll < my_power else opponent
        
        # 3. Visuals
        embed = discord.Embed(
            title="⚔️ The Standoff",
            description=f"**{ctx.author.name}** ({my_power:,}) vs **{opponent.name}** ({their_power:,})",
            color=discord.Color.dark_red()
        )
        
        embed.add_field(name="Win Probability", value=f"{ctx.author.name}: {int((my_power/total)*100)}%")
        embed.add_field(name="Result", value=f"🏆 **{actual_winner.display_name} Wins!**")
        
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(RPG(bot))