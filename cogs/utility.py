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
        Prioritizes cached data (Skills/Power).
        Calculates fresh stats via Game Math if not in cache.
        """
        loading = await ctx.send(f"🔍 Searching for **{name}**...")

        # 1. Search AniList for the ID and basic stats
        search_query = """
        query ($search: String) {
            Character(search: $search) {
                id
                name { full }
                image { large }
                favourites
                siteUrl
            }
        }
        """
        
        async with aiohttp.ClientSession() as session:
            try:
                # --- FETCH BASIC INFO ---
                async with session.post(self.anilist_url, json={'query': search_query, 'variables': {'search': name}}) as resp:
                    if resp.status != 200:
                        return await loading.edit(content=f"❌ AniList API Error: {resp.status}")
                    
                    data = await resp.json()
                    if 'errors' in data or not data.get('data') or not data['data'].get('Character'):
                        return await loading.edit(content=f"❌ Character **{name}** not found.")
                    
                    char_data = data['data']['Character']
                    anilist_id = char_data['id']
                    favs = char_data['favourites']

                # 2. Check Database Cache (Priority)
                pool = await get_db_pool()
                db_char = await pool.fetchrow("""
                    SELECT rarity, true_power, ability_tags 
                    FROM characters_cache 
                    WHERE anilist_id = $1
                """, anilist_id)

                if db_char:
                    # USE CACHED DATA
                    rarity = db_char['rarity']
                    power = db_char['true_power']
                    skills = json.loads(db_char['ability_tags'])
                    source_text = "Checking Database..."
                else:
                    # 3. USE GAME MATH (Fresh Calculation)
                    # We must fetch the actual Rank to determine Rarity/Power accurately.
                    rank_query = """
                    query ($favs: Int) {
                        Page(perPage: 1) {
                            pageInfo { total }
                            characters(favourites_greater: $favs) { id }
                        }
                    }
                    """
                    async with session.post(self.anilist_url, json={'query': rank_query, 'variables': {'favs': favs}}) as rank_resp:
                        if rank_resp.status != 200:
                             return await loading.edit(content="❌ Could not fetch Rank data (AniList 400/500).")
                        
                        rank_data = await rank_resp.json()
                        rank = rank_data['data']['Page']['pageInfo']['total'] + 1
                    
                    # Exact Rarity Logic
                    if rank <= 250: rarity = "SSR"
                    elif rank <= 1500: rarity = "SR"
                    else: rarity = "R"

                    # Calculate using your math file
                    power = calculate_effective_power(favs, rarity, rank)
                    skills = [] # Not in DB, so no skills yet
                    source_text = "Calculated via Game Math"

                # 4. Build Embed
                embed = discord.Embed(title=char_data['name']['full'], url=char_data['siteUrl'], color=0x00BFFF)
                embed.set_thumbnail(url=char_data['image']['large'])
                
                # Stats Row
                embed.add_field(name="🆔 ID", value=f"`{anilist_id}`", inline=True)
                embed.add_field(name="💎 Rarity", value=f"**{rarity}**", inline=True)
                embed.add_field(name="⚔️ Battle Power", value=f"**{power:,}**", inline=True)
                
                # Skills Row
                if skills:
                    skill_str = "\n".join([f"• {s}" for s in skills])
                    embed.add_field(name="✨ Skills", value=skill_str, inline=False)
                else:
                    embed.add_field(name="✨ Skills", value="*None (Base Unit)*", inline=False)

                embed.set_footer(text=f"{source_text} | Rank #{favs:,} Favs")
                
                await loading.delete()
                await ctx.send(embed=embed)

            except Exception as e:
                await loading.edit(content=f"⚠️ Lookup Error: `{e}`")

async def setup(bot):
    await bot.add_cog(Utility(bot))