import discord
from discord.ext import commands, tasks
from discord.ui import View, Select, Button
import json
import random
import datetime
import io
import asyncio
import traceback
from core.database import get_db_pool
from core.game_math import calculate_bond_exp_required
from core.emotes import Emotes
from core.skills import create_skill_instance, BattleContext
from core.image_gen import generate_team_image

# --- UI VIEWS ---

class HuntView(View):
    def __init__(self, bot, user_id, bounty_data, user_status_map):
        super().__init__(timeout=180)
        self.bot = bot
        self.user_id = user_id
        self.bounty_data = bounty_data
        self.status_map = user_status_map
        self.selected_slot = None

        # 1. Dropdown: Select Target
        options = []
        for slot, data in bounty_data.items():
            status = user_status_map.get(slot, "AVAILABLE")
            
            if status == "AVAILABLE":
                label = f"Slot {slot}: {data['tier']} Tier"
                desc = "Select to lock target"
                emoji = "🟥" 
            else:
                label = f"Slot {slot}: {data['tier']} ({status})"
                desc = "Already attempted"
                emoji = "✅" if status == "COMPLETED" else "❌"

            # Only allow selecting Available ones for the hunt interaction
            if status == "AVAILABLE":
                options.append(discord.SelectOption(
                    label=label,
                    value=str(slot),
                    description=desc,
                    emoji=emoji
                ))

        if not options:
            options.append(discord.SelectOption(label="No Targets Available", value="none", description="Wait for reset or check back later."))

        self.select = Select(
            placeholder="🔍 Select a Bounty Target...",
            min_values=1, 
            max_values=1, 
            options=options,
            row=0,
            disabled=(len(options) == 1 and options[0].value == "none")
        )
        self.select.callback = self.select_callback
        self.add_item(self.select)

        # 2. Button: Fight (Initially Disabled)
        self.fight_btn = Button(
            label="⚔️ FIGHT", 
            style=discord.ButtonStyle.danger, 
            disabled=True, 
            row=1
        )
        self.fight_btn.callback = self.fight_callback
        self.add_item(self.fight_btn)

    async def interaction_check(self, interaction: discord.Interaction):
        if str(interaction.user.id) != str(self.user_id):
            await interaction.response.send_message("❌ This is not your hunt.", ephemeral=True)
            return False
        return True

    async def select_callback(self, interaction: discord.Interaction):
        val = self.select.values[0]
        if val == "none":
            return await interaction.response.send_message("No valid target available.", ephemeral=True)
            
        self.selected_slot = int(val)
        data = self.bounty_data[self.selected_slot]
        team = json.loads(data['enemy_data'])
        total_power = sum(u['true_power'] for u in team)
        
        # Update Embed to show "Target Locked" state
        embed = interaction.message.embeds[0]
        embed.color = 0xE74C3C # Red for danger
        embed.clear_fields()
        
        embed.add_field(name="🎯 Target Locked", value=f"**Slot {self.selected_slot} ({data['tier']})**", inline=True)
        embed.add_field(name="⚠️ Enemy Power", value=f"**{total_power:,}**", inline=True)
        
        roster = "\n".join([f"• {u['name']} (Pow: {u['true_power']:,})" for u in team])
        embed.add_field(name="Enemy Team Intelligence", value=roster, inline=False)
        
        embed.set_footer(text="Press FIGHT to consume 1 Key and start battle.")

        # Enable Fight Button
        self.fight_btn.disabled = False
        await interaction.response.edit_message(embed=embed, view=self)

    async def fight_callback(self, interaction: discord.Interaction):
        if not self.selected_slot: return

        # Lock UI immediately
        self.select.disabled = True
        self.fight_btn.disabled = True
        self.fight_btn.label = "⏳ BATTLE IN PROGRESS..."
        self.fight_btn.style = discord.ButtonStyle.secondary
        await interaction.response.edit_message(view=self)
        
        # Handover to Cog for processing
        cog = self.bot.get_cog("Bounty")
        if cog:
            await cog.process_hunt(interaction, self.selected_slot, self.bounty_data[self.selected_slot])
        else:
            await interaction.followup.send("❌ Error: Bounty system not found.", ephemeral=True)


