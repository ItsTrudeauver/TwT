import discord
from discord.ext import commands
import random
import json
import io
from core.database import get_db_pool
from core.game_math import calculate_effective_power
from core.skill_handlers import SkillHandler
from core.image_gen import generate_battle_image

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
            if not team_row:
                return []

            # Explicitly capture slot IDs in the order of slot_1 to slot_5
            slot_ids = [team_row[f'slot_{i}'] for i in range(1, 6) if team_row[f'slot_{i}']]
            if not slot_ids:
                return []

            chars = await conn.fetch("""
                SELECT 
                    i.id, 
                    c.name, 
                    FLOOR(c.true_power * (1 + (COALESCE(i.dupe_level, 0) * 0.05)) * (1 + (COALESCE(u.team_level, 1) * 0.01)))::int as true_power, 
                    i.dupe_level, -- FETCH THIS FIELD FOR THE IMAGE GEN
                    c.ability_tags, 
                    c.rarity, 
                    c.rank, 
                    c.image_url 
                FROM inventory i 
                JOIN characters_cache c ON i.anilist_id = c.anilist_id
                LEFT JOIN users u ON i.user_id = u.user_id 
                WHERE i.id = ANY($1)
            """, slot_ids)
            
            # Reorder character data to strictly match the slot sequence
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
            # Mock power calculation for NPCs
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
    async def battle(self, ctx, target: discord.Member = None):
        """Initiates a team-based battle against a player or NPC."""
        attacker_id = str(ctx.author.id)
        attacker_team = await self.get_team_for_battle(attacker_id)

        if not attacker_team:
            return await ctx.reply("❌ Your team is empty! Use `!team` to set one up.")

        if target:
            defender_team = await self.get_team_for_battle(str(target.id))
            defender_name = target.display_name
            if not defender_team:
                return await ctx.reply(f"❌ {target.display_name} does not have a team set up.")
        else:
            defender_team = self.generate_npc_team("normal")
            defender_name = "Training Dummy NPC"

        loading_msg = await ctx.reply("⚔️ **The battle is commencing...**")

        # --- INITIALIZATION ---
        # Collect logs per character slot to ensure visual order matches slot order
        atk_slot_logs = {i: [] for i in range(len(attacker_team))}
        def_slot_logs = {i: [] for i in range(len(defender_team))}
        atk_misc_logs, def_misc_logs = [], [] # For team-wide effects like Kamikaze
        
        atk_active_skills = SkillHandler.get_active_skills(attacker_team)
        def_active_skills = SkillHandler.get_active_skills(defender_team)

        # 1. Handle Pre-Battle (Zodiac Rolls)
        def pre_battle_phase(team, opp_team, slot_logs, active_skills):
            zodiac_effects = []
            for i, char in enumerate(team):
                tags = char.get('ability_tags', [])
                if isinstance(tags, str): tags = json.loads(tags)
                
                if "Queen of the Zodiacs" in tags:
                    eff, log = SkillHandler.handle_zodiac_roll(char, team, opp_team)
                    zodiac_effects.append((i, eff))
                    slot_logs[i].append(log)
            return zodiac_effects

        atk_z_effects = pre_battle_phase(attacker_team, defender_team, atk_slot_logs, atk_active_skills)
        def_z_effects = pre_battle_phase(defender_team, attacker_team, def_slot_logs, def_active_skills)

        # 2. Handle Kamikaze (Immediate removals)
        atk_ignored, k_logs_a = SkillHandler.handle_kamikaze(defender_team, atk_active_skills)
        def_ignored, k_logs_d = SkillHandler.handle_kamikaze(attacker_team, def_active_skills)
        atk_misc_logs.extend(k_logs_a)
        def_misc_logs.extend(k_logs_d)

        # 3. Final Power Calculation with Logic Overrides
        def calculate_total_team_power(team, ignored, z_effects, opp_team, slot_logs, misc_logs, enemy_skills):
            team_multiplier = 1.0
            temp_powers = []
            
            # Step A: Base Individual Calculations (Surge, Lucky 7, etc)
            for i, char in enumerate(team):
                if i in ignored:
                    temp_powers.append(0)
                    continue
                
                p, logs = SkillHandler.apply_individual_battle_skills(char['true_power'], char)
                slot_logs[i].extend(logs)
                
                variance = random.uniform(0.9, 1.1)
                for idx, eff in z_effects:
                    if idx == i:
                        p *= eff.get("self_mult", 1.0)
                        if "override_variance" in eff:
                            variance = eff["override_variance"]
                    if "team_mult" in eff:
                        team_multiplier *= eff["team_mult"]
                
                temp_powers.append(p * variance)

            # Step B: Apply Logic Overrides (Monkey, Sheep, Dog)
            for idx, eff in z_effects:
                if eff.get("sheep_logic"):
                    opp_max = max([oc['true_power'] for oc in opp_team], default=0)
                    temp_powers[idx] = opp_max
                if "monkey_target_idx" in eff:
                    target_idx = eff["monkey_target_idx"]
                    temp_powers[idx], opp_team[target_idx]['true_power'] = opp_team[target_idx]['true_power'], temp_powers[idx]
                if eff.get("dog_logic"):
                    temp_powers[idx] = max(temp_powers)

            # Step C: Final Team Tally & Mods
            team_total = sum(temp_powers) * team_multiplier
            final_total, team_mods = SkillHandler.apply_team_battle_mods(team_total, enemy_skills)
            misc_logs.extend(team_mods)
            
            return final_total

        final_atk_power = calculate_total_team_power(attacker_team, def_ignored, atk_z_effects, defender_team, atk_slot_logs, atk_misc_logs, def_active_skills)
        final_def_power = calculate_total_team_power(defender_team, atk_ignored, def_z_effects, attacker_team, def_slot_logs, def_misc_logs, atk_active_skills)

        # Flatten logs: Slot 1 -> Slot 5 (Zodiac + Individual combined), then misc team effects
        atk_logs = [log for i in range(len(attacker_team)) for log in atk_slot_logs[i]] + atk_misc_logs
        def_logs = [log for i in range(len(defender_team)) for log in def_slot_logs[i]] + def_misc_logs

        # --- OUTCOME ---
        initial_win = final_atk_power > final_def_power
        
        # Check for Snake/Revive Logic
        snake_trap = any(e.get("force_draw_on_loss") for _, e in (atk_z_effects if not initial_win else def_z_effects))
        outcome, outcome_logs = SkillHandler.handle_revive(initial_win, atk_active_skills, snake_trap)
        
        if initial_win:
            def_logs.extend(outcome_logs)
        else:
            atk_logs.extend(outcome_logs)

        # --- EMBED GENERATION ---
        win_idx = 1 if outcome == "WIN" else (2 if outcome == "LOSS" else 0)
        color = 0x5865F2 if win_idx == 1 else (0xED4245 if win_idx == 2 else 0x979C9F)
        
        embed = discord.Embed(
            title=f"⚔️ {ctx.author.display_name} vs {defender_name}",
            description=f"🏆 **Winner: {'Draw' if win_idx == 0 else (ctx.author.display_name if win_idx == 1 else defender_name)}**",
            color=color
        )

        embed.add_field(name=f"🔵 {ctx.author.display_name}", value=f"Total: **{int(final_atk_power):,}**", inline=True)
        embed.add_field(name=f"🔴 {defender_name}", value=f"Total: **{int(final_def_power):,}**", inline=True)

        if atk_logs:
            embed.add_field(name="🔹 Attacker Highlights", value="\n".join(atk_logs[:10]), inline=False)
        if def_logs:
            embed.add_field(name="🔸 Defender Highlights", value="\n".join(def_logs[:10]), inline=False)

        # Image
        img_bytes = await generate_battle_image(attacker_team, defender_team, ctx.author.display_name, defender_name, winner_idx=win_idx)
        file = discord.File(fp=img_bytes, filename="battle.png")
        embed.set_image(url="attachment://battle.png")

        await loading_msg.delete()
        await ctx.reply(file=file, embed=embed)

async def setup(bot):
    await bot.add_cog(Battle(bot))