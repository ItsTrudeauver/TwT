import discord
from discord.ext import commands
import datetime
from core.database import get_db_pool, add_currency

NPC_DATA = {
    "easy":      {"reward": 500,  "desc": "Defeat an Easy NPC Team (5 R)"},
    "normal":    {"reward": 1000, "desc": "Defeat a Normal NPC Team (3 R, 2 SR)"},
    "hard":      {"reward": 1500, "desc": "Defeat a Hard NPC Team (5 SR)"},
    "expert":    {"reward": 2500, "desc": "Defeat an Expert NPC Team (2 SSR)"},
    "nightmare": {"reward": 3500, "desc": "Defeat a Nightmare NPC Team (3 SSR)"},
    "hell":      {"reward": 5000, "desc": "Defeat a Hell NPC Team (5 SSR, 2 Top 50)"}
}

class Daily(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="checkin")
    async def checkin(self, ctx):
        """Standard daily check-in (+1500 gems)"""
        user_id = str(ctx.author.id)
        pool = await get_db_pool()
        now = datetime.datetime.utcnow().date()

        async with pool.acquire() as conn:
            user = await conn.fetchrow("SELECT last_daily_exchange FROM users WHERE user_id = $1", user_id)
            if user['last_daily_exchange'] and user['last_daily_exchange'].date() >= now:
                return await ctx.reply("❌ Already checked in today! Reset at 00:00 UTC.")

            await add_currency(user_id, 1500)
            await conn.execute("UPDATE users SET last_daily_exchange = CURRENT_TIMESTAMP WHERE user_id = $1", user_id)
            await ctx.reply("📅 **Check-in Successful!** +1,500 Gems awarded.")

    @commands.command(name="tasks")
    async def view_tasks(self, ctx):
        """View and claim rewards for daily battles"""
        user_id = str(ctx.author.id)
        pool = await get_db_pool()
        
        # Reset check: If date in DB is older than today, clear progress
        await pool.execute("DELETE FROM daily_tasks WHERE user_id = $1 AND last_updated < CURRENT_DATE", user_id)
        
        rows = await pool.fetch("SELECT * FROM daily_tasks WHERE user_id = $1", user_id)
        completed = {r['task_key']: r['is_claimed'] for r in rows}
        progress = {r['task_key']: r['progress'] for r in rows}

        embed = discord.Embed(title="⚔️ Daily Battle Objectives", color=0xf1c40f)
        
        # PVP Task
        p_status = "✅ Claimed" if completed.get('pvp') else ("🎁 !claim pvp" if progress.get('pvp') else "⏳ 0/1")
        embed.add_field(name="PVP: Battle a Player", value=f"Reward: 500 Gems | {p_status}", inline=False)

        # NPC Tasks
        for key, info in NPC_DATA.items():
            status = "✅ Claimed" if completed.get(key) else ("🎁 !claim " + key if progress.get(key) else "⏳ 0/1")
            embed.add_field(name=f"NPC: {key.capitalize()}", value=f"Reward: {info['reward']} Gems | {status}", inline=False)

        await ctx.reply(embed=embed)

    @commands.command(name="claim")
    async def claim_task(self, ctx, task: str):
        """Claim gems for a completed task"""
        user_id = str(ctx.author.id)
        task = task.lower()
        pool = await get_db_pool()
        
        reward = 500 if task == "pvp" else NPC_DATA.get(task, {}).get("reward")
        if not reward: return await ctx.reply("❌ Invalid task.")

        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT progress, is_claimed FROM daily_tasks WHERE user_id = $1 AND task_key = $2", user_id, task)
            if not row or row['progress'] == 0: return await ctx.reply("❌ Task not completed yet.")
            if row['is_claimed']: return await ctx.reply("⚠️ Reward already claimed.")

            await add_currency(user_id, reward)
            await conn.execute("UPDATE daily_tasks SET is_claimed = TRUE WHERE user_id = $1 AND task_key = $2", user_id, task)
            await ctx.reply(f"🎉 **Claimed {reward:,} Gems** for {task} task!")

async def setup(bot):
    await bot.add_cog(Daily(bot))