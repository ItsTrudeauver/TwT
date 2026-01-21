import discord
from discord.ext import commands
import math
import json
# Added mass_scrap_r_rarity to imports so !scrap_all works
from core.database import get_db_pool, get_user, mass_scrap_r_rarity 

class Inventory(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="gems", aliases=["pc", "wallet", "profile"])
    async def check_balance(self, ctx):
        """
        Shows your current Gems and Collection stats.
        """
        # 1. Fetch User Data
        user_data = await get_user(ctx.author.id)
        
        # 2. Fetch Collection Stats
        pool = await get_db_pool()
        stats = await pool.fetchrow("""
            SELECT COUNT(*) as total_chars, 
                   COUNT(DISTINCT anilist_id) as unique_chars,
                   SUM(c.true_power) as total_power
            FROM inventory i
            JOIN characters_cache c ON i.anilist_id = c.anilist_id
            WHERE i.user_id = $1
        """, str(ctx.author.id))

        total_chars = stats['total_chars'] or 0
        unique_chars = stats['unique_chars'] or 0
        total_power = stats['total_power'] or 0

        # 3. Build Embed
        embed = discord.Embed(
            title=f"💳 {ctx.author.display_name}'s Profile",
            color=0x2ECC71
        )
        embed.set_thumbnail(url=ctx.author.display_avatar.url)

        # --- CRASH FIX IS HERE ---
        # We use .get() to avoid crashing if 'scrap' column doesn't exist yet
        scrap_amount = user_data.get('scrap', 0) 
        
        embed.add_field(
            name="💰 Currency",
            value=f"**Gems:** `{user_data['gacha_gems']:,}` 💎\n**Scrap:** `{scrap_amount:,}` 🔩",
            inline=True
        )

        embed.add_field(
            name="📦 Collection",
            value=f"**Units:** `{total_chars}` (Unique: `{unique_chars}`)\n**Total Power:** `{total_power:,}` ⚔️",
            inline=True
        )

        await ctx.send(embed=embed)

    @commands.command(name="inventory", aliases=["inv"])
    async def show_inventory(self, ctx, page: int = 1):
        """
        Displays your characters.
        Usage: !inventory [page]
        """
        user_id = str(ctx.author.id)
        pool = await get_db_pool()
        
        # Count total items
        count_val = await pool.fetchval("SELECT COUNT(*) FROM inventory WHERE user_id = $1", user_id)
        if not count_val:
            return await ctx.send("Your inventory is empty! Use `!pull` or `!starter` to get characters.")

        per_page = 10
        max_pages = math.ceil(count_val / per_page)
        
        if page < 1: page = 1
        if page > max_pages: page = max_pages

        offset = (page - 1) * per_page
        
        # Fetch inventory
        rows = await pool.fetch("""
            SELECT i.id, c.name, c.rarity, c.true_power, i.is_locked
            FROM inventory i
            JOIN characters_cache c ON i.anilist_id = c.anilist_id
            WHERE i.user_id = $1
            ORDER BY c.true_power DESC, i.obtained_at DESC
            LIMIT $2 OFFSET $3
        """, user_id, per_page, offset)

        embed = discord.Embed(title=f"🎒 Inventory (Page {page}/{max_pages})", color=0x3498DB)
        
        desc_lines = []
        for row in rows:
            lock_icon = "🔒 " if row['is_locked'] else ""
            rarity_icon = "🌟" if row['rarity'] == "SSR" else "✨" if row['rarity'] == "SR" else "⚪"
            
            line = f"`#{row['id']}` {lock_icon}**{row['name']}** {rarity_icon}\nChecking Power: `{row['true_power']:,}`"
            desc_lines.append(line)
        
        embed.description = "\n".join(desc_lines)
        embed.set_footer(text=f"Total Units: {count_val} | Use !view [ID] for details")
        
        await ctx.send(embed=embed)

    @commands.command(name="view")
    async def view_character(self, ctx, inventory_id: int):
        """
        View detailed stats of a specific character in your inventory.
        Usage: !view [Inventory ID] (The number with # in !inv)
        """
        pool = await get_db_pool()
        
        row = await pool.fetchrow("""
            SELECT i.id, c.name, c.image_url, c.rarity, c.true_power, c.ability_tags, i.is_locked, c.anilist_id
            FROM inventory i
            JOIN characters_cache c ON i.anilist_id = c.anilist_id
            WHERE i.id = $1 AND i.user_id = $2
        """, inventory_id, str(ctx.author.id))

        if not row:
            return await ctx.send("❌ Character not found in your inventory.")

        embed = discord.Embed(title=f"{row['name']}", color=0xF1C40F if row['rarity'] == "SSR" else 0x9B59B6)
        if row['image_url']:
            embed.set_image(url=row['image_url'])
        
        status = "🔒 Locked" if row['is_locked'] else "🔓 Unlocked"
        
        embed.add_field(name="DETAILS", value=f"**Rarity:** {row['rarity']}\n**Power:** {row['true_power']:,}\n**Status:** {status}", inline=True)
        embed.add_field(name="META", value=f"**Inv ID:** `{row['id']}`\n**AniList ID:** `{row['anilist_id']}`", inline=True)
        
        # Parse Skills
        skills = json.loads(row['ability_tags'])
        if skills:
            embed.add_field(name="SKILLS", value="\n".join([f"• {s}" for s in skills]), inline=False)
        else:
            embed.add_field(name="SKILLS", value="*None*", inline=False)

        await ctx.send(embed=embed)

    @commands.command(name="lock")
    async def lock_character(self, ctx, inventory_id: int):
        """Locks a character."""
        pool = await get_db_pool()
        res = await pool.execute("UPDATE inventory SET is_locked = TRUE WHERE id = $1 AND user_id = $2", inventory_id, str(ctx.author.id))
        
        if res == "UPDATE 1":
            await ctx.send(f"🔒 Character `#{inventory_id}` has been **LOCKED**.")
        else:
            await ctx.send(f"❌ Could not find character `#{inventory_id}`.")

    @commands.command(name="unlock")
    async def unlock_character(self, ctx, inventory_id: int):
        """Unlocks a character."""
        pool = await get_db_pool()
        res = await pool.execute("UPDATE inventory SET is_locked = FALSE WHERE id = $1 AND user_id = $2", inventory_id, str(ctx.author.id))
        
        if res == "UPDATE 1":
            await ctx.send(f"🔓 Character `#{inventory_id}` has been **UNLOCKED**.")
        else:
            await ctx.send(f"❌ Could not find character `#{inventory_id}`.")

    @commands.command(name="scrap_all", aliases=["mass_scrap"])
    async def scrap_all(self, ctx):
        """Scraps all unlocked 'R' characters."""
        # This will fail if mass_scrap_r_rarity isn't imported at top of file
        count, reward = await mass_scrap_r_rarity(ctx.author.id)
        if count > 0:
            await ctx.send(f"♻️ Scrapped **{count}** characters for **{reward:,}** Gems!")
        else:
            await ctx.send("❌ No unlocked 'R' characters found to scrap.")

async def setup(bot):
    await bot.add_cog(Inventory(bot))