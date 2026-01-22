import discord
from discord.ext import commands
import datetime
from core.database import get_db_pool, get_user

class Event(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # CONFIGURATION
        self.EVENT_UNIT_ID = 77777  # The ID of the "Dealer" unit
        self.BOSS_NAME = "Jackpot Slime"
        self.DAILY_TICKETS = 3

    async def _get_event_data(self, user_id):
        """Fetches or initializes user event data."""
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            # Table: event_ranking
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS event_ranking (
                    user_id TEXT PRIMARY KEY,
                    score INTEGER DEFAULT 0,
                    tickets INTEGER DEFAULT 3,
                    last_reset TEXT
                )
            """)
            
            row = await conn.fetchrow("SELECT * FROM event_ranking WHERE user_id = $1", user_id)
            today = datetime.datetime.utcnow().strftime("%Y-%m-%d")

            if not row:
                # New Entry
                await conn.execute(
                    "INSERT INTO event_ranking (user_id, score, tickets, last_reset) VALUES ($1, 0, $2, $3)",
                    user_id, self.DAILY_TICKETS, today
                )
                return {'score': 0, 'tickets': self.DAILY_TICKETS, 'last_reset': today}
            
            # Daily Reset Logic
            if row['last_reset'] != today:
                await conn.execute(
                    "UPDATE event_ranking SET tickets = $1, last_reset = $2 WHERE user_id = $3",
                    self.DAILY_TICKETS, today, user_id
                )
                return {'score': row['score'], 'tickets': self.DAILY_TICKETS, 'last_reset': today}

            return dict(row)

    @commands.group(name="casino", invoke_without_command=True)
    async def casino_main(self, ctx):
        """The High-Stakes Casino Event (Team Power)."""
        data = await self._get_event_data(str(ctx.author.id))
        
        embed = discord.Embed(title=f"🎰 {self.BOSS_NAME} Raid", color=discord.Color.red())
        embed.description = (
            f"**Objective:** Deal damage with your **Active Team**.\n"
            f"**Setup:** Use `!stb` to set your squad before fighting!\n"
            f"**Consistency:** Damage = Your Team's Total Power.\n\n"
            f"🎫 **Tickets:** {data['tickets']}/{self.DAILY_TICKETS}\n"
            f"🏆 **Total Score:** {data['score']:,}"
        )
        embed.add_field(name="Commands", value="`!casino fight` - Deal Damage (1 Ticket)\n`!casino rank` - View Leaderboard")
        embed.set_footer(text="Top 1 wins the Exclusive Unit!")
        
        await ctx.send(embed=embed)

    @commands.command(name="fight")
    async def fight_boss(self, ctx):
        """Deals damage using your Active Team (!team)."""
        user_id = str(ctx.author.id)
        data = await self._get_event_data(user_id)
        
        if data['tickets'] < 1:
            return await ctx.send("❌ **Out of Tickets!** Your attempts regenerate daily.")

        pool = await get_db_pool()
        async with pool.acquire() as conn:
            # 1. Fetch Active Team Slots
            team_row = await conn.fetchrow("SELECT slot_1, slot_2, slot_3, slot_4, slot_5 FROM teams WHERE user_id = $1", user_id)
            
            if not team_row:
                return await ctx.send("⚠️ **No Team Found!**\nPlease use `!stb <id1> <id2> ...` to set your squad first.")

            # Filter out None values (empty slots)
            slot_ids = [val for val in dict(team_row).values() if val is not None]
            
            if not slot_ids:
                return await ctx.send("⚠️ Your team is empty! Use `!stb` to add units.")

            # 2. Calculate Power of these specific units
            # Formula: Base * DupeBonus * TeamLevelBonus
            power_rows = await conn.fetch("""
                SELECT FLOOR(
                    c.true_power 
                    * (1 + (COALESCE(i.dupe_level, 0) * 0.05)) 
                    * (1 + (COALESCE(u.team_level, 1) * 0.01))
                )::int as effective_power
                FROM inventory i
                JOIN characters_cache c ON i.anilist_id = c.anilist_id
                LEFT JOIN users u ON i.user_id = u.user_id
                WHERE i.id = ANY($1)
            """, slot_ids)

            # Damage = Sum of the Active Team
            damage_dealt = sum(r['effective_power'] for r in power_rows)

            if damage_dealt == 0:
                return await ctx.send("⚠️ Your team has 0 power. Check your units!")

            # 3. Update Score & Tickets
            await conn.execute("""
                UPDATE event_ranking 
                SET tickets = tickets - 1, score = score + $1 
                WHERE user_id = $2
            """, damage_dealt, user_id)

        await ctx.send(
            f"⚔️ **Attack Complete!**\n"
            f"Your **Active Team** dealt **{damage_dealt:,} damage**.\n"
            f"📈 **Score Updated!**"
        )

    @commands.command(name="rank", aliases=["leaderboard", "lb"])
    async def view_rankings(self, ctx):
        """View the Event Leaderboard."""
        pool = await get_db_pool()
        rows = await pool.fetch("""
            SELECT user_id, score FROM event_ranking 
            ORDER BY score DESC LIMIT 10
        """)
        
        if not rows:
            return await ctx.send("📉 The leaderboard is empty.")

        embed = discord.Embed(title="🏆 Raid Leaderboard", color=discord.Color.gold())
        desc = ""
        
        for idx, row in enumerate(rows):
            # Fetch username
            try:
                user = await self.bot.fetch_user(int(row['user_id']))
                name = user.name
            except:
                name = f"User {row['user_id']}"
            
            icon = "👑" if idx == 0 else f"#{idx+1}"
            desc += f"**{icon} {name}** — {row['score']:,} pts\n"
            
        embed.description = desc
        embed.set_footer(text="Tip: Optimize your !stb team for max damage!")
        await ctx.send(embed=embed)

    @commands.command(name="end_event")
    @commands.has_permissions(administrator=True)
    async def end_event(self, ctx):
        """(Admin) Ends event and distributes rewards."""
        await ctx.send("🛑 **ENDING EVENT...**")
        
        pool = await get_db_pool()
        rows = await pool.fetch("SELECT user_id, score FROM event_ranking ORDER BY score DESC")
        
        if not rows: return await ctx.send("No participants.")

        winner = rows[0]
        
        # Distribute Rewards
        async with pool.acquire() as conn:
            # Rank 1: The Unit
            await conn.execute(
                "INSERT INTO inventory (user_id, anilist_id, level, xp) VALUES ($1, $2, 1, 0)",
                winner['user_id'], self.EVENT_UNIT_ID
            )
            
            # Everyone Else: Consolation Gems (10% of Score)
            for row in rows[1:]:
                gems = int(row['score'] * 0.1)
                await conn.execute(
                    "UPDATE users SET gacha_gems = gacha_gems + $1 WHERE user_id = $2",
                    gems, row['user_id']
                )

        await ctx.send(f"🎉 **Event Ended!**\nWinner: <@{winner['user_id']}> (Score: {winner['score']:,})\nReward: Exclusive Unit (ID {self.EVENT_UNIT_ID})")

async def setup(bot):
    await bot.add_cog(Event(bot))