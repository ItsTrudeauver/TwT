import discord
from discord.ext import commands
import aiohttp
import json
import os
from core.database import get_db_pool
from core.game_math import calculate_effective_power
# Updated import to include get_skill_info
from core.skills import SKILL_DATA, get_skill_info
from core.emotes import Emotes

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

# --- NEW DROPDOWN CLASSES ---
class SkillDropdown(discord.ui.Select):
    def __init__(self):
        options = []
        # Sort skills alphabetically and slice to 25 (Discord's limit per dropdown)
        sorted_skills = sorted(list(SKILL_DATA.keys()))
        
        for skill_name in sorted_skills[:25]:
            options.append(discord.SelectOption(label=skill_name))

        super().__init__(placeholder="👇 Select a skill...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        skill_name = self.values[0]
        data = SKILL_DATA.get(skill_name)

        if not data:
            await interaction.response.send_message("❌ Error: Skill data unavailable.", ephemeral=True)
            return

        # Build the details embed
        embed = discord.Embed(title=f"✨ {skill_name}", description=data['description'], color=0x2ECC71)
        
        # Determine Context
        applies_map = {"b": "Battle", "e": "Expedition", "g": "Global"}
        context = applies_map.get(data['applies_in'], "Unknown")
        
        # Determine Attributes
        attrs = []
        if data['stackable']: attrs.append("Stackable")
        if data['overlap']: attrs.append("Overlap OK")
        attr_str = ", ".join(attrs) if attrs else "Unique / No Overlap"

        embed.add_field(name="Type", value=context, inline=True)
        embed.add_field(name="Attributes", value=attr_str, inline=True)
        embed.add_field(name="Raw Value", value=f"`{data['value']}`", inline=False)

        # Update the message with the embed and remove the dropdown
        await interaction.response.edit_message(content=None, embed=embed, view=None)

class SkillDropdownView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(SkillDropdown())
# ----------------------------

class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.anilist_url = os.getenv("ANILIST_URL", "https://graphql.anilist.co")
        
    @commands.command(name="whohas", aliases=["usersof", "skillsearch"])
    async def who_has_skill(self, ctx, *, skill_name: str):
        """
        Finds all characters that possess a specific skill (Case-Insensitive).
        Usage: !whohas Lucky 7
        """
        target_skill = skill_name.strip()
        pool = await get_db_pool()
        
        async with pool.acquire() as conn:
            # We cast to ::jsonb to ensure compatibility, then expand elements and check lowercase
            rows = await conn.fetch("""
                SELECT name, rarity, ability_tags 
                FROM characters_cache 
                WHERE EXISTS (
                    SELECT 1 
                    FROM jsonb_array_elements_text(ability_tags::jsonb) as tag 
                    WHERE LOWER(tag) = LOWER($1)
                )
            """, target_skill)

        if not rows:
            return await ctx.reply(f"🤷 **No known characters** possess the skill `{target_skill}`.")

        # Format Output
        msg = f"🔍 **Characters with '{target_skill}':**\n"
        
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

    # --- NEW FUNCTION HERE ---
    @commands.command(name="skill_details", aliases=["sd", "skillinfo"])
    async def skill_details(self, ctx, *, skill_name: str = None):
        """
        View detailed stats of a skill.
        Usage: !sd [skill name] OR !sd (to view dropdown)
        """
        # 1. Dropdown Mode
        if not skill_name:
            view = SkillDropdownView()
            return await ctx.reply("📖 **Select a skill to view details:**", view=view)

        # 2. Text Search Mode
        data = get_skill_info(skill_name)
        if not data:
            return await ctx.reply(f"❌ Skill `{skill_name}` not found.")

        # Find the correct casing for the Title
        real_name = skill_name
        for key in SKILL_DATA.keys():
            if key.lower() == skill_name.lower():
                real_name = key
                break

        embed = discord.Embed(title=f"✨ {real_name}", description=data['description'], color=0x2ECC71)
        
        # Formatting
        applies_map = {"b": "Battle", "e": "Expedition", "g": "Global"}
        context = applies_map.get(data['applies_in'], "Unknown")
        
        attrs = []
        if data['stackable']: attrs.append("Stackable")
        if data['overlap']: attrs.append("Overlap OK")
        attr_str = ", ".join(attrs) if attrs else "Unique / No Overlap"

        embed.add_field(name="Type", value=context, inline=True)
        embed.add_field(name="Attributes", value=attr_str, inline=True)
        embed.add_field(name="Raw Value", value=f"`{data['value']}`", inline=False)

        await ctx.reply(embed=embed)
    # -------------------------

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
                    
                emoji = getattr(Emotes, rarity, rarity)
                # 4. Embed Result
                embed = discord.Embed(title=char_data['name']['full'], url=char_data['siteUrl'], color=0x00BFFF)
                embed.set_thumbnail(url=char_data['image']['large'])
                
                embed.add_field(name="🆔", value=str(anilist_id), inline=True)
                embed.add_field(name="Rarity", value=f"{emoji}", inline=True)
                embed.add_field(name=f"Battle Power", value=f"**{power:,}**", inline=True)
                
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