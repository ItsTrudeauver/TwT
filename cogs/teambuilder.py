import discord
from discord.ext import commands
from discord.ui import View, Select, Button
from core.database import get_db_pool

class TeamBuilderView(View):
    def __init__(self, ctx, inventory_data):
        super().__init__(timeout=300)
        self.ctx = ctx
        self.inventory = inventory_data # Full list of all units
        self.filtered_inventory = inventory_data # Currently visible list (filtered)
        self.team = [] # The 5 selected units
        self.page = 0
        self.items_per_page = 25
        self.current_rarity_filter = "ALL"

        # UI Components
        self.filter_select = None
        self.unit_select = None
        self.remove_select = None
        
        self.setup_ui()
        self.update_components()

    def setup_ui(self):
        # 1. Rarity Filter
        self.filter_select = Select(
            placeholder="Filter by Rarity",
            options=[
                discord.SelectOption(label="All Rarities", value="ALL", default=True),
                discord.SelectOption(label="SSR Only", value="SSR"),
                discord.SelectOption(label="SR Only", value="SR"),
                discord.SelectOption(label="R Only", value="R")
            ],
            row=0
        )
        self.filter_select.callback = self.on_filter_change
        self.add_item(self.filter_select)

        # 2. Unit Picker (Placeholder, populated dynamically)
        self.unit_select = Select(placeholder="Select Units to Add...", min_values=1, max_values=1, row=1)
        self.unit_select.callback = self.on_unit_select
        self.add_item(self.unit_select)

        # 3. Remove Picker (Placeholder, populated dynamically)
        self.remove_select = Select(placeholder="Remove from Team...", min_values=1, max_values=1, row=2, disabled=True)
        self.remove_select.callback = self.on_remove_select
        self.add_item(self.remove_select)

        # 4. Pagination Buttons
        self.prev_btn = Button(label="◀ Prev", style=discord.ButtonStyle.secondary, row=3, disabled=True)
        self.prev_btn.callback = self.on_prev
        self.add_item(self.prev_btn)

        self.next_btn = Button(label="Next ▶", style=discord.ButtonStyle.secondary, row=3, disabled=True)
        self.next_btn.callback = self.on_next
        self.add_item(self.next_btn)

        # 5. Clear Button
        clear_btn = Button(label="Clear Team", style=discord.ButtonStyle.danger, row=3)
        clear_btn.callback = self.on_clear
        self.add_item(clear_btn)

    def apply_filter(self):
        """Filters the master inventory list based on selected rarity."""
        if self.current_rarity_filter == "ALL":
            self.filtered_inventory = self.inventory
        else:
            self.filtered_inventory = [u for u in self.inventory if u['rarity'] == self.current_rarity_filter]
        
        self.page = 0 # Reset to page 1 on filter change

    def update_components(self):
        """Refreshes the Select Menus based on current state."""
        
        # --- Update Unit Selector (Row 1) ---
        start = self.page * self.items_per_page
        end = start + self.items_per_page
        current_page_items = self.filtered_inventory[start:end]

        options = []
        for unit in current_page_items:
            # Check if already in team to mark visually (optional, but good UX)
            is_selected = any(u['id'] == unit['id'] for u in self.team)
            label = f"{'✅ ' if is_selected else ''}[{unit['rarity']}] {unit['name'][:50]}"
            desc = f"Pwr: {unit['power']:,} | Dupe: {unit['dupe']} | ID: {unit['id']}"
            
            options.append(discord.SelectOption(
                label=label,
                description=desc,
                value=str(unit['id'])
            ))

        if not options:
            self.unit_select.options = [discord.SelectOption(label="No units found", value="none")]
            self.unit_select.disabled = True
        else:
            self.unit_select.options = options
            self.unit_select.disabled = False

        # --- Update Pagination Buttons (Row 3) ---
        self.prev_btn.disabled = (self.page == 0)
        self.next_btn.disabled = (end >= len(self.filtered_inventory))

        # --- Update Remove Selector (Row 2) ---
        if not self.team:
            self.remove_select.options = [discord.SelectOption(label="Team Empty", value="none")]
            self.remove_select.disabled = True
        else:
            remove_opts = []
            for unit in self.team:
                remove_opts.append(discord.SelectOption(
                    label=f"{unit['name'][:80]}", 
                    value=str(unit['id']),
                    emoji="❌"
                ))
            self.remove_select.options = remove_opts
            self.remove_select.disabled = False

    async def generate_embed(self):
        """Generates the display embed and code blocks."""
        desc = "Use the dropdowns below to build your team.\n\n"
        
        # Team Display
        if not self.team:
            desc += "🚫 **Current Team:** (Empty)"
        else:
            desc += "✅ **Current Team:**\n"
            for i, unit in enumerate(self.team, 1):
                desc += f"`{i}.` **{unit['name']}** (ID: {unit['id']})\n"

        # Generate Code Blocks
        if self.team:
            ids_str = " ".join([str(u['id']) for u in self.team])
            desc += f"\n**Copy & Paste Commands:**"
            desc += f"\n⚔️ Battle Team:\n```!stb {ids_str}```"
            desc += f"\n🗺️ Expedition Team:\n```!se {ids_str}```"
        else:
            desc += "\n*Select units to generate command strings.*"

        embed = discord.Embed(
            title="🛠️ Team Builder",
            description=desc,
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"Page {self.page + 1} | Filter: {self.current_rarity_filter} | {len(self.filtered_inventory)} Units Found")
        return embed

    # --- Callbacks ---

    async def on_filter_change(self, interaction: discord.Interaction):
        self.current_rarity_filter = self.filter_select.values[0]
        self.apply_filter()
        self.update_components()
        await interaction.response.edit_message(embed=await self.generate_embed(), view=self)

    async def on_unit_select(self, interaction: discord.Interaction):
        selected_id = int(self.unit_select.values[0])
        
        # Find unit data
        unit = next((u for u in self.inventory if u['id'] == selected_id), None)
        
        if not unit:
            return await interaction.response.send_message("Error: Unit not found.", ephemeral=True)

        # Check limits
        if len(self.team) >= 5:
            return await interaction.response.send_message("❌ Team is full (Max 5). Remove a unit first.", ephemeral=True)
        
        if any(u['id'] == selected_id for u in self.team):
             return await interaction.response.send_message("⚠️ Unit is already in the team.", ephemeral=True)

        self.team.append(unit)
        self.update_components()
        await interaction.response.edit_message(embed=await self.generate_embed(), view=self)

    async def on_remove_select(self, interaction: discord.Interaction):
        remove_id = int(self.remove_select.values[0])
        self.team = [u for u in self.team if u['id'] != remove_id]
        
        self.update_components()
        await interaction.response.edit_message(embed=await self.generate_embed(), view=self)

    async def on_prev(self, interaction: discord.Interaction):
        if self.page > 0:
            self.page -= 1
            self.update_components()
            await interaction.response.edit_message(embed=await self.generate_embed(), view=self)

    async def on_next(self, interaction: discord.Interaction):
        self.page += 1
        self.update_components()
        await interaction.response.edit_message(embed=await self.generate_embed(), view=self)

    async def on_clear(self, interaction: discord.Interaction):
        self.team = []
        self.update_components()
        await interaction.response.edit_message(embed=await self.generate_embed(), view=self)

class TeamBuilder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="teambuilder", aliases=["tb"])
    async def teambuilder(self, ctx):
        """Opens the interactive Team Builder UI."""
        loading_msg = await ctx.reply("🔄 **Loading your inventory...**")

        pool = await get_db_pool()
        async with pool.acquire() as conn:
            # Fetch inventory joined with character cache for names/power
            rows = await conn.fetch("""
                SELECT i.id, c.name, c.true_power, i.dupe_level, c.rarity 
                FROM inventory i
                JOIN characters_cache c ON i.anilist_id = c.anilist_id
                WHERE i.user_id = $1
                ORDER BY c.true_power DESC
            """, str(ctx.author.id))

        if not rows:
            return await loading_msg.edit(content="❌ You have no units in your inventory!")

        # Convert to lightweight dict list
        inventory_data = [
            {
                "id": r['id'], 
                "name": r['name'], 
                "power": r['true_power'], 
                "dupe": r['dupe_level'], 
                "rarity": r['rarity']
            } 
            for r in rows
        ]

        view = TeamBuilderView(ctx, inventory_data)
        embed = await view.generate_embed()
        
        await loading_msg.delete()
        await ctx.send(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(TeamBuilder(bot))