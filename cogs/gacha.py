import discord
from discord.ext import commands
import aiosqlite
import aiohttp
import random
import os
import asyncio

# Custom Modules
from core.database import DB_PATH, add_character_to_inventory, cache_character
from core.game_math import calculate_effective_power
from core.image_gen import generate_10_pull_image


class Gacha(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.anilist_url = os.getenv("ANILIST_URL")

    # --- 1. CORE GACHA MECHANICS ---
    def roll_rarity(self):
        roll = random.uniform(0, 100)
        if roll <= 1.0: return "SSR"
        elif roll <= 10.0: return "SR"
        else: return "R"

    def get_rank_by_rarity(self, rarity):
        if rarity == "SSR": return random.randint(1, 250)
        elif rarity == "SR": return random.randint(251, 1500)
        else: return random.randint(1501, 10000)

    # --- 2. API & RETRY ENGINE ---
    async def fetch_character_data(self, rank):
        query = '''
        query ($rank: Int) {
            Page (page: $rank, perPage: 1) {
                characters (sort: FAVOURITES_DESC) {
                    id
                    name { full }
                    image { large }
                    favourites
                }
            }
        }
        '''
        variables = {'rank': rank}
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(self.anilist_url,
                                        json={
                                            'query': query,
                                            'variables': variables
                                        }) as resp:
                    if resp.status == 429:
                        await asyncio.sleep(2)
                        return None
                    if resp.status != 200:
                        return None

                    data = await resp.json()
                    chars = data.get('data', {}).get('Page',
                                                     {}).get('characters')

                    if not chars: return None

                    char = chars[0]
                    img_url = char.get('image', {}).get('large')
                    if not img_url or "default.jpg" in img_url or "default.png" in img_url:
                        return None

                    return char
            except:
                return None

    async def get_valid_character(self, forced_rarity=None):
        attempts = 0
        while attempts < 7:
            rarity = forced_rarity if forced_rarity else self.roll_rarity()
            rank = self.get_rank_by_rarity(rarity)

            data = await self.fetch_character_data(rank)

            if data:
                return {
                    'id': data['id'],
                    'name': data['name']['full'],
                    'image_url': data['image']['large'],
                    'favs': data['favourites'],
                    'rarity': rarity,
                    'power': calculate_effective_power(data['favourites'])
                }
            attempts += 1
            await asyncio.sleep(0.2)
        return None

    # --- 3. COMMANDS ---

    @commands.command(name="pull")
    async def pull_character(self, ctx, amount: int = 1):
        if amount not in [1, 10]:
            await ctx.send("❌ You can only pull **1** or **10** times.")
            return

        loading_msg = await ctx.send(
            f"🎰 *Initiating {amount}-Pull Protocol...*")
        pulled_chars = []

        for _ in range(amount):
            char_data = await self.get_valid_character()
            if char_data:
                pulled_chars.append(char_data)

        # Mercy Rule
        if amount == 10 and pulled_chars:
            has_good_pull = any(c['rarity'] in ["SR", "SSR"]
                                for c in pulled_chars)
            if not has_good_pull:
                guaranteed = await self.get_valid_character(forced_rarity="SR")
                if guaranteed:
                    pulled_chars[-1] = guaranteed

        if not pulled_chars:
            await loading_msg.edit(
                content="❌ Connection Error. AniList is unreachable.")
            return

        # Save to DB
        for char in pulled_chars:
            await cache_character(char['id'], char['name'], char['image_url'],
                                  char['favs'])
            await add_character_to_inventory(str(ctx.author.id), char['id'])

        # Display
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
        """
        Lists your characters sorted by Power (Highest First).
        """
        items_per_page = 10
        offset = (page - 1) * items_per_page

        try:
            async with aiosqlite.connect(DB_PATH) as db:
                # 1. Count Total
                cursor = await db.execute(
                    "SELECT COUNT(*) FROM inventory WHERE user_id = ?",
                    (str(ctx.author.id), ))
                total_items = (await cursor.fetchone())[0]

                if total_items == 0:
                    await ctx.send(
                        "🎒 Your inventory is empty. Try `!pull` first!")
                    return

                max_pages = (total_items // items_per_page) + 1
                if page > max_pages:
                    page = max_pages

                # 2. Fetch Data (FIXED: Using c.base_power instead of c.favourites)
                sql = """
                SELECT i.id, c.name, c.base_power
                FROM inventory i
                LEFT JOIN characters_cache c ON i.anilist_id = c.anilist_id
                WHERE i.user_id = ?
                ORDER BY c.base_power DESC
                LIMIT ? OFFSET ?
                """
                cursor = await db.execute(
                    sql, (str(ctx.author.id), items_per_page, offset))
                rows = await cursor.fetchall()

            # 3. Build Embed
            embed = discord.Embed(
                title=f"🎒 Inventory - {ctx.author.name}",
                description=
                f"**Page {page}/{max_pages}** | Total Units: {total_items}",
                color=discord.Color.dark_grey())

            list_text = ""
            for row in rows:
                inv_id, name, raw_favs = row

                if name is None:
                    list_text += f"`ID {inv_id}` *Unknown Character* (Cache Missing)\n"
                else:
                    # raw_favs IS base_power in the DB, so we use it to calculate effective power
                    power = calculate_effective_power(raw_favs)
                    list_text += f"`ID {inv_id}` **{name}** — ⚔️ {power:,}\n"

            if not list_text:
                list_text = "No items found."

            embed.add_field(name="Strongest Units",
                            value=list_text,
                            inline=False)
            embed.set_footer(text="Equip with: !set_team <ID> <ID> <ID> ...")

            await ctx.send(embed=embed)

        except Exception as e:
            print(f"❌ ERROR: {e}")
            await ctx.send(f"⚠️ Inventory Error: {e}")


async def setup(bot):
    await bot.add_cog(Gacha(bot))