# --- MAIN COG ---

class Bounty(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bounty_refresh_loop.start()

    def cog_unload(self):
        self.bounty_refresh_loop.cancel()

    # --- HELPERS ---

    async def regenerate_keys(self, user_id):
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            user = await conn.fetchrow("SELECT bounty_keys, last_key_regen FROM users WHERE user_id = $1", str(user_id))
            if not user: return 0
            
            current_keys = user['bounty_keys']
            if current_keys >= 3: return current_keys
            
            now = datetime.datetime.now(datetime.timezone.utc)
            last_regen = user['last_key_regen']
            if last_regen and last_regen.tzinfo is None:
                last_regen = last_regen.replace(tzinfo=datetime.timezone.utc)
            elif not last_regen:
                last_regen = now

            diff = now - last_regen
            hours_passed = int(diff.total_seconds() // 3600)
            
            if hours_passed > 0:
                new_keys = min(3, current_keys + hours_passed)
                # Keep minute offset
                new_last_regen = last_regen + datetime.timedelta(hours=hours_passed)
                await conn.execute("UPDATE users SET bounty_keys = $1, last_key_regen = $2 WHERE user_id = $3", 
                                   new_keys, new_last_regen, str(user_id))
                return new_keys
            return current_keys

    async def get_dashboard_embed_and_view(self, user_id):
        """Helper to reconstruct the dashboard state."""
        keys = await self.regenerate_keys(user_id)
        pool = await get_db_pool()
        
        rows = await pool.fetch("SELECT * FROM bounty_board ORDER BY slot_id ASC")
        if not rows: return None, None
        
        bounty_data = {r['slot_id']: r for r in rows}
        status_rows = await pool.fetch("SELECT slot_id, status FROM user_bounty_status WHERE user_id = $1", str(user_id))
        status_map = {r['slot_id']: r['status'] for r in status_rows}
        
        embed = discord.Embed(title="⚔️ Bounty Hunt Dashboard", description=f"**Keys Available:** {keys}/3 🔑", color=0x3498db)
        embed.set_footer(text="Select a target from the dropdown to begin.")
        
        view = HuntView(self.bot, user_id, bounty_data, status_map)
        return embed, view

    # --- TASKS ---

    @tasks.loop(hours=3)
    async def bounty_refresh_loop(self):
        pool = await get_db_pool()
        expires_at = datetime.datetime.now() + datetime.timedelta(hours=3)
        
        # Configuration: (Slot, Tier, MinPower, MaxPower)
        configs = [
            (1, "R", 30000, 35000),
            (2, "SR", 50000, 55000),
            (3, "SSR", 70000, 75000)
        ]

        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM bounty_board")
            await conn.execute("DELETE FROM user_bounty_status")
            
            for slot, tier, min_p, max_p in configs:
                is_ur = random.random() < 0.01
                final_tier = "UR" if is_ur else tier
                total_power = 90000 if is_ur else random.randint(min_p, max_p)
                
                # Mock Team Generation
                member_power = total_power // 5
                team_data = []
                for i in range(5):
                    team_data.append({
                        'name': f"{final_tier} Enemy",
                        'true_power': member_power,
                        'rarity': final_tier,
                        'ability_tags': [], 
                        'anilist_id': 0, # Placeholder for safety
                        'image_url': None
                    })
                
                await conn.execute("""
                    INSERT INTO bounty_board (slot_id, enemy_data, tier, expires_at)
                    VALUES ($1, $2, $3, $4)
                """, slot, json.dumps(team_data), final_tier, expires_at)

    # --- COMMANDS ---

    @commands.command(name="bounty")
    async def bounty_info(self, ctx):
        """Displays the Bounty Board status (Information Only)."""
        keys = await self.regenerate_keys(ctx.author.id)
        pool = await get_db_pool()
        
        rows = await pool.fetch("SELECT * FROM bounty_board ORDER BY slot_id ASC")
        if not rows: return await ctx.reply("⚠️ Bounty Board is currently refreshing...")
        
        status_rows = await pool.fetch("SELECT slot_id, status FROM user_bounty_status WHERE user_id = $1", str(ctx.author.id))
        status_map = {r['slot_id']: r['status'] for r in status_rows}
        
        expires = rows[0]['expires_at']
        if expires.tzinfo is None: expires = expires.replace(tzinfo=datetime.timezone.utc)
        ts = int(expires.timestamp())

        embed = discord.Embed(title="📜 Bounty Board Requests", color=0x8B4513)
        embed.description = f"**Keys:** {keys}/3 🔑\n**Resets:** <t:{ts}:R>"
        
        for row in rows:
            slot = row['slot_id']
            tier = row['tier']
            status = status_map.get(slot, "AVAILABLE")
            
            if status == "COMPLETED": icon = "✅ Completed"
            elif status == "FAILED": icon = "❌ Failed"
            else: icon = "⚔️ Available"
            
            if tier == "UR": rewards = "**UR Bond**, 50 Coins, 5k Gems"
            else: rewards = {1: "Small Bond", 2: "Med Bond", 3: "Large Bond"}.get(slot, "Gift")
            
            enemy_team = json.loads(row['enemy_data'])
            power = sum(u['true_power'] for u in enemy_team)
            
            embed.add_field(
                name=f"Slot {slot}: {tier} Tier",
                value=f"**Status:** {icon}\n**Power:** {power:,}\n**Reward:** {rewards}",
                inline=False
            )
            
        embed.set_footer(text="Use !hunt to start a battle!")
        await ctx.reply(embed=embed)

    @commands.command(name="hunt")
    async def hunt_command(self, ctx):
        """Interactive menu to select and fight a bounty."""
        keys = await self.regenerate_keys(ctx.author.id)
        if keys < 1:
            return await ctx.reply(f"❌ You have 0 keys! Next key regenerates soon.")
            
        embed, view = await self.get_dashboard_embed_and_view(ctx.author.id)
        if not embed:
            return await ctx.reply("⚠️ Board refreshing...")
            
        await ctx.reply(embed=embed, view=view)

    # --- LOGIC HANDLER ---

    async def process_hunt(self, interaction, slot_id, bounty_row):
        """Handles the actual fight logic."""
        user_id = str(interaction.user.id)
        pool = await get_db_pool()
        
        try:
            # 1. Validation
            keys = await self.regenerate_keys(user_id)
            if keys < 1:
                return await interaction.followup.send("❌ No keys left! Did you use one elsewhere?", ephemeral=True)
            
            battle_cog = self.bot.get_cog("Battle")
            if not battle_cog: 
                return await interaction.followup.send("❌ Battle System Error: Cog not loaded.", ephemeral=True)
            
            attacker_team = await battle_cog.get_team_for_battle(int(user_id))
            if not attacker_team: 
                return await interaction.followup.send("❌ You need a team! Use `!team` to set one up.", ephemeral=True)
            
            defender_team = json.loads(bounty_row['enemy_data'])
            
            # 2. Consume Key
            await pool.execute("UPDATE users SET bounty_keys = bounty_keys - 1 WHERE user_id = $1", user_id)
            
            # 3. Run Battle
            ctx = BattleContext(attacker_team, defender_team)

            # -- Initialize Skills --
            all_skills = []
            for side, team in [("attacker", attacker_team), ("defender", defender_team)]:
                for i, char in enumerate(team):
                    if not char: continue
                    tags = char.get('ability_tags', [])
                    if isinstance(tags, str): tags = json.loads(tags)
                    for tag in tags:
                        s = create_skill_instance(tag, char, i, side)
                        if s: all_skills.append(s)

            # -- Start Phase --
            for s in all_skills: await s.on_battle_start(ctx)
            
            # -- Power Calculation --
            final_powers = {"attacker": [], "defender": []}
            for side in ["attacker", "defender"]:
                team = ctx.get_team(side)
                for i, char in enumerate(team):
                    if not char:
                        final_powers[side].append(0)
                        continue
                    
                    power = char['true_power']
                    # Apply Skill Modifiers
                    for s in all_skills:
                        if s.side == side and s.idx == i:
                            mod = await s.get_power_modifier(ctx, power)
                            power *= mod
                    
                    # Apply Multipliers (Context)
                    power *= ctx.multipliers[side][i]
                    power += ctx.flat_bonuses[side][i]
                    
                    # Apply Variance
                    # Check for override (Dragon Zodiac)
                    variance_val = ctx.flags.get("variance_override", {}).get(f"{side}_{i}", None)
                    if variance_val is None:
                        variance_val = random.uniform(0.9, 1.1)
                    
                    final_powers[side].append(max(0, int(power * variance_val)))
            
            # -- Post Calc (Zodiac swaps/copies) --
            for s in all_skills:
                await s.on_post_power_calculation(ctx, final_powers)

            # -- Outcome --
            total_att = sum(final_powers["attacker"])
            total_def = sum(final_powers["defender"])
            
            initial_win = total_att > total_def
            outcome = "WIN" if initial_win else "LOSS"
            
            # Special Check (Snake Zodiac / Revive)
            if not initial_win and ctx.flags.get("snake_trap"):
                outcome = "DRAW"
                ctx.misc_logs["defender"].append("🐍 **Snake Zodiac** forced a DRAW!")

            if outcome == "LOSS":
                 for s in all_skills:
                     if s.side == "attacker":
                         # Check on_battle_end modifiers (Revive)
                         new_res = await s.on_battle_end(ctx, outcome)
                         if new_res: 
                             outcome = new_res
                             break

            # -- Status Update --
            final_status = "COMPLETED" if outcome == "WIN" else "FAILED"
            if outcome == "DRAW": final_status = "FAILED" # Treat draw as fail for bounty purposes? Or allow retry? 
            # Usually Bounties require a WIN.
            
            await pool.execute("""
                INSERT INTO user_bounty_status (user_id, slot_id, status) VALUES ($1, $2, $3)
                ON CONFLICT (user_id, slot_id) DO UPDATE SET status = $3
            """, user_id, slot_id, final_status)
            
            # 4. Rewards
            loot_text = "None"
            if outcome == "WIN":
                tier = bounty_row['tier']
                if tier == "UR":
                    await pool.execute("UPDATE users SET coins = coins + 50, gacha_gems = gacha_gems + 5000 WHERE user_id = $1", user_id)
                    await pool.execute("INSERT INTO user_items (user_id, item_id, quantity) VALUES ($1, 'bond_ur', 1) ON CONFLICT (user_id, item_id) DO UPDATE SET quantity = user_items.quantity + 1", user_id)
                    loot_text = f"**UR Bond** {Emotes.UR_BOND}, 50 Coins, 5000 Gems"
                else:
                    item_map = {1: "bond_small", 2: "bond_med", 3: "bond_large"}
                    item_id = item_map.get(slot_id, "bond_small")
                    display_name = item_id.replace('_', ' ').title()
                    loot_text = f"1x {display_name}"
                    
                    await pool.execute(f"INSERT INTO user_items (user_id, item_id, quantity) VALUES ($1, $2, 1) ON CONFLICT (user_id, item_id) DO UPDATE SET quantity = user_items.quantity + 1", user_id, item_id)

            # 5. Collect Logs (THE FIX)
            # We aggregate logs from the Context, avoiding manual object access
            combined_logs = []
            
            # Add Global/Misc Logs first
            if ctx.misc_logs['attacker']: combined_logs.extend(ctx.misc_logs['attacker'])
            if ctx.misc_logs['defender']: combined_logs.extend(ctx.misc_logs['defender'])
            
            # Add Slot-specific logs
            for side in ['attacker', 'defender']:
                for slot_idx in sorted(ctx.logs[side].keys()):
                    for msg in ctx.logs[side][slot_idx]:
                        combined_logs.append(msg)

            # 6. Generate Result UI
            color = 0x2ECC71 if outcome == "WIN" else 0xE74C3C
            if outcome == "DRAW": color = 0xF1C40F

            result_embed = discord.Embed(
                title=f"BATTLE RESULT: {outcome}",
                color=color
            )
            result_embed.add_field(name="Your Power", value=f"{total_att:,}", inline=True)
            result_embed.add_field(name="Enemy Power", value=f"{total_def:,}", inline=True)
            result_embed.add_field(name="Loot", value=loot_text, inline=False)
            
            if combined_logs:
                # Deduplicate and limit length
                unique_logs = list(dict.fromkeys(combined_logs))
                log_str = "\n".join(unique_logs)
                if len(log_str) > 1000: log_str = log_str[:995] + "..."
                result_embed.add_field(name="Battle Log", value=log_str, inline=False)
            else:
                 result_embed.add_field(name="Battle Log", value="*No significant events.*", inline=False)

            file = None
            if outcome == "WIN":
                # Attempt Image Generation
                try:
                    img_bytes = await generate_team_image(attacker_team)
                    file = discord.File(io.BytesIO(img_bytes), filename="victory.png")
                    result_embed.set_image(url="attachment://victory.png")
                except Exception as img_err:
                    print(f"Image Gen Error: {img_err}")

            # Send the Result (New Message)
            await interaction.followup.send(embed=result_embed, file=file)

            # 7. Update Original Dashboard (Lock the Slot)
            new_embed, new_view = await self.get_dashboard_embed_and_view(user_id)
            if new_embed:
                await interaction.edit_original_response(embed=new_embed, view=new_view)
        
        except Exception as e:
            traceback.print_exc()
            await interaction.followup.send(f"❌ An error occurred during the battle: {e}", ephemeral=True)

    @commands.command(name="gift")
    async def gift_bond(self, ctx, char_id: int, item_alias: str):
        """Usage: !gift <id> <small/med/large/ur>"""
        aliases = {
            "small": ("bond_small", 10), "s": ("bond_small", 10),
            "med": ("bond_med", 50), "m": ("bond_med", 50),
            "large": ("bond_large", 250), "l": ("bond_large", 250),
            "ur": ("bond_ur", 2500)
        }
        
        selection = aliases.get(item_alias.lower())
        if not selection:
            return await ctx.reply("❌ Invalid item. Options: small, med, large, ur.")
            
        item_id, exp_gain = selection
        pool = await get_db_pool()
        
        # Check Item
        inv_item = await pool.fetchrow("SELECT quantity FROM user_items WHERE user_id=$1 AND item_id=$2", str(ctx.author.id), item_id)
        if not inv_item or inv_item['quantity'] < 1:
            return await ctx.reply(f"❌ You do not own any **{item_id}** items.")
            
        # Check Character
        char = await pool.fetchrow("SELECT bond_level, bond_exp FROM inventory WHERE id=$1 AND user_id=$2", char_id, str(ctx.author.id))
        if not char: return await ctx.reply("❌ Character not found.")
        if char['bond_level'] >= 50: return await ctx.reply("❌ Character is already at Max Bond (Lv. 50)!")
        
        # Apply EXP
        cur_lvl, cur_exp = char['bond_level'], char['bond_exp']
        cur_exp += exp_gain
        leveled = False
        
        while cur_lvl < 50:
            req = calculate_bond_exp_required(cur_lvl)
            if cur_exp >= req:
                cur_exp -= req
                cur_lvl += 1
                leveled = True
            else:
                break
        
        async with pool.acquire() as conn:
            await conn.execute("UPDATE user_items SET quantity = quantity - 1 WHERE user_id=$1 AND item_id=$2", str(ctx.author.id), item_id)
            await conn.execute("UPDATE inventory SET bond_level=$1, bond_exp=$2 WHERE id=$3", cur_lvl, cur_exp, char_id)
            
        msg = f"🎁 Used **{item_alias.upper()}**! (+{exp_gain} Bond EXP)"
        if leveled:
            mult = 1 + (cur_lvl * 0.005)
            msg += f"\n🆙 **BOND LEVEL UP!** Lv. {cur_lvl} (Power x{mult:.3f})"
        
        await ctx.reply(msg)

async def setup(bot):
    await bot.add_cog(Bounty(bot))