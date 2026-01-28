import discord
from discord.ext import commands
from discord.ui import View, Button
import math

from core.achievements import ACHIEVEMENTS, AchievementEngine
from core.emotes import Emotes
from core.database import get_db_pool

class AchievementPaginationView(View):
    def __init__(self, ctx, user, earned_ids, all_achievements):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.user = user
        self.earned_ids = earned_ids
        self.data = list(all_achievements.values()) # Convert dict values to list
        self.current_page = 0
        self.items_per_page = 10
        self.total_pages = math.ceil(len(self.data) / self.items_per_page)

    async def get_page_embed(self):
        # Slice data for current page
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        page_items = self.data[start:end]

        # 1. Badge Row (Always visible or specific to page? Keeping it global is usually nicer)
        # However, if you have MANY badges, you might want to slice this too. 
        # For now, let's keep the badge row global but truncated if needed, 
        # or we can just focus on the list details.
        
        # Let's rebuild the badge row just for the summary (or skip it if it's too huge).
        # We'll include a condensed badge row of *all* earned badges at the top.
        badge_row = ""
        for ach in self.data:
            badge_row += f"{ach.badge_emote}" if ach.id in self.earned_ids else f"{Emotes.UNACHIEVED}"
        
        # Truncate badge row if absolutely massive, though emojis are small.
        if len(badge_row) > 1000: 
            badge_row = badge_row[:1000] + "..."

        embed = discord.Embed(
            title=f"{Emotes.ACHIEVEMENTS} {self.user.display_name}'s Hall of Fame",
            color=0x2b2d31
        )
        embed.set_thumbnail(url=self.user.display_avatar.url)
        embed.add_field(name="Badges", value=badge_row or "None", inline=False)

        # 2. Detailed List for this Page
        details = ""
        for ach in page_items:
            status = "\✅" if ach.id in self.earned_ids else "\🔒"
            desc = f"**{ach.name}**" if ach.id in self.earned_ids else f"*{ach.name}*"
            details += f"{status} {desc}\n"
            # Optional: Add description line
            # details += f"╚ {ach.description}\n" 

        embed.add_field(name=f"Achievements (Page {self.current_page + 1}/{self.total_pages})", value=details, inline=False)
        embed.set_footer(text=f"Total Unlocked: {len(self.earned_ids)}/{len(self.data)}")
        
        return embed

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            return await interaction.response.send_message("❌ This is not your menu.", ephemeral=True)
            
        if self.current_page > 0:
            self.current_page -= 1
            await interaction.response.edit_message(embed=await self.get_page_embed(), view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            return await interaction.response.send_message("❌ This is not your menu.", ephemeral=True)

        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            await interaction.response.edit_message(embed=await self.get_page_embed(), view=self)
        else:
            await interaction.response.defer()

class AchievementCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="achievements", aliases=["ach", "badges"])
    async def show_achievements(self, ctx, user: discord.Member = None):
        """Displays user badges with pagination."""
        target = user or ctx.author
        user_id = str(target.id)
        
        pool = await get_db_pool()
        rows = await pool.fetch("SELECT achievement_id FROM achievements WHERE user_id = $1", user_id)
        earned_ids = {r['achievement_id'] for r in rows}

        view = AchievementPaginationView(ctx, target, earned_ids, ACHIEVEMENTS)
        embed = await view.get_page_embed()
        
        await ctx.reply(embed=embed, view=view)

    @commands.Cog.listener()
    async def on_command_completion(self, ctx):
        """Automatically checks for new achievements after any command."""
        if ctx.author.bot: return

        # Wrap in try/except to prevent errors from blocking command execution
        try:
            new_unlocks = await AchievementEngine.process_all(ctx.author.id)
            
            for ach in new_unlocks:
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
        except Exception as e:
            print(f"Achievement Check Error: {e}")

async def setup(bot):
    await bot.add_cog(AchievementCog(bot))