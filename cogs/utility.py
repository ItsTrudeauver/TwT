import discord
from discord.ext import commands
import aiohttp
import json
import os
from core.database import get_db_pool
from core.game_math import calculate_effective_power
from core.skills import SKILL_DATA
class SkillPagination(discord.ui.View):
    def __init__(self, pages):
        super().__init__(timeout=60)  # Buttons disable after 60 seconds
        self.pages = pages
        self.current_page = 0

    async def update_view(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.gray)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            await self.update_view(interaction)
        else:
            await interaction.response.send_message("You are on the first page.", ephemeral=True)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.gray)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < len(self.pages) - 1:
            self.current_page += 1
            await self.update_view(interaction)
        else:
            await interaction.response.send_message("You are on the last page.", ephemeral=True)
            
class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.anilist_url = os.getenv("ANILIST_URL", "https://graphql.anilist.co")
        
    @commands.command(name="whohas", aliases=["usersof", "skillsearch"])
    async def who_has_skill(self, ctx, *, skill_name: str):
        """
        Finds all characters that possess a specific skill.
        Usage: !whohas Lucky 7
        """
        # 1. Clean input (Title Case helps with matching if your DB is consistent)
        # However, it's safer to rely on exact match or ILIKE. 
        # Since ability_tags is JSONB, case sensitivity matters.
        # We will try exact match first.
        
        target_skill = skill_name.strip()
        
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            # PostgreSQL Operator '?' checks if a string exists in a JSONB array
            rows = await conn.fetch("""
                SELECT name, rarity, ability_tags 
                FROM characters_cache 
                WHERE ability_tags ? $1
            """, target_skill)
            
            # If exact match fails, try a broader search (slower but helpful)
            # This fetches ALL chars and checks in python (fallback for case-insensitivity)
            if not rows:
                all_chars = await conn.fetch("SELECT name, rarity, ability_tags FROM characters_cache")
                rows = [
                    row for row in all_chars 
                    if any(s.lower() == target_skill.lower() for s in (row['ability_tags'] or []))
                ]

        if not rows:
            return await ctx.reply(f"🤷 **No known characters** possess the skill `{target_skill}`.")

        # 2. Format Output
        msg = f"🔍 **Characters with '{target_skill}':**\n"
        
        # Limit list length to avoid Discord 2000 char limit
        lines = []
        for row in rows:
            lines.append(f"• **{row['name']}** ({row['rarity']})")
        
        if len(lines) > 20:
            msg += "\n".join(lines[:20])
            msg += f"\n...and {len(lines)-20} more."
        else:
            msg += "\n".join(lines)

        await ctx.reply(msg)
    
    @commands.command(name="skills", aliases=["sl"])
    async def list_skills(self, ctx):
        """Displays all available skills using a paginated menu."""
        
        # Split skills into chunks of 5 per page
        skill_items = list(SKILL_DATA.items())
        chunks = [skill_items[i:i + 5] for i in range(0, len(skill_items), 5)]
        pages = []

        for idx, chunk in enumerate(chunks):
            embed = discord.Embed(
                title="✨ Character Skills",
                description="List of battle/expedition abilities.",
                color=0xF1C40F
            )
            
            for skill_name, data in chunk:
                # Formatting context labels
                context = "Battle" if data['applies_in'] == "b" else "Expedition"
                if data['applies_in'] == "g": context = "Global"
                
                tags = []
                if data['stackable']: tags.append("Stackable")
                if data['overlap']: tags.append("Overlap OK")
                attr_text = f"**[{context}]** " + (" | ".join(tags) if tags else "Unique")
                
                embed.add_field(
                    name=f"**{skill_name}**",
                    value=f"{data['description']}\n*{attr_text}*",
                    inline=False
                )
            
            embed.set_footer(text=f"Page {idx + 1} of {len(chunks)}")
            pages.append(embed)

        if not pages:
            return await ctx.reply("No skills found.")

        view = SkillPagination(pages)
        await ctx.reply(embed=pages[0], view=view)

    @commands.command(name="lookup")
    async def lookup(self, ctx, *, name: str):
        """
        Searches for a character.
        - Checks DB Cache first.
        - Fallback: Uses Gacha Cog's JSON Map (100% Accurate).
        """
        loading = await ctx.reply(f"🔍 Searching for **{name}**...")

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
                await ctx.reply(embed=embed)

            except Exception as e:
                await loading.edit(content=f"⚠️ Error: `{e}`")

async def setup(bot):
    await bot.add_cog(Utility(bot))