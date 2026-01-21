import discord
from discord.ext import commands
import aiohttp
import json
import os
from core.database import get_db_pool
from core.game_math import calculate_effective_power

class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.anilist_url = os.getenv("ANILIST_URL", "https://graphql.anilist.co")

    @commands.command(name="lookup")
    async def lookup(self, ctx, *, name: str):
        """
        Searches for a character.
        - Checks DB Cache first.
        - Fallback: Uses Gacha Cog's JSON Map (100% Accurate).
        """
        loading = await ctx.send(f"🔍 Searching for **{name}**...")

        query = """
        query ($search: String) {
            Character(search: $search) {
                id name { full } image { large } favourites siteUrl
            }
        }
        """
        async with aiohttp.ClientSession() as session:
            try:
                # 1. AniList Basic Data
                async with session.post(self.anilist_url, json={'query': query, 'variables': {'search': name}}) as resp:
                    if resp.status != 200: return await loading.edit(content="❌ API Error.")
                    data = await resp.json()
                    if 'errors' in data: return await loading.edit(content="❌ Not found.")
                    
                    char_data = data['data']['Character']
                    anilist_id = char_data['id']
                    favs = char_data['favourites']

                # 2. Check Database Cache
                pool = await get_db_pool()
                db_char = await pool.fetchrow("SELECT rarity, true_power, ability_tags FROM characters_cache WHERE anilist_id = $1", anilist_id)

                if db_char:
                    rarity = db_char['rarity']
                    power = db_char['true_power']
                    skills = json.loads(db_char['ability_tags'])
                    source_text = "Checking Database..."
                else:
                    # 3. USE LOCAL RANKINGS FROM GACHA COG
                    gacha_cog = self.bot.get_cog("Gacha")
                    if gacha_cog:
                        # This is the "Backwards Implementation" in action:
                        rank = gacha_cog.get_cached_rank(anilist_id)
                        rarity = gacha_cog.determine_rarity(rank)
                        power = calculate_effective_power(favs, rarity, rank)
                        skills = []
                        source_text = "Calculated via Rankings.json"
                    else:
                        return await loading.edit(content="❌ Gacha System Offline.")

                # 4. Embed Result
                embed = discord.Embed(title=char_data['name']['full'], url=char_data['siteUrl'], color=0x00BFFF)
                embed.set_thumbnail(url=char_data['image']['large'])
                
                embed.add_field(name="🆔 ID", value=str(anilist_id), inline=True)
                embed.add_field(name="💎 Rarity", value=f"**{rarity}**", inline=True)
                embed.add_field(name="⚔️ Battle Power", value=f"**{power:,}**", inline=True)
                
                if skills:
                    embed.add_field(name="✨ Skills", value="\n".join([f"• {s}" for s in skills]), inline=False)
                else:
                    embed.add_field(name="✨ Skills", value="*None*", inline=False)
                
                embed.set_footer(text=f"{source_text} | Rank #{rank if 'rank' in locals() else '???'}")
                
                await loading.delete()
                await ctx.send(embed=embed)

            except Exception as e:
                await loading.edit(content=f"⚠️ Error: `{e}`")

async def setup(bot):
    await bot.add_cog(Utility(bot))