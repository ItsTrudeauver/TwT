import discord
from discord.ext import commands
from discord.ui import View, Button
import random
import os
from core.economy import get_item_display_name
from core.database import get_db_pool
from core.game_math import calculate_effective_power
from core.image_gen import generate_team_image


class RPG(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def get_team_data(self, user_id):
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT slot_1, slot_2, slot_3, slot_4, slot_5 FROM teams WHERE user_id = $1", str(user_id))
            
            if not row:
                return 0, [None] * 5

            team_list = []
            total_power = 0
            slot_ids = [row['slot_1'], row['slot_2'], row['slot_3'], row['slot_4'], row['slot_5']]
            
            for char_id in slot_ids:
                if char_id is None:
                    team_list.append(None)
                    continue
                
                # UPDATED: This query now pulls dupe_level from inventory to calculate boosted power
                #
                # UPDATED SQL
                char_data = await conn.fetchrow("""
                    SELECT 
                        c.name, 
                        c.image_url, 
                        FLOOR(
                            c.true_power 
                            * (1 + (i.dupe_level * 0.05)) 
                            * (1 + (u.team_level * 0.01)) -- Team Level Bonus
                        )::int as true_power, 
                        c.rarity, 
                        c.rarity_override, 
                        c.ability_tags 
                    FROM inventory i
                    JOIN characters_cache c ON i.anilist_id = c.anilist_id
                    JOIN users u ON i.user_id = u.user_id
                    WHERE i.id = $1
                """, char_id)
                
                if char_data:
                    power = int(char_data['true_power'])
                    total_power += power
                    team_list.append({
                        'name': char_data['name'], 
                        'image_url': char_data['image_url'], 
                        'rarity': char_data['rarity_override'] or char_data['rarity'], 
                        'power': power,
                        'ability_tags': char_data['ability_tags']
                    })
                else:
                    team_list.append(None)

            return total_power, team_list

    @commands.command(name="set_team_battle", aliases=['stb', 'sbt', 'st'])
    async def set_team(self, ctx, s1: int, s2: int = None, s3: int = None, s4: int = None, s5: int = None):
        slots = [s1, s2, s3, s4, s5]
        clean_slots = [s for s in slots if s is not None]
        
        if len(set(clean_slots)) != len(clean_slots):
            await ctx.reply("❌ Duplicate IDs detected!")
            return

        pool = await get_db_pool()
        async with pool.acquire() as conn:
            owned = await conn.fetch("SELECT id FROM inventory WHERE user_id = $1 AND id = ANY($2)", 
                                    str(ctx.author.id), clean_slots)
            
            if len(owned) != len(clean_slots):
                await ctx.reply("❌ You do not own one of those IDs.")
                return

            final_slots = clean_slots + [None] * (5 - len(clean_slots))
            await conn.execute("""
                INSERT INTO teams (user_id, slot_1, slot_2, slot_3, slot_4, slot_5)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT(user_id) DO UPDATE SET
                    slot_1=EXCLUDED.slot_1, slot_2=EXCLUDED.slot_2,
                    slot_3=EXCLUDED.slot_3, slot_4=EXCLUDED.slot_4,
                    slot_5=EXCLUDED.slot_5
            """, str(ctx.author.id), *final_slots)
            
            await ctx.reply(f"✅ Squad composition updated.")

    @commands.command(name="team")
    async def view_team(self, ctx, user: discord.Member = None):
        target = user or ctx.author
        loading = await ctx.reply("🛡️ *Analyzing Squad Composition...*")
        power, team_list = await self.get_team_data(target.id)
        
        try:
            image_data = await generate_team_image(team_list)
            file = discord.File(fp=image_data, filename="team_banner.png")
            await loading.delete()
            await ctx.reply(content=f"**Officer:** {target.name} | **Power:** {power:,}", file=file)
        except Exception as e:
            await loading.edit(content=f"⚠️ Visual Error: {e}")

    @commands.command(name="save_team")
    async def save_team_preset(self, ctx, name: str):
        """Saves your CURRENT active team to a preset slot."""
        if len(name) > 15:
            return await ctx.reply("❌ Name too long (max 15 chars).")

        pool = await get_db_pool()
        async with pool.acquire() as conn:
            # 1. Fetch current active team
            current = await conn.fetchrow("SELECT slot_1, slot_2, slot_3, slot_4, slot_5 FROM teams WHERE user_id = $1", str(ctx.author.id))
            
            if not current:
                return await ctx.reply("❌ You don't have a team equipped to save.")

            # 2. Save to presets table
            await conn.execute("""
                INSERT INTO team_presets (user_id, preset_name, slot_1, slot_2, slot_3, slot_4, slot_5)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (user_id, preset_name) DO UPDATE SET
                    slot_1=EXCLUDED.slot_1, slot_2=EXCLUDED.slot_2,
                    slot_3=EXCLUDED.slot_3, slot_4=EXCLUDED.slot_4, 
                    slot_5=EXCLUDED.slot_5
            """, str(ctx.author.id), name.lower(), current['slot_1'], current['slot_2'], current['slot_3'], current['slot_4'], current['slot_5'])
            
            await ctx.reply(f"✅ Active team saved as preset: **{name}**")

    @commands.command(name="load_team", aliases=['equip_team'])
    async def load_team_preset(self, ctx, name: str):
        """Swaps your active team to the saved preset."""
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            # 1. Find the preset
            preset = await conn.fetchrow("""
                SELECT slot_1, slot_2, slot_3, slot_4, slot_5 
                FROM team_presets 
                WHERE user_id = $1 AND preset_name = $2
            """, str(ctx.author.id), name.lower())
            
            if not preset:
                return await ctx.reply(f"❌ No preset found named '{name}'.")

            # 2. Overwrite the active 'teams' table
            await conn.execute("""
                INSERT INTO teams (user_id, slot_1, slot_2, slot_3, slot_4, slot_5)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT(user_id) DO UPDATE SET
                    slot_1=EXCLUDED.slot_1, slot_2=EXCLUDED.slot_2,
                    slot_3=EXCLUDED.slot_3, slot_4=EXCLUDED.slot_4,
                    slot_5=EXCLUDED.slot_5
            """, str(ctx.author.id), preset['slot_1'], preset['slot_2'], preset['slot_3'], preset['slot_4'], preset['slot_5'])
            
            await ctx.reply(f"✅ Equipped preset **{name}**!")

    @commands.command(name="presets")
    async def list_presets(self, ctx):
        """View your saved presets with detailed unit names."""
        pool = await get_db_pool()
        rows = await pool.fetch("""
            SELECT preset_name, slot_1, slot_2, slot_3, slot_4, slot_5 
            FROM team_presets 
            WHERE user_id = $1 
            ORDER BY preset_name ASC
        """, str(ctx.author.id))
        
        if not rows:
            return await ctx.reply("You have no saved team presets.")

        class PresetView(View):
            def __init__(self, ctx, data, pool):
                super().__init__(timeout=60)
                self.ctx = ctx
                self.data = data
                self.pool = pool
                self.current_page = 0
                self.items_per_page = 5
                self.total_pages = (len(data) - 1) // self.items_per_page + 1
                self.update_buttons()

            def update_buttons(self):
                self.prev_btn.disabled = (self.current_page == 0)
                self.next_btn.disabled = (self.current_page >= self.total_pages - 1)
                self.count_btn.label = f"{self.current_page + 1}/{self.total_pages}"

            async def get_embed(self):
                start = self.current_page * self.items_per_page
                page_data = self.data[start:start + self.items_per_page]
                
                # 1. Collect all Unit IDs to fetch names in one go
                all_ids = set()
                for row in page_data:
                    for i in range(1, 6):
                        if row[f'slot_{i}']: all_ids.add(row[f'slot_{i}'])
                
                # 2. Fetch Names from DB
                name_map = {}
                if all_ids:
                    res = await self.pool.fetch("""
                        SELECT i.id, c.name 
                        FROM inventory i
                        JOIN characters_cache c ON i.anilist_id = c.anilist_id
                        WHERE i.id = ANY($1::int[])
                    """, list(all_ids))
                    name_map = {r['id']: r['name'] for r in res}

                # 3. Build Embed
                embed = discord.Embed(title="📁 Team Presets", color=0x00ff00)
                for row in page_data:
                    slots_display = []
                    for i in range(1, 6):
                        uid = row[f'slot_{i}']
                        if not uid:
                            slots_display.append("`--`")
                        else:
                            # Truncate name to keep it clean
                            name = name_map.get(uid, "Unknown")
                            if len(name) > 10: name = name[:9] + "…"
                            slots_display.append(f"`{name}`")

                    embed.add_field(
                        name=f"🔹 {row['preset_name'].title()}", 
                        value=" | ".join(slots_display), 
                        inline=False
                    )
                embed.set_footer(text=f"Total Presets: {len(self.data)}")
                return embed

            @discord.ui.button(label="◀️", style=discord.ButtonStyle.primary)
            async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user != self.ctx.author: return
                self.current_page -= 1
                self.update_buttons()
                await interaction.response.edit_message(embed=await self.get_embed(), view=self)

            @discord.ui.button(label="Page 1/1", style=discord.ButtonStyle.secondary, disabled=True)
            async def count_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
                pass

            @discord.ui.button(label="▶️", style=discord.ButtonStyle.primary)
            async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user != self.ctx.author: return
                self.current_page += 1
                self.update_buttons()
                await interaction.response.edit_message(embed=await self.get_embed(), view=self)

        view = PresetView(ctx, rows, pool)
        await ctx.reply(embed=await view.get_embed(), view=view)

async def setup(bot):
    await bot.add_cog(RPG(bot))