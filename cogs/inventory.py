import discord
from discord.ext import commands
from core.database import get_inventory_details

class InventoryPagination(discord.ui.View):
    def __init__(self, pages, user):
        super().__init__(timeout=60)
        self.pages = pages
        self.user = user
        self.index = 0

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user != self.user:
            await interaction.response.send_message("This isn't your inventory menu!", ephemeral=True)
            return False
        return True

    async def update_page(self, interaction: discord.Interaction):
        embed = self.pages[self.index]
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.gray)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.index > 0:
            self.index -= 1
            await self.update_page(interaction)
        else:
            await interaction.response.send_message("You are already on the first page.", ephemeral=True)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.gray)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.index < len(self.pages) - 1:
            self.index += 1
            await self.update_page(interaction)
        else:
            await interaction.response.send_message("You are already on the last page.", ephemeral=True)

class Inventory(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="inventory", aliases=["inv"])
    async def inventory(self, ctx, sort: str = "date"):
        """Usage: !inv [date | power | dupes]"""
        valid_sorts = ["date", "power", "dupes"]
        sort_choice = sort.lower()
        
        if sort_choice not in valid_sorts:
            await ctx.send(f"❌ Invalid sort. Use: `{', '.join(valid_sorts)}`")
            return

        data = await get_inventory_details(ctx.author.id, sort_choice)
        
        if not data:
            await ctx.send("Your inventory is empty. Start pulling characters with `!pull`!")
            return

        items_per_page = 10
        chunks = [data[i:i + items_per_page] for i in range(0, len(data), items_per_page)]
        pages = []
        
        for idx, chunk in enumerate(chunks):
            embed = discord.Embed(
                title=f"🎒 {ctx.author.name}'s Collection",
                description=f"Sorting by: **{sort_choice.upper()}**",
                color=0x3498db
            )
            
            # Added User Avatar as Thumbnail
            embed.set_thumbnail(url=ctx.author.display_avatar.url)
            
            lines = []
            for c in chunk:
                name = c['name'] or f"Unknown ID:{c['anilist_id']}"
                rarity = c['rarity'] or "R"
                char_id = c['id'] # Requires 'id' to be fetched in database.py
                power = c['true_power'] or 0
                dupes = c['dupe_count']
                
                # Updated to show ID and ⚔️ emoji
                lines.append(f"**{name}** [{rarity}]")
                lines.append(f"└ ID: `{char_id}` | ⚔️: `{power:,}` | Dupes: `{dupes}`")
            
            embed.description += "\n\n" + "\n".join(lines)
            embed.set_footer(text=f"Page {idx+1}/{len(chunks)} • Total Characters: {len(data)}")
            pages.append(embed)

        view = InventoryPagination(pages, ctx.author)
        await ctx.send(embed=pages[0], view=view)

async def setup(bot):
    await bot.add_cog(Inventory(bot))