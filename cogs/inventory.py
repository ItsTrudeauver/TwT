import discord
from discord.ext import commands
from core.database import get_inventory_details

class InventoryView(discord.ui.View):
    def __init__(self, pages, user):
        super().__init__(timeout=60)
        self.pages = pages
        self.user = user
        self.current_page = 0

    async def update_view(self, interaction: discord.Interaction):
        embed = self.pages[self.current_page]
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.gray)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            await self.update_view(interaction)
        else:
            await interaction.response.send_message("You are on the first page!", ephemeral=True)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.gray)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < len(self.pages) - 1:
            self.current_page += 1
            await self.update_view(interaction)
        else:
            await interaction.response.send_message("You are on the last page!", ephemeral=True)

class Inventory(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="inventory", aliases=["inv"])
    async def inventory(self, ctx, sort_style: str = "date"):
        """
        Displays user inventory. 
        Usage: !inv [date | power | dupes]
        """
        valid_sorts = ["date", "power", "dupes"]
        if sort_style.lower() not in valid_sorts:
            return await ctx.send(f"❌ Invalid sort. Use: `{', '.join(valid_sorts)}`")

        inventory_data = await get_inventory_details(ctx.author.id, sort_style.lower())

        if not inventory_data:
            return await ctx.send("Your inventory is currently empty. Go pull some characters!")

        # 1. Paginate the data (10 items per page)
        items_per_page = 10
        pages = []
        
        for i in range(0, len(inventory_data), items_per_page):
            chunk = inventory_data[i : i + items_per_page]
            embed = discord.Embed(
                title=f"🎒 {ctx.author.name}'s Inventory",
                description=f"Sorting by: **{sort_style.upper()}**",
                color=discord.Color.blue()
            )
            
            description_text = ""
            for item in chunk:
                name = item['name'] or f"Unknown ({item['anilist_id']})"
                # Updated to use the new true_power and rank fields
                power = item['true_power'] or 0
                rank_num = item['rank'] or 10000
                rarity = item['rarity'] or "R"
                dupes = item['dupe_count']
                
                # Format: Name [Rarity] | Rank | Power | Dupes
                description_text += f"• **{name}** [{rarity}]\n└ Rank: `#{rank_num}` | Power: `{power:,}` | Dupes: `{dupes}`\n"
            
            embed.description += f"\n\n{description_text}"
            embed.set_footer(text=f"Page {len(pages) + 1} of {(len(inventory_data) // items_per_page) + 1} | Total Characters: {len(inventory_data)}")
            pages.append(embed)

        # 2. Send initial message with View
        if pages:
            view = InventoryView(pages, ctx.author)
            await ctx.send(embed=pages[0], view=view)

async def setup(bot):
    await bot.add_cog(Inventory(bot))