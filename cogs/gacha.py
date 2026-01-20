import discord
from discord.ext import commands
import aiohttp
import random
import os
import asyncio

# Custom Modules (Importing the new connection helper)
from core.database import get_db_connection, add_character_to_inventory, cache_character
from core.game_math import calculate_effective_power
from core.image_gen import generate_10_pull_image

class Gacha(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.anilist_url = os.getenv("ANILIST_URL")

    # [Note: roll_rarity, get_rank_by_rarity, fetch_character_data, get_valid_character stay the same]

    @commands.command(name="pull")
    async def pull_character(self, ctx, amount: int = 1):
        if amount not in [1, 10]:
            await ctx.send("❌ You can only pull **1** or **10** times.")
            return

        loading_msg = await ctx.send(f"🎰 *Initiating {amount}-Pull Protocol...*")
        pulled_chars = []

        for _ in range(amount):
            char_data = await self.get_valid_character()
            if char_data:
                pulled_chars.append(char_data)

        if amount == 10 and pulled_chars:
            has_good_pull = any(c['rarity'] in ["SR", "SSR"] for c in pulled_chars)
            if not has_good_pull:
                guaranteed = await self.get_valid_character(forced_rarity="SR")
                if guaranteed:
                    pulled_chars[-1] = guaranteed

        if not pulled_chars:
            await loading_msg.edit(content="❌ Connection Error. AniList is unreachable.")
            return

        # Save to Supabase using the core.database helpers
        for char in pulled_chars:
            await cache_character(char['id'], char['name'], char['image_url'], char['favs'])
            await add_character_to_inventory(str(ctx.author.id), char['id'])

        # Display Logic (Unchanged)
        if amount == 1:
            c = pulled_chars[0]
            cols = {"SSR": 0xFFD700, "SR": 0xDA70D6, "R": 0x00BFFF}
            embed = discord.Embed(
                title=f"✨ {c['rarity']} Summon",
                description=f"**{c['name']}**\nPower: {c['power']:,}",
                color=cols.get(c['rarity'], 0xFFFFFF))
            embed.set_image(url=c['image_url'])
            await loading_msg.edit(content=None, embed=embed)
        else:
            await loading_msg.edit(content="🎨 *Painting the stars...*")
            try:
                image_data = await generate_10_pull_image(pulled_chars)
                file = discord.File(fp=image_data, filename="10pull.png")
                await loading_msg.delete()
                await ctx.send(f"💫 **{ctx.author.name}'s 10-Pull**", file=file)
            except Exception as e:
                await ctx.send(f"Image Error: {e}")

    @commands.command(name="inventory", aliases=["inv"])
    async def show_inventory(self, ctx, page: int = 1):
        items_per_page = 10
        offset = (page - 1) * items_per_page

        conn = await get_db_connection()
        try:
            # Postgres: fetchval gets a single value
            total_items = await conn.fetchval("SELECT COUNT(*) FROM inventory WHERE user_id = $1", str(ctx.author.id))

            if total_items == 0:
                await ctx.send("🎒 Your inventory is empty. Try `!pull` first!")
                return

            max_pages = (total_items // items_per_page) + 1
            if page > max_pages: page = max_pages

            # Postgres: uses $1, $2 instead of ?
            sql = """
                SELECT i.id, c.name, c.base_power
                FROM inventory i
                LEFT JOIN characters_cache c ON i.anilist_id = c.anilist_id
                WHERE i.user_id = $1
                ORDER BY c.base_power DESC
                LIMIT $2 OFFSET $3
            """
            rows = await conn.fetch(sql, str(ctx.author.id), items_per_page, offset)

            embed = discord.Embed(
                title=f"🎒 Inventory - {ctx.author.name}",
                description=f"**Page {page}/{max_pages}** | Total Units: {total_items}",
                color=discord.Color.dark_grey())

            list_text = ""
            for row in rows:
                inv_id, name, raw_favs = row['id'], row['name'], row['base_power']
                if name is None:
                    list_text += f"`ID {inv_id}` *Unknown Character*\n"
                else:
                    power = calculate_effective_power(raw_favs)
                    list_text += f"`ID {inv_id}` **{name}** — ⚔️ {power:,}\n"

            embed.add_field(name="Strongest Units", value=list_text or "No items found.", inline=False)
            embed.set_footer(text="Equip with: !set_team <ID> <ID> <ID> ...")
            await ctx.send(embed=embed)
        finally:
            await conn.close()

async def setup(bot):
    await bot.add_cog(Gacha(bot))