import discord
from discord.ext import commands, tasks
import json
import random
import datetime
import asyncio
from core.database import get_db_pool
from core.game_math import calculate_effective_power, calculate_bond_exp_required
from core.emotes import Emotes
from core.skills import create_skill_instance, BattleContext
from core.image_gen import generate_battle_image
from cogs.battle import Battle # Importing to reuse helper if needed, though we implement logic here

class Bounty(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bounty_refresh_loop.start()

    def cog_unload(self):
        self.bounty_refresh_loop.cancel()

    async def regenerate_keys(self, user_id):
        """Checks and regenerates keys based on time passed."""
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            user = await conn.fetchrow("SELECT bounty_keys, last_key_regen FROM users WHERE user_id = $1", str(user_id))
            if not user: return 0

            current_keys = user['bounty_keys']
            last_regen = user['last_key_regen']
            now = datetime.datetime.now(datetime.timezone.utc)
            
            if current_keys >= 3:
                return current_keys

            # Calculate time passed
            diff = now - last_regen
            hours_passed = int(diff.total_seconds() // 3600)

            if hours_passed > 0:
                new_keys = min(3, current_keys + hours_passed)
                # Reset timer only if we added keys, but keep the "remainder" minutes by advancing last_regen by exact hours
                new_last_regen = last_regen + datetime.timedelta(hours=hours_passed)
                await conn.execute("UPDATE users SET bounty_keys = $1, last_key_regen = $2 WHERE user_id = $3", 
                                   new_keys, new_last_regen, str(user_id))
                return new_keys
            return current_keys

    @tasks.loop(hours=3)
    async def bounty_refresh_loop(self):
        """Rotates the bounty board every 3 hours."""
        pool = await get_db_pool()
        expires_at = datetime.datetime.now() + datetime.timedelta(hours=3)
        
        # Tiers setup
        configs = [
            (1, "R", 30000, 35000),    # Slot 1: R (30-35k)
            (2, "SR", 50000, 55000),   # Slot 2: SR (50-55k)
            (3, "SSR", 70000, 75000)   # Slot 3: SSR (70-75k)
        ]

        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM bounty_board")
            await conn.execute("DELETE FROM user_bounty_status") # Reset user progress
            
            for slot, tier, min_p, max_p in configs:
                # 1% Chance for UR Upgrade
                is_ur = random.random() < 0.01
                
                final_tier = "UR" if is_ur else tier
                target_power = 90000 if is_ur else random.randint(min_p, max_p)
                
                # Generate Mock Team (5 units with equal split power)
                unit_power = target_power // 5
                team_data = []
                for i in range(5):
                    team_data.append({
                        'name': f"Bounty {final_tier} Unit",
                        'true_power': unit_power,
                        'rarity': final_tier,
                        'ability_tags': [],
                        'image_url': None
                    })
                
                await conn.execute("""
                    INSERT INTO bounty_board (slot_id, enemy_data, tier, expires_at)
                    VALUES ($1, $2, $3, $4)
                """, slot, json.dumps(team_data), final_tier, expires_at)

    @commands.command(name="bounty")
    async def bounty(self, ctx):
        """Displays the current Bounty Board."""
        keys = await self.regenerate_keys(ctx.author.id)
        pool = await get_db_pool()
        
        board = await pool.fetch("SELECT * FROM bounty_board ORDER BY slot_id ASC")
        if not board:
            return await ctx.reply("⚠️ The Bounty Board is currently refreshing. Please wait a moment.")

        user_status = await pool.fetch("SELECT slot_id, status FROM user_bounty_status WHERE user_id = $1", str(ctx.author.id))
        status_map = {row['slot_id']: row['status'] for row in user_status}

        embed = discord.Embed(title="📜 Wanted: Bounty Board", color=0x8B4513)
        embed.description = f"**Keys Available:** {keys}/3 🔑\nRefreshes every 3 hours."
        
        rewards = {
            1: f"{Emotes.R_BOND} Small Gift",
            2: f"{Emotes.SR_BOND} Medium Gift",
            3: f"{Emotes.SSR_BOND} Large Gift"
        }

        for row in board:
            slot = row['slot_id']
            tier = row['tier']
            status = status_map.get(slot, "AVAILABLE")
            
            # Status Icons
            if status == "COMPLETED": stat_icon = "✅ **COMPLETED**"
            elif status == "FAILED": stat_icon = "❌ **FAILED**"
            else: stat_icon = "⚔️ **AVAILABLE**"
            
            # UR Check
            reward_text = rewards.get(slot, "Unknown")
            if tier == "UR":
                reward_text = f"{Emotes.UR_BOND} **UR Bond** + 50 Coins + 5k Gems!"
                tier_display = f"🚨 **UR BOSS** 🚨"
            else:
                tier_display = f"**Tier {tier}**"

            embed.add_field(
                name=f"Slot {slot}: {tier_display}", 
                value=f"{stat_icon}\nReward: {reward_text}", 
                inline=False
            )
            
        embed.set_footer(text="Use !hunt <slot_id> to fight!")
        await ctx.reply(embed=embed)

    @commands.command(name="hunt")
    async def hunt(self, ctx, slot_id: int):
        """Challenge a bounty target."""
        # 1. Validation & Key Check
        current_keys = await self.regenerate_keys(ctx.author.id)
        if current_keys < 1:
            return await ctx.reply("❌ You have no keys left! Wait for regeneration (1/hr).")
            
        pool = await get_db_pool()
        bounty = await pool.fetchrow("SELECT * FROM bounty_board WHERE slot_id = $1", slot_id)
        
        if not bounty:
            return await ctx.reply("❌ Invalid slot ID.")

        status_row = await pool.fetchrow("SELECT status FROM user_bounty_status WHERE user_id = $1 AND slot_id = $2", str(ctx.author.id), slot_id)
        if status_row and status_row['status'] in ['COMPLETED', 'FAILED']:
             return await ctx.reply(f"❌ You have already {status_row['status'].lower()} this bounty for this rotation.")

        # 2. Fetch Teams
        battle_cog = self.bot.get_cog("Battle")
        if not battle_cog: return await ctx.reply("❌ Battle system offline.")
        
        attacker_team = await battle_cog.get_team_for_battle(ctx.author.id)
        if not attacker_team: return await ctx.reply("❌ You need a team! Use `!team`.")
        
        defender_team = json.loads(bounty['enemy_data'])
        
        # 3. Consume Key
        await pool.execute("UPDATE users SET bounty_keys = bounty_keys - 1 WHERE user_id = $1", str(ctx.author.id))

        loading_msg = await ctx.reply(f"⚔️ **Hunting Bounty {bounty['tier']}...**")

        # 4. Run Battle Engine (Replicated from Battle.py logic)
        battle_ctx = BattleContext(attacker_team, defender_team)
        all_skills = []

        def load_skills(team, side):
            for i, char in enumerate(team):
                if not char: continue
                tags = char.get('ability_tags', [])
                if isinstance(tags, str): tags = json.loads(tags)
                for tag in tags:
                    skill = create_skill_instance(tag, char, i, side)
                    if skill: all_skills.append(skill)

        load_skills(attacker_team, "attacker")
        load_skills(defender_team, "defender")

        # Phase 1: Start
        for skill in all_skills: await skill.on_battle_start(battle_ctx)

        # Phase 2 & 3: Calculation
        final_powers = {"attacker": [], "defender": []}
        for side in ["attacker", "defender"]:
            team = battle_ctx.get_team(side)
            for i, char in enumerate(team):
                if not char: 
                    final_powers[side].append(0)
                    continue
                p = char['true_power']
                my_skills = [s for s in all_skills if s.side == side and s.idx == i]
                for s in my_skills:
                    mod = await s.get_power_modifier(battle_ctx, p)
                    p *= mod
                p *= battle_ctx.multipliers[side][i]
                p += battle_ctx.flat_bonuses[side][i]
                
                # Variance
                variance = battle_ctx.flags.get("variance_override", {}).get(f"{side}_{i}", random.uniform(0.9, 1.1))
                final_powers[side].append(max(0, p * variance))

        for skill in all_skills: await skill.on_post_power_calculation(battle_ctx, final_powers)

        # Phase 4: Outcome
        totals = {side: sum(final_powers[side]) for side in ["attacker", "defender"]}
        initial_win = totals["attacker"] > totals["defender"]
        outcome = "WIN" if initial_win else "LOSS"
        
        if not initial_win and battle_ctx.flags.get("snake_trap"): outcome = "DRAW"
        if outcome == "LOSS":
             for skill in all_skills:
                 if skill.side == "attacker":
                     new_res = await skill.on_battle_end(battle_ctx, outcome)
                     if new_res: 
                         outcome = new_res; break

        # 5. Handle Rewards & Status
        final_status = "COMPLETED" if outcome == "WIN" else "FAILED"
        await pool.execute("""
            INSERT INTO user_bounty_status (user_id, slot_id, status) VALUES ($1, $2, $3)
            ON CONFLICT (user_id, slot_id) DO UPDATE SET status = $3
        """, str(ctx.author.id), slot_id, final_status)

        result_embed = discord.Embed(
            title=f"Hunt Result: {outcome}",
            description=f"You {final_status.lower()} the bounty!",
            color=0x00FF00 if outcome == "WIN" else 0xFF0000
        )
        result_embed.add_field(name="Your Power", value=f"{int(totals['attacker']):,}")
        result_embed.add_field(name="Enemy Power", value=f"{int(totals['defender']):,}")

        if outcome == "WIN":
            # Grant Items
            item_rewards = {
                1: ("bond_small", 1, "Small Bond Gift"),
                2: ("bond_med", 1, "Medium Bond Gift"),
                3: ("bond_large", 1, "Large Bond Gift")
            }
            # Special UR Logic
            if bounty['tier'] == "UR":
                await pool.execute("UPDATE users SET coins = coins + 50, gacha_gems = gacha_gems + 5000 WHERE user_id = $1", str(ctx.author.id))
                item_id, qty, name = ("bond_ur", 1, "UR Bond Gift")
                result_embed.add_field(name="UR REWARDS!", value="50 Coins, 5000 Gems, UR Bond Gift!", inline=False)
            else:
                item_id, qty, name = item_rewards.get(slot_id, ("bond_small", 1, "Gift"))
            
            await pool.execute("""
                INSERT INTO user_items (user_id, item_id, quantity) VALUES ($1, $2, $3)
                ON CONFLICT (user_id, item_id) DO UPDATE SET quantity = user_items.quantity + $3
            """, str(ctx.author.id), item_id, qty)
            
            result_embed.add_field(name="Loot", value=f"+{qty} {name}")

        await loading_msg.delete()
        await ctx.reply(embed=result_embed)

    @commands.command(name="gift")
    async def gift(self, ctx, char_id: int, item_name: str):
        """Give a Bond Gift to a character. Usage: !gift <inventory_id> <small/med/large/ur>"""
        item_map = {
            "small": ("bond_small", 10),
            "med": ("bond_med", 50),
            "medium": ("bond_med", 50),
            "large": ("bond_large", 250),
            "ur": ("bond_ur", 2500)
        }
        
        selection = item_map.get(item_name.lower())
        if not selection:
            return await ctx.reply(f"❌ Invalid item. Use: small, med, large, ur.")
        
        item_db_id, exp_gain = selection
        pool = await get_db_pool()

        # Check Item Ownership
        row = await pool.fetchrow("SELECT quantity FROM user_items WHERE user_id = $1 AND item_id = $2", str(ctx.author.id), item_db_id)
        if not row or row['quantity'] < 1:
            return await ctx.reply(f"❌ You don't have any {item_name} gifts!")

        # Check Character Ownership
        char = await pool.fetchrow("SELECT id, bond_level, bond_exp FROM inventory WHERE id = $1 AND user_id = $2", char_id, str(ctx.author.id))
        if not char:
            return await ctx.reply("❌ Character not found in your inventory.")

        if char['bond_level'] >= 50:
            return await ctx.reply("❌ This character is already at Max Bond (Level 50)!")

        # Apply Logic
        cur_level = char['bond_level']
        cur_exp = char['bond_exp']
        cur_exp += exp_gain
        
        # Level Up Loop
        leveled_up = False
        while cur_level < 50:
            req = calculate_bond_exp_required(cur_level)
            if cur_exp >= req:
                cur_exp -= req
                cur_level += 1
                leveled_up = True
            else:
                break
        
        # Save
        async with pool.acquire() as conn:
            await conn.execute("UPDATE user_items SET quantity = quantity - 1 WHERE user_id = $1 AND item_id = $2", str(ctx.author.id), item_db_id)
            await conn.execute("UPDATE inventory SET bond_level = $1, bond_exp = $2 WHERE id = $3", cur_level, cur_exp, char_id)

        msg = f"🎁 Gifted **{item_name.upper()}**! +{exp_gain} EXP."
        if leveled_up:
            msg += f"\n🆙 **Bond Level Up!** Level {cur_level} (Power Multiplier: {1 + (cur_level * 0.005):.2f}x)"
        
        await ctx.reply(msg)

async def setup(bot):
    await bot.add_cog(Bounty(bot))