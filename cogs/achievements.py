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
        self.all_data = list(all_achievements.values())
        
        # --- PRE-CALCULATE PAGES ---
        self.badge_pages = self._generate_badge_pages()
        self.text_pages = self._generate_text_pages()
        
        self.total_pages = len(self.badge_pages) + len(self.text_pages)
        self.current_page = 0
        
        # Calculate the index where text pages start
        self.text_start_index = len(self.badge_pages)
        
        # Initialize button state
        self._update_buttons()

    def _generate_badge_pages(self):
        """Chunks badges into fields/pages safely."""
        pages = []
        
        # 1. Build a massive list of all badge strings
        all_badge_strs = []
        for ach in self.all_data:
            emote = f"{ach.badge_emote}" if ach.id in self.earned_ids else f"{Emotes.UNACHIEVED}"
            all_badge_strs.append(emote)

        # 2. Chunk into fields (Max 1024 chars per field)
        fields = []
        current_field = ""
        field_limit = 1000  # Safety buffer
        
        for badge_str in all_badge_strs:
            if len(current_field) + len(badge_str) > field_limit:
                fields.append(current_field)
                current_field = badge_str
            else:
                current_field += badge_str
        
        if current_field:
            fields.append(current_field)
            
        # 3. Chunk fields into Pages (Max 2 fields of badges per page for aesthetics)
        FIELDS_PER_PAGE = 2
        for i in range(0, len(fields), FIELDS_PER_PAGE):
            pages.append(fields[i : i + FIELDS_PER_PAGE])
            
        return pages if pages else [["None"]]

    def _generate_text_pages(self):
        """Chunks text details into pages of 10."""
        pages = []
        ITEMS_PER_PAGE = 10
        for i in range(0, len(self.all_data), ITEMS_PER_PAGE):
            pages.append(self.all_data[i : i + ITEMS_PER_PAGE])
        return pages if pages else [[]]

    def _update_buttons(self):
        """Updates the Jump button label/style based on current view."""
        is_text_mode = self.current_page >= self.text_start_index
        
        for child in self.children:
            if isinstance(child, Button) and child.custom_id == "jump_btn":
                if is_text_mode:
                    child.label = "Badges"
                    child.style = discord.ButtonStyle.secondary
                else:
                    child.label = "List"
                    child.style = discord.ButtonStyle.primary
                break

    async def get_page_embed(self):
        embed = discord.Embed(
            title=f"{Emotes.ACHIEVEMENTS} {self.user.display_name}'s Hall of Fame",
            color=0x2b2d31
        )
        embed.set_thumbnail(url=self.user.display_avatar.url)

        # --- RENDER LOGIC ---
        
        # CASE A: Badge Page
        if self.current_page < self.text_start_index:
            fields = self.badge_pages[self.current_page]
            
            for i, field_text in enumerate(fields):
                # Only title the first field "Badges"
                name = "Badges" if i == 0 else "\u200b"
                embed.add_field(name=name, value=field_text, inline=False)
                
            footer_txt = f"View: Badges (Page {self.current_page + 1}/{self.total_pages})"

        # CASE B: Text Page
        else:
            local_idx = self.current_page - self.text_start_index
            items = self.text_pages[local_idx]
            
            description = ""
            for ach in items:
                is_unlocked = ach.id in self.earned_ids
                icon = "✅" if is_unlocked else "🔒"
                name = f"**{ach.name}**" if is_unlocked else f"*{ach.name}*"
                
                description += f"{icon} {name}\n╚ {ach.description}\n\n"
            
            embed.description = description
            footer_txt = f"View: Details (Page {self.current_page + 1}/{self.total_pages})"

        unlock_stats = f"Unlocked: {len(self.earned_ids)}/{len(self.all_data)}"
        embed.set_footer(text=f"{footer_txt} • {unlock_stats}")
        
        return embed

    # --- BUTTONS ---

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id: return
        
        if self.current_page > 0:
            self.current_page -= 1
            self._update_buttons()
            await interaction.response.edit_message(embed=await self.get_page_embed(), view=self)

    # Note: custom_id="jump_btn" is crucial for _update_buttons to find it
    @discord.ui.button(label="📜 List", style=discord.ButtonStyle.primary, custom_id="jump_btn")
    async def jump_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id: return
        
        # Toggle Logic
        if self.current_page < self.text_start_index:
            # Currently on Badges -> Jump to Text
            self.current_page = self.text_start_index
        else:
            # Currently on Text -> Jump to Badges
            self.current_page = 0
            
        self._update_buttons()
        await interaction.response.edit_message(embed=await self.get_page_embed(), view=self)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id: return

        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self._update_buttons()
            await interaction.response.edit_message(embed=await self.get_page_embed(), view=self)

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