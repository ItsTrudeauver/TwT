# cogs/inventory.py
import discord
from discord.ext import commands
from discord.ui import View, Button
import math
import json
from core.database import get_db_pool, get_user, mass_scrap_r_rarity, mass_scrap_sr_rarity
from core.emotes import Emotes  # Import Emotes

class ConfirmSRScrap(View):
    def __init__(self, author):
        super().__init__(timeout=30)
        self.author = author
        self.value = None

    @discord.ui.button(label="⚠️ Confirm Scrap SRs", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.author: return
        self.value = True
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        self.value = False
        self.stop()

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
        embed.description = f"{Emotes.GEMS} **Gems:** `{user_data['gacha_gems']:,}`\n"
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
        await ctx.reply(f"{ctx.author.mention}, you currently have **{user_data['gacha_gems']:,}** {Emotes.GEMS} and **{user_data.get('coins', 0):,}** {Emotes.COINS}")

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
        count, gems, coins = await mass_scrap_r_rarity(ctx.author.id)
        if count > 0:
            await ctx.reply(f"♻️ Scrapped **{count}** R units for **{gems:,}** {Emotes.GEMS} and **{coins:,}** {Emotes.COINS}!")
        else:
            await ctx.reply("❌ No unlocked R units found.")

    @commands.command(name="scrap_sr")
    async def scrap_sr_cmd(self, ctx):
        """Mass scraps unlocked SRs with confirmation."""
        view = ConfirmSRScrap(ctx.author)
        msg = await ctx.reply(
            "⚠️ **WARNING:** This will scrap ALL **unlocked** SR units for 500 Gems + 25 Coins each.\n**Please check if you locked the ones you want to keep!**", 
            view=view
        )
        
        await view.wait()
        if view.value:
            count, gems, coins = await mass_scrap_sr_rarity(ctx.author.id)
            if count > 0:
                await msg.edit(content=f"♻️ Scrapped **{count}** SR units for **{gems:,}** {Emotes.GEMS} and **{coins:,}** {Emotes.COINS}!", view=None)
            else:
                await msg.edit(content="❌ No unlocked SR units found.", view=None)
        else:
            await msg.edit(content="❌ Scrap cancelled.", view=None)

    @commands.command(name="items", aliases=["bag"])
    async def show_items(self, ctx):
        """Displays your Coins and Special Items."""
        pool = await get_db_pool()
        user_data = await pool.fetchrow("SELECT coins FROM users WHERE user_id = $1", str(ctx.author.id))
        items = await pool.fetch("SELECT item_id, quantity FROM user_items WHERE user_id = $1 AND quantity > 0", str(ctx.author.id))
        
        coins = user_data['coins'] if user_data else 0
        
        embed = discord.Embed(title=f"🎒 {ctx.author.display_name}'s Items", color=0x9B59B6)
        embed.add_field(name="Currency", value=f"{Emotes.COINS} **Coins:** `{coins:,}`", inline=False)
        
        if items:
            item_list = "\n".join([f"• **{r['item_id']}**: `{r['quantity']}`" for r in items])
        else:
            item_list = "*No special items owned.*"
            
        embed.add_field(name="Consumables", value=item_list, inline=False)
        await ctx.reply(embed=embed)

    @commands.command(name="use_token")
    async def use_ssr_token(self, ctx, char_id: int):
        """Uses an SSR Token to upgrade a specific character."""
        pool = await get_db_pool()
        
        # 1. Check if user has a token
        token_row = await pool.fetchrow("SELECT quantity FROM user_items WHERE user_id = $1 AND item_id = 'SSR Token'", str(ctx.author.id))
        if not token_row or token_row['quantity'] < 1:
            return await ctx.reply(f"❌ You do not have an **SSR Token**! Buy one in the shop.")

        # 2. Check if user owns the character and it is an SSR
        char_row = await pool.fetchrow("""
            SELECT i.dupe_level, c.rarity, c.name 
            FROM inventory i 
            JOIN characters_cache c ON i.anilist_id = c.anilist_id 
            WHERE i.user_id = $1 AND i.id = $2
        """, str(ctx.author.id), char_id)

        if not char_row:
            return await ctx.reply("❌ Character not found in your inventory.")
        
        if char_row['rarity'] != 'SSR':
            return await ctx.reply("❌ You can only use this token on **SSR** characters.")
            
        if char_row['dupe_level'] >= 10:
            return await ctx.reply("❌ This character is already at Max Dupes (Lv. 10)!")

        # 3. Apply Upgrade
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Consume Token
                await conn.execute("UPDATE user_items SET quantity = quantity - 1 WHERE user_id = $1 AND item_id = 'SSR Token'", str(ctx.author.id))
                # Upgrade Unit
                await conn.execute("UPDATE inventory SET dupe_level = dupe_level + 1 WHERE id = $1", char_id)

        await ctx.reply(f"{Emotes.SSRTOKEN} **Success!** Used 1 SSR Token to upgrade **{char_row['name']}** to **Dupe Lv. {char_row['dupe_level'] + 1}**!")

async def setup(bot):
    await bot.add_cog(Inventory(bot))