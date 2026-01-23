# cogs/battle.py

import discord
from discord.ext import commands
import random
import json
import typing
from core.database import get_db_pool
from core.game_math import calculate_effective_power
from core.image_gen import generate_battle_image
from core.skills import create_skill_instance, BattleContext

class Battle(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def get_team_for_battle(self, user_id):
        """Fetches the full team data for a specific user."""
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            team_row = await conn.fetchrow(
                "SELECT slot_1, slot_2, slot_3, slot_4, slot_5 FROM teams WHERE user_id = $1", 
                str(user_id)
            )
            if not team_row: return []

            slot_ids = [team_row[f'slot_{i}'] for i in range(1, 6) if team_row[f'slot_{i}']]
            if not slot_ids: return []

            chars = await conn.fetch("""
                SELECT 
                    i.id, c.anilist_id, c.name, 
                    FLOOR(c.true_power * (1 + (COALESCE(i.dupe_level, 0) * 0.05)) * (1 + (COALESCE(u.team_level, 1) * 0.01)))::int as true_power, 
                    i.dupe_level, c.ability_tags, c.rarity, c.rank, c.image_url 
                FROM inventory i 
                JOIN characters_cache c ON i.anilist_id = c.anilist_id
                LEFT JOIN users u ON i.user_id = u.user_id 
                WHERE i.id = ANY($1)
            """, slot_ids)
            
            char_map = {c['id']: dict(c) for c in chars}
            return [char_map[sid] for sid in slot_ids if sid in char_map]

    def generate_npc_team(self, difficulty):
        """Generates a mock NPC team based on difficulty."""
        team = []
        rules = {
            "easy":      [("R", 1501, 10000)] * 5,
            "normal":    [("R", 1501, 10000)] * 3 + [("SR", 251, 1500)] * 2,
            "hard":      [("SR", 251, 1500)] * 5,
            "expert":    [("SSR", 1, 250)] * 2 + [("SR", 251, 1500)] * 2 + [("R", 1501, 10000)] * 1,
            "nightmare": [("SSR", 1, 250)] * 3 + [("SR", 251, 1500)] * 2,
            "hell":      [("SSR", 1, 50)] * 2 + [("SSR", 1, 250)] * 3
        }
        setup = rules.get(difficulty.lower(), rules["normal"])
        
        for rarity, min_rank, max_rank in setup:
            rank = random.randint(min_rank, max_rank)
            mock_favs = int(600000 / (rank**0.5)) 
            power = calculate_effective_power(mock_favs, rarity, rank)
            team.append({
                'name': f"NPC {rarity}", 
                'true_power': power, 
                'ability_tags': [], 
                'rarity': rarity, 
                'image_url': None
            })
        return team

    @commands.command(name="battle")
    async def battle(self, ctx, target: typing.Union[discord.Member, str] = None):
        """Initiates a team-based battle against a player or NPC."""
        attacker_id = str(ctx.author.id)
        attacker_team = await self.get_team_for_battle(attacker_id)
        task_key = None

        if not attacker_team:
            return await ctx.reply("❌ Your team is empty! Use `!team` to set one up.")

        if isinstance(target, discord.Member):
            defender_team = await self.get_team_for_battle(str(target.id))
            defender_name = target.display_name
            task_key = "pvp"
            if not defender_team:
                return await ctx.reply(f"❌ {target.display_name} does not have a team set up.")
        elif isinstance(target, str):
            diff = target.lower()
            valid_diffs = ["easy", "normal", "hard", "expert", "nightmare", "hell"]
            if diff not in valid_diffs:
                return await ctx.reply(f"❌ Invalid difficulty. Choose from: {', '.join(valid_diffs)}")
            
            defender_team = self.generate_npc_team(diff)
            defender_name = f"{diff.capitalize()} NPC"
            task_key = diff
        else:
            defender_team = self.generate_npc_team("normal")
            defender_name = "Training Dummy NPC"
            task_key = "normal"

        loading_msg = await ctx.reply("⚔️ **The battle is commencing...**")

        # --- 1. INITIALIZE ENGINE ---
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

        # --- 2. PHASE: START OF BATTLE ---
        # (Zodiacs, Disables, Kamikaze, Team Debuffs)
        for skill in all_skills:
            await skill.on_battle_start(battle_ctx)

        # --- 3. PHASE: CALCULATION ---
        final_powers = {"attacker": [], "defender": []}

        # Calculate Individual Powers (Base * Mods * Context)
        for side in ["attacker", "defender"]:
            team = battle_ctx.get_team(side)
            for i, char in enumerate(team):
                if not char: 
                    final_powers[side].append(0)
                    continue
                
                # Base Power
                p = char['true_power']
                
                # Ask skills for multipliers (Only OWN skills)
                my_skills = [s for s in all_skills if s.side == side and s.idx == i]
                for s in my_skills:
                    mod = await s.get_power_modifier(battle_ctx, p)
                    p *= mod

                # Apply Context Multipliers (Debuffs, Global Buffs)
                p *= battle_ctx.multipliers[side][i]
                p += battle_ctx.flat_bonuses[side][i]

                # Apply Variance (unless locked by Dragon Zodiac)
                if battle_ctx.flags.get("variance_override", {}).get(f"{side}_{i}"):
                    variance = battle_ctx.flags["variance_override"][f"{side}_{i}"]
                else:
                    variance = random.uniform(0.9, 1.1)
                
                final_powers[side].append(max(0, p * variance))

        # Post-Calculation Logic (Monkey swap, Dog copy, etc.)
        for skill in all_skills:
            await skill.on_post_power_calculation(battle_ctx, final_powers)

        # Final Summation
        final_team_totals = {"attacker": 0, "defender": 0}
        for side in ["attacker", "defender"]:
            total = sum(final_powers[side])
            final_team_totals[side] = total

        # --- 4. PHASE: OUTCOME ---
        initial_win = final_team_totals["attacker"] > final_team_totals["defender"]
        outcome = "WIN" if initial_win else "LOSS"
        
        # Check Snake Trap
        if not initial_win and battle_ctx.flags.get("snake_trap"):
            outcome = "DRAW"
            battle_ctx.add_log("attacker", None, "🐍 The **Snake Zodiac** trap triggered! Defeat -> **DRAW**.")

        # Check Revive Skills (Only trigger on LOSS)
        if outcome == "LOSS":
             for skill in all_skills:
                 if skill.side == "attacker":
                     new_outcome = await skill.on_battle_end(battle_ctx, outcome)
                     if new_outcome: 
                         outcome = new_outcome
                         break

        # --- EMBED GENERATION ---
        win_idx = 1 if outcome == "WIN" else (2 if outcome == "LOSS" else 0)
        color = 0x5865F2 if win_idx == 1 else (0xED4245 if win_idx == 2 else 0x979C9F)
        
        # Flatten logs
        atk_logs = [l for slot in battle_ctx.logs["attacker"].values() for l in slot] + battle_ctx.misc_logs["attacker"]
        def_logs = [l for slot in battle_ctx.logs["defender"].values() for l in slot] + battle_ctx.misc_logs["defender"]

        embed = discord.Embed(
            title=f"⚔️ {ctx.author.display_name} vs {defender_name}",
            description=f"🏆 **Winner: {'Draw' if win_idx == 0 else (ctx.author.display_name if win_idx == 1 else defender_name)}**",
            color=color
        )

        embed.add_field(name=f"🔵 {ctx.author.display_name}", value=f"Total: **{int(final_team_totals['attacker']):,}**", inline=True)
        embed.add_field(name=f"🔴 {defender_name}", value=f"Total: **{int(final_team_totals['defender']):,}**", inline=True)

        if atk_logs:
            embed.add_field(name="🔹 Attacker Highlights", value="\n".join(atk_logs[:10]), inline=False)
        if def_logs:
            embed.add_field(name="🔸 Defender Highlights", value="\n".join(def_logs[:10]), inline=False)

        # Task Progress
        pool = await get_db_pool()
        await pool.execute("""
            INSERT INTO daily_tasks (user_id, task_key, progress, last_updated, is_claimed)
            VALUES ($1, $2, 1, CURRENT_DATE, FALSE)
            ON CONFLICT (user_id, task_key) 
            DO UPDATE SET 
                progress = 1, 
                last_updated = CURRENT_DATE, 
                is_claimed = FALSE
            WHERE daily_tasks.last_updated < CURRENT_DATE OR daily_tasks.progress = 0
        """, attacker_id, task_key)

        # Image
        img_bytes = await generate_battle_image(attacker_team, defender_team, ctx.author.display_name, defender_name, winner_idx=win_idx)
        file = discord.File(fp=img_bytes, filename="battle.png")
        embed.set_image(url="attachment://battle.png")

        await loading_msg.delete()
        await ctx.reply(file=file, embed=embed)

async def setup(bot):
    await bot.add_cog(Battle(bot))