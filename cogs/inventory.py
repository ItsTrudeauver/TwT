import discord
from discord.ext import commands
import math
import json
from core.database import get_db_pool, get_user, mass_scrap_r_rarity

class InventoryView(discord.ui.View):
    def __init__(self, bot, user, pool, per_page=10):
        # Setting timeout to None so buttons don't die
        super().__init__(timeout=None)
        self.bot = bot
        self.user = user
        self.pool = pool
        self.page = 1
        self.per_page = per_page
        self.max_pages = 1

    async def get_page_content(self):
        user_id_str = str(self.user.id)
        # 1. Force recalculate max pages
        count_val = await self.pool.fetchval("SELECT COUNT(*) FROM inventory WHERE user_id = $1", user_id_str)
        count_val = count_val or 0
        self.max_pages = math.ceil(count_val / self.per_page)
        if self.max_pages < 1: self.max_pages = 1
        
        user_data = await get_user(self.user.id)
        
        offset = (self.page - 1) * self.per_page
        # UPDATED SQL: Includes dupe_level and calculates boosted power for sorting/display
        rows = await self.pool.fetch("""
            SELECT 
                i.id, 
                c.name, 
                c.rarity, 
                i.is_locked, 
                i.dupe_level,
                FLOOR(c.true_power * (1 + (i.dupe_level * 0.05))) as true_power
            FROM inventory i
            JOIN characters_cache c ON i.anilist_id = c.anilist_id
            WHERE i.user_id = $1
            ORDER BY true_power DESC, i.obtained_at DESC
            LIMIT $2 OFFSET $3
        """, user_id_str, self.per_page, offset)

        embed = discord.Embed(title=f"🎒 {self.user.display_name}'s Inventory", color=0x3498DB)
        embed.description = f"💎 **Gems:** `{user_data['gacha_gems']:,}`\n"
        embed.description += f"📦 **Total Units:** `{count_val}`\n"
        embed.description += "─" * 25 + "\n"

        if not rows:
            embed.description += "*No characters found on this page.*"
        else:
            for row in rows:
                lock = "🔒" if row['is_locked'] else ""
                rarity = "🌟" if row['rarity'] == "SSR" else "✨" if row['rarity'] == "SR" else "⚪"
                
                # UPDATED: Add dupe count display next to the name
                dupe_text = f" (+{row['dupe_level']})" if row['dupe_level'] > 0 else ""
                
                embed.description += f"`#{row['id']}` {lock} **{row['name']}**{dupe_text} {rarity} — ⚔️ `{row['true_power']:,}`\n"

        embed.set_footer(text=f"Page {self.page} of {self.max_pages} | Use !view [ID]")
        return embed

    def update_buttons(self):
        # Disable "Previous" if on page 1
        self.prev_button.disabled = (self.page <= 1)
        # Disable "Next" if on the last page or if there's only 1 page
        self.next_button.disabled = (self.page >= self.max_pages)

    @discord.ui.button(label="⬅️ Previous", style=discord.ButtonStyle.primary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        embed = await self.get_page_content()
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Next ➡️", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        embed = await self.get_page_content()
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

class Inventory(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="gems", aliases=["pc", "wallet", "profile"])
    async def check_balance(self, ctx):
        user_data = await get_user(ctx.author.id)
        await ctx.reply(f"💎 {ctx.author.mention}, you currently have **{user_data['gacha_gems']:,}** Gems.")

    @commands.command(name="inventory", aliases=["inv"])
    async def show_inventory(self, ctx):
        pool = await get_db_pool()
        view = InventoryView(self.bot, ctx.author, pool)
        
        # We MUST fetch content first so max_pages is calculated BEFORE update_buttons
        embed = await view.get_page_content()
        view.update_buttons()
        
        await ctx.reply(embed=embed, view=view)

    @commands.command(name="view")
    async def view_character(self, ctx, inventory_id: int):
        pool = await get_db_pool()
        # UPDATED SQL: Pulls dupe_level and calculates boosted power
        row = await pool.fetchrow("""
            SELECT 
                i.id, 
                c.name, 
                c.image_url, 
                c.rarity, 
                c.ability_tags, 
                i.is_locked, 
                c.anilist_id, 
                i.dupe_level,
                FLOOR(c.true_power * (1 + (i.dupe_level * 0.05))) as true_power
            FROM inventory i
            JOIN characters_cache c ON i.anilist_id = c.anilist_id
            WHERE i.id = $1 AND i.user_id = $2
        """, inventory_id, str(ctx.author.id))

        if not row:
            return await ctx.reply("❌ Character not found.")

        embed = discord.Embed(title=f"{row['name']}", color=0xF1C40F if row['rarity'] == "SSR" else 0x9B59B6)
        if row['image_url']: embed.set_image(url=row['image_url'])
        
        status = "🔒 Locked" if row['is_locked'] else "🔓 Unlocked"
        
        # UPDATED: Added Dupes count to the field list and corrected power display
        details = (
            f"**Rarity:** {row['rarity']}\n"
            f"**Power:** {row['true_power']:,}\n"
            f"**Dupes:** {row['dupe_level']}\n"
            f"**Status:** {status}"
        )
        embed.add_field(name="DETAILS", value=details, inline=True)
        
        skills = json.loads(row['ability_tags'])
        embed.add_field(name="SKILLS", value="\n".join([f"• {s}" for s in skills]) if skills else "*None*", inline=False)
        await ctx.reply(embed=embed)

    @commands.command(name="lock")
    async def lock_character(self, ctx, inventory_id: int):
        pool = await get_db_pool()
        await pool.execute("UPDATE inventory SET is_locked = TRUE WHERE id = $1 AND user_id = $2", inventory_id, str(ctx.author.id))
        await ctx.reply(f"🔒 Character `#{inventory_id}` locked.")

    @commands.command(name="unlock")
    async def unlock_character(self, ctx, inventory_id: int):
        pool = await get_db_pool()
        await pool.execute("UPDATE inventory SET is_locked = FALSE WHERE id = $1 AND user_id = $2", inventory_id, str(ctx.author.id))
        await ctx.reply(f"🔓 Character `#{inventory_id}` unlocked.")

    @commands.command(name="scrap_all", aliases=["mass_scrap"])
    async def scrap_all(self, ctx):
        count, reward = await mass_scrap_r_rarity(ctx.author.id)
        await ctx.reply(f"♻️ Scrapped {count} units for {reward:,} Gems!" if count > 0 else "❌ No units to scrap.")

async def setup(bot):
    await bot.add_cog(Inventory(bot))