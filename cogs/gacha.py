import discord
from discord.ext import commands
import aiohttp
import random
import os
import asyncio

# Custom Modules
from core.database import get_db_connection, add_character_to_inventory, cache_character, get_user
from core.game_math import calculate_effective_power
from core.image_gen import generate_10_pull_image

class Gacha(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.anilist_url = os.getenv("ANILIST_URL", "https://graphql.anilist.co")

    def roll_rarity(self):
        """Standard Gacha rates: SSR 1%, SR 10%, R 89%."""
        roll = random.random() * 100
        if roll < 1: return "SSR"
        if roll < 11: return "SR"
        return "R"

    def get_rank_by_rarity(self, rarity):
        ranks = {"SSR": "S", "SR": "A", "R": "B"}
        return ranks.get(rarity, "C")

    async def fetch_character_data(self):
        """Fetches a random character from AniList."""
        query = """
        query ($page: Int) {
            Page(page: $page, perPage: 1) {
                characters(sort: FAVOURITES_DESC) {
                    id
                    name { full }
                    image { large }
                    favourites
                }
            }
        }
        """
        # Randomize page to get diverse characters
        variables = {'page': random.randint(1, 10000)}
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(self.anilist_url, json={'query': query, 'variables': variables}) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        chars = data['data']['Page']['characters']
                        if chars:
                            char = chars[0]
                            return {
                                'id': char['id'],
                                'name': char['name']['full'],
                                'image_url': char['image']['large'],
                                'favs': char['favourites']
                            }
            except Exception as e:
                print(f"AniList API Error: {e}")
        return None

    async def get_valid_character(self):
        """Retries character fetch if API fails."""
        for _ in range(3):
            data = await self.fetch_character_data()
            if data:
                rarity = self.roll_rarity()
                data.update({
                    'rarity': rarity,
                    'rank': self.get_rank_by_rarity(rarity)
                })
                return data
        return None

    @commands.command(name="pull")
    async def pull_character(self, ctx, amount: int = 1):
        if amount not in [1, 10]:
            await ctx.send("❌ You can only pull **1** or **10** times.")
            return

        # CRITICAL FIX: Ensure user exists in the 'users' table first.
        # This prevents the 'inventory' table from hanging on a Foreign Key error.
        await get_user(ctx.author.id)

        loading_msg = await ctx.send(f"🎰 *Initiating {amount}-Pull Protocol...*")
        
        try:
            pulled_chars = []
            for _ in range(amount):
                char_data = await self.get_valid_character()
                if char_data:
                    pulled_chars.append(char_data)

            if not pulled_chars:
                await loading_msg.edit(content="❌ Failed to connect to character database.")
                return

            # Pity Mechanic for 10-pulls (Guaranteed SR+)
            if amount == 10:
                has_good_pull = any(c['rarity'] in ["SR", "SSR"] for c in pulled_chars)
                if not has_good_pull:
                    # Replace the last character with a guaranteed SR
                    sr_char = await self.get_valid_character()
                    sr_char['rarity'] = "SR"
                    sr_char['rank'] = "A"
                    pulled_chars[-1] = sr_char

            # Save results to database
            for char in pulled_chars:
                await cache_character(char['id'], char['name'], char['image_url'], char['favs'])
                await add_character_to_inventory(str(ctx.author.id), char['id'])

            if amount == 1:
                char = pulled_chars[0]
                embed = discord.Embed(title=f"✨ {char['name']}", color=0x00ff00)
                embed.add_field(name="Rarity", value=f"**{char['rarity']}**", inline=True)
                embed.set_image(url=char['image_url'])
                await loading_msg.delete()
                await ctx.send(embed=embed)
            else:
                await loading_msg.edit(content="🎨 *Generating results image...*")
                image_data = await generate_10_pull_image(pulled_chars)
                file = discord.File(fp=image_data, filename="10pull.png")
                await loading_msg.delete()
                await ctx.send(f"💫 **{ctx.author.name}'s 10-Pull Results**", file=file)

        except Exception as e:
            # ERROR LOGGING: This prevents the command from staying "stuck" silently.
            print(f"CRITICAL ERROR in !pull: {e}")
            await ctx.send(f"⚠️ An internal error occurred: `{e}`")

async def setup(bot):
    await bot.add_cog(Gacha(bot))