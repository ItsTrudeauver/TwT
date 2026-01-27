# cogs/achievements.py
import discord
from discord.ext import commands
from core.achievements import ACHIEVEMENTS, AchievementEngine
from core.emotes import Emotes
from core.database import get_db_pool

class AchievementCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="achievements", aliases=["ach", "badges"])
    async def show_achievements(self, ctx, user: discord.Member = None):
        """Displays user badges in a row and a list of completions."""
        target = user or ctx.author
        user_id = str(target.id)
        
        pool = await get_db_pool()
        rows = await pool.fetch("SELECT achievement_id FROM achievements WHERE user_id = $1", user_id)
        earned_ids = {r['achievement_id'] for r in rows}

        # 1. Create the Badge Row (Mudae Style)
        badge_row = ""
        for aid, ach in ACHIEVEMENTS.items():
            badge_row += f"{ach.badge_emote}" if aid in earned_ids else f"{Emotes.UNACHIEVED}"
        
        embed = discord.Embed(
            title=f"{Emotes.ACHIEVEMENTS} {target.display_name}'s Hall of Fame",
            color=0x2b2d31
        )
        embed.add_field(name="Badges", value=badge_row or "None", inline=False)
        
        # 2. Detailed List
        details = ""
        for aid, ach in ACHIEVEMENTS.items():
            if aid in earned_ids:
                details += f"✅**{ach.name}**\n"
            else:
                details += f"🔒*{ach.name}* (Locked)\n"
        
        embed.add_field(name="Details", value=details or "No achievements defined.", inline=False)
        embed.set_thumbnail(url=target.display_avatar.url)
        
        await ctx.reply(embed=embed)

    @commands.Cog.listener()
    async def on_command_completion(self, ctx):
        """Automatically checks for new achievements after any command."""
        if ctx.author.bot: return

        new_unlocks = await AchievementEngine.process_all(ctx.author.id)
        
        for ach in new_unlocks:
            # Stylish unlock notification
            embed = discord.Embed(
                title=f"{Emotes.ACHIEVEMENTS} Achievement Unlocked!",
                description=f"Congratulations {ctx.author.mention}!\nYou earned the **{ach.name}** badge.",
                color=0x00ff00
            )
            embed.add_field(name="Badge", value=ach.badge_emote, inline=True)
            
            rewards = []
            if ach.gem_reward: rewards.append(f"{ach.gem_reward} {Emotes.GEMS}")
            if ach.coin_reward: rewards.append(f"{ach.coin_reward} {Emotes.COINS}")
            
            if rewards:
                embed.add_field(name="Rewards", value=" | ".join(rewards), inline=True)
            
            await ctx.channel.send(embed=embed)

async def setup(bot):
    await bot.add_cog(AchievementCog(bot))