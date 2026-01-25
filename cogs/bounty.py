import discord
from discord.ext import commands, tasks
from discord.ui import View, Select
import json
import random
import datetime
import io
import asyncio
from core.database import get_db_pool
from core.game_math import calculate_bond_exp_required
from core.emotes import Emotes
from core.skills import create_skill_instance, BattleContext
from core.image_gen import generate_team_image

class BountyView(View):
    def __init__(self, bot, user_id, bounty_data, user_status_map):
        super().__init__(timeout=180)
        self.bot = bot
        self.user_id = user_id
        self.bounty_data = bounty_data
        self.status_map = user_status_map
        
        # --- INSPECT DROPDOWN ---
        inspect_options = []
        for s, d in bounty_data.items():
            enemy_team = json.loads(d['enemy_data'])
            total_p = sum(u['true_power'] for u in enemy_team)
            inspect_options.append(discord.SelectOption(
                label=f"Inspect Slot {s}: {d['tier']} Tier",
                value=str(s),
                description=f"Power: {total_p:,} | Reward: {self.get_reward_name(s, d['tier'])}"
            ))
            
        self.inspect_select = Select(placeholder="🔍 Inspect Bounty Details", options=inspect_options, custom_id="inspect_sel", row=0)
        self.inspect_select.callback = self.inspect_callback
        self.add_item(self.inspect_select)

        # --- HUNT DROPDOWN ---
        hunt_options = []
        for s, d in bounty_data.items():
            status = user_status_map.get(s, "AVAILABLE")
            emoji = "✅" if status == "COMPLETED" else "❌" if status == "FAILED" else "⚔️"
            
            # Disable if done
            desc = "Ready to fight! (-1 Key)"
            if status != "AVAILABLE": desc = f"Status: {status}"
            
            hunt_options.append(discord.SelectOption(
                label=f"Hunt Slot {s} ({d['tier']})",
                value=str(s),
                emoji=emoji,
                description=desc
            ))

        self.hunt_select = Select(placeholder="⚔️ Select Target to Fight", options=hunt_options, custom_id="hunt_sel", row=1)
        self.hunt_select.callback = self.hunt_callback
        self.add_item(self.hunt_select)

    def get_reward_name(self, slot, tier):
        if tier == "UR": return "UR Bond + Gems"
        return {1: "Small Bond", 2: "Med Bond", 3: "Large Bond"}.get(slot, "Gift")

    async def interaction_check(self, interaction: discord.Interaction):
        if str(interaction.user.id) != str(self.user_id):
            await interaction.response.send_message("❌ This is not your menu.", ephemeral=True)
            return False
        return True

    async def inspect_callback(self, interaction: discord.Interaction):
        slot = int(self.inspect_select.values[0])
        data = self.bounty_data[slot]
        team = json.loads(data['enemy_data'])
        
        embed = discord.Embed(title=f"🕵️ Intel: {data['tier']} Bounty (Slot {slot})", color=0x3498db)
        embed.add_field(name="Total Power", value=f"{sum(u['true_power'] for u in team):,}")
        embed.add_field(name="Reward", value=self.get_reward_name(slot, data['tier']))
        
        roster = "\n".join([f"• **{u['name']}** (Pow: {u['true_power']:,})" for u in team])
        embed.add_field(name="Enemy Team", value=roster, inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def hunt_callback(self, interaction: discord.Interaction):
        slot = int(self.hunt_select.values[0])
        if self.status_map.get(slot) in ["COMPLETED", "FAILED"]:
            return await interaction.response.send_message("❌ You have already challenged this bounty.", ephemeral=True)
            
        # Hand off to Cog logic
        cog = self.bot.get_cog("Bounty")
        await cog.process_hunt(interaction, slot, self.bounty_data[slot])

class Bounty(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bounty_refresh_loop.start()

    def cog_unload(self):
        self.bounty_refresh_loop.cancel()

    @tasks.loop(hours=3)
    async def bounty_refresh_loop(self):
        pool = await get_db_pool()
        expires = datetime.datetime.now() + datetime.timedelta(hours=3)
        
        configs = [(1, "R", 30000, 35000), (2, "SR", 50000, 55000), (3, "SSR", 70000, 75000)]
        
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM bounty_board")
            await conn.execute("DELETE FROM user_bounty_status")
            
            for slot, tier, min_p, max_p in configs:
                is_ur = random.random() < 0.01
                final_tier = "UR" if is_ur else tier
                target_power = 90000 if is_ur else random.randint(min_p, max_p)
                
                # Mock Team Generation
                team = []
                for i in range(5):
                    team.append({
                        'name': f"{final_tier} Bandit {i+1}",
                        'true_power': target_power // 5,
                        'rarity': final_tier,
                        'ability_tags': [],
                        'image_url': None
                    })
                
                await conn.execute("INSERT INTO bounty_board (slot_id, enemy_data, tier, expires_at) VALUES ($1, $2, $3, $4)",
                                   slot, json.dumps(team), final_tier, expires)

    async def regenerate_keys(self, user_id):
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            user = await conn.fetchrow("SELECT bounty_keys, last_key_regen FROM users WHERE user_id = $1", str(user_id))
            if not user: return 0
            
            if user['bounty_keys'] >= 3: return user['bounty_keys']
            
            now = datetime.datetime.now(datetime.timezone.utc)
            # Ensure last_key_regen is aware
            last = user['last_key_regen'] or now
            if last.tzinfo is None: last = last.replace(tzinfo=datetime.timezone.utc)
                
            diff = now - last
            hours = int(diff.total_seconds() // 3600)
            
            if hours > 0:
                new_keys = min(3, user['bounty_keys'] + hours)
                new_last = last + datetime.timedelta(hours=hours)
                await conn.execute("UPDATE users SET bounty_keys = $1, last_key_regen = $2 WHERE user_id = $3", 
                                   new_keys, new_last, str(user_id))
                return new_keys
            return user['bounty_keys']

    @commands.command(name="bounty")
    async def bounty_menu(self, ctx):
        keys = await self.regenerate_keys(ctx.author.id)
        pool = await get_db_pool()
        
        rows = await pool.fetch("SELECT * FROM bounty_board ORDER BY slot_id ASC")
        if not rows: return await ctx.reply("⚠️ Board is refreshing...")
        
        bounty_data = {r['slot_id']: r for r in rows}
        status_rows = await pool.fetch("SELECT slot_id, status FROM user_bounty_status WHERE user_id = $1", str(ctx.author.id))
        status_map = {r['slot_id']: r['status'] for r in status_rows}
        
        embed = discord.Embed(title="📜 Bounty Board", color=0x8B4513)
        embed.description = f"**Keys Available:** {keys}/3 🔑\nResets every 3 hours."
        embed.set_thumbnail(url="https://i.imgur.com/bounty_board_icon.png") # Optional placeholder
        
        view = BountyView(self.bot, ctx.author.id, bounty_data, status_map)
        await ctx.reply(embed=embed, view=view)

    async def process_hunt(self, interaction, slot_id, bounty_row):
        user_id = str(interaction.user.id)
        pool = await get_db_pool()
        
        # 1. Key Check
        keys = await self.regenerate_keys(user_id)
        if keys < 1:
            return await interaction.response.send_message("❌ No keys remaining!", ephemeral=True)
            
        await interaction.response.defer()
        
        # 2. Get Teams
        battle_cog = self.bot.get_cog("Battle")
        attacker_team = await battle_cog.get_team_for_battle(int(user_id))
        if not attacker_team:
            return await interaction.followup.send("❌ You don't have a team equipped! Use `!team`.")
            
        defender_team = json.loads(bounty_row['enemy_data'])
        
        # 3. Consume Key
        await pool.execute("UPDATE users SET bounty_keys = bounty_keys - 1 WHERE user_id = $1", user_id)
        
        # 4. Battle Logic
        ctx = BattleContext(attacker_team, defender_team)
        logs = []
        
        # Setup Skills
        all_skills = []
        for side, team in [("attacker", attacker_team), ("defender", defender_team)]:
            for i, char in enumerate(team):
                if not char: continue
                tags = char.get('ability_tags', [])
                if isinstance(tags, str): tags = json.loads(tags)
                for tag in tags:
                    s_inst = create_skill_instance(tag, char, i, side)
                    if s_inst: all_skills.append(s_inst)

        # Start Phase
        for s in all_skills: await s.on_battle_start(ctx)
        
        # Calc Phase (Simplified for brevity)
        final_p = {"attacker": [], "defender": []}
        for side in ["attacker", "defender"]:
            team = ctx.get_team(side)
            for i, char in enumerate(team):
                if not char:
                    final_p[side].append(0)
                    continue
                
                base = char['true_power']
                # Skill Mods
                for s in all_skills:
                    if s.side == side and s.idx == i:
                        mod = await s.get_power_modifier(ctx, base)
                        if mod != 1.0:
                            # Log significant mods?
                            pass
                        base *= mod
                
                # Apply Variance
                variance = random.uniform(0.9, 1.1)
                final = int(base * variance)
                final_p[side].append(final)
        
        # Post-Calc Phase & Logging
        for s in all_skills:
            # We can capture logs here if skills had a 'log' property or returned strings
            # For now, we simulate logs based on tags present
            if s.side == "attacker" and random.random() < 0.3: # Simulate proc chance visibility
                logs.append(f"🔵 **{s.char['name']}** activated **{s.tag}**!")

        total_a = sum(final_p['attacker'])
        total_d = sum(final_p['defender'])
        win = total_a > total_d
        
        outcome = "COMPLETED" if win else "FAILED"
        
        # 5. DB Update
        await pool.execute("""
            INSERT INTO user_bounty_status (user_id, slot_id, status) VALUES ($1, $2, $3)
            ON CONFLICT (user_id, slot_id) DO UPDATE SET status = $3
        """, user_id, slot_id, outcome)

        # 6. Rewards & Visuals
        embed = discord.Embed(
            title="🏆 Victory!" if win else "💀 Defeat",
            description=f"**Your Power:** {total_a:,}\n**Enemy Power:** {total_d:,}",
            color=0x00FF00 if win else 0xFF0000
        )
        
        if logs: embed.add_field(name="Battle Log", value="\n".join(logs), inline=False)
        else: embed.add_field(name="Battle Log", value="*No skills activated visible effects.*", inline=False)
        
        file = None
        if win:
            tier = bounty_row['tier']
            # Distribute Loot
            rewards_txt = ""
            if tier == "UR":
                await pool.execute("UPDATE users SET coins = coins + 50, gacha_gems = gacha_gems + 5000 WHERE user_id = $1", user_id)
                await pool.execute("INSERT INTO user_items (user_id, item_id, quantity) VALUES ($1, 'bond_ur', 1) ON CONFLICT (user_id, item_id) DO UPDATE SET quantity = user_items.quantity + 1", user_id)
                rewards_txt = "50 Coins, 5000 Gems, UR Bond"
            else:
                item_map = {1: "bond_small", 2: "bond_med", 3: "bond_large"}
                item_id = item_map.get(slot_id, "bond_small")
                await pool.execute(f"INSERT INTO user_items (user_id, item_id, quantity) VALUES ($1, $2, 1) ON CONFLICT (user_id, item_id) DO UPDATE SET quantity = user_items.quantity + 1", user_id, item_id)
                rewards_txt = f"1x {item_id.replace('_', ' ').title()}"
            
            embed.add_field(name="Loot Obtained", value=rewards_txt, inline=False)
            
            # Generate Victory Image (User Team)
            img_bytes = await generate_team_image(attacker_team)
            file = discord.File(io.BytesIO(img_bytes), filename="victory_team.png")
            embed.set_image(url="attachment://victory_team.png")

        if file:
            await interaction.followup.send(embed=embed, file=file)
        else:
            await interaction.followup.send(embed=embed)

    @commands.command(name="gift")
    async def gift_bond(self, ctx, char_id: int, item_alias: str):
        """Usage: !gift <id> <small/med/large/ur>"""
        aliases = {
            "small": ("bond_small", 10), "s": ("bond_small", 10),
            "med": ("bond_med", 50), "m": ("bond_med", 50),
            "large": ("bond_large", 250), "l": ("bond_large", 250),
            "ur": ("bond_ur", 2500)
        }
        
        if item_alias.lower() not in aliases:
            return await ctx.reply("❌ Invalid item. Use: small, med, large, ur.")
            
        item_id, exp_gain = aliases[item_alias.lower()]
        pool = await get_db_pool()
        
        # Check Item
        inv_item = await pool.fetchrow("SELECT quantity FROM user_items WHERE user_id=$1 AND item_id=$2", str(ctx.author.id), item_id)
        if not inv_item or inv_item['quantity'] < 1:
            return await ctx.reply(f"❌ You don't have any {item_id}!")
            
        # Check Char
        char = await pool.fetchrow("SELECT bond_level, bond_exp FROM inventory WHERE id=$1 AND user_id=$2", char_id, str(ctx.author.id))
        if not char: return await ctx.reply("❌ Character not found.")
        if char['bond_level'] >= 50: return await ctx.reply("❌ Max Bond Reached!")
        
        # Apply Logic
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
            
        msg = f"🎁 Applied **{item_alias.upper()}** (+{exp_gain} EXP)."
        if leveled: msg += f"\n🆙 **Level Up!** Bond Level {cur_lvl}!"
        await ctx.reply(msg)

async def setup(bot):
    await bot.add_cog(Bounty(bot))