import discord
from discord.ext import commands
import random
import asyncio
from core.database import get_db_pool, get_user
from core.game_math import simulate_standoff, calculate_effective_power
from core.skill_handlers import SkillHandler

class Battle(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def get_team_for_battle(self, user_id):
        """Fetches a user's battle team with full stats and ability tags."""
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            # Fetch the inventory IDs from the teams table
            team_row = await conn.fetchrow("SELECT slot_1, slot_2, slot_3, slot_4, slot_5 FROM teams WHERE user_id = $1", str(user_id))
            if not team_row: return []

            slot_ids = [v for v in team_row.values() if v is not None]
            if not slot_ids: return []

            # Join with cache to get power and skills
            chars = await conn.fetch("""
                SELECT i.id, c.name, c.true_power, c.ability_tags, c.rarity, c.rank
                FROM inventory i
                JOIN characters_cache c ON i.anilist_id = c.anilist_id
                WHERE i.id = ANY($1)
            """, slot_ids)
            return [dict(c) for c in chars]

    def generate_npc_team(self, difficulty):
        """Generates a temporary NPC team based on the specified difficulty."""
        team = []
        rules = {
            "easy":      [("R", 1501, 10000)] * 5,
            "normal":    [("R", 1501, 10000)] * 3 + [("SR", 251, 1500)] * 2,
            "hard":      [("SR", 251, 1500)] * 5,
            "expert":    [("SSR", 1, 250)] * 2 + [("SR", 251, 1500)] * 2 + [("R", 1501, 10000)] * 1,
            "nightmare": [("SSR", 1, 250)] * 3 + [("SR", 251, 1500)] * 2,
            "hell":      [("SSR", 1, 50)] * 2 + [("SSR", 1, 250)] * 3
        }
        
        setup = rules.get(difficulty.lower())
        if not setup: return None

        for rarity, min_rank, max_rank in setup:
            rank = random.randint(min_rank, max_rank)
            # Use a dummy fav count based on rank to estimate power
            # (Rank 1 is ~550k, Rank 10k is ~100)
            mock_favs = int(600000 / (rank**0.5)) 
            power = calculate_effective_power(mock_favs, rarity, rank)
            
            team.append({
                'name': f"NPC {rarity}",
                'true_power': power,
                'ability_tags': [], # NPCs generally don't have skills unless specified
                'rarity': rarity
            })
        return team

    @commands.command(name="battle")
    async def battle(self, ctx, opponent: discord.Member = None, difficulty: str = None):
        """
        Usage: !battle @user (PVP) or !battle easy/hell (PVE)
        """
        user_id = str(ctx.author.id)
        attacker_team = await self.get_team_for_battle(user_id)
        
        if not attacker_team:
            return await ctx.send("❌ Your battle team is empty! Use `!set_team` first.")

        # 1. Resolve Defender
        defender_name = ""
        if opponent:
            defender_team = await self.get_team_for_battle(str(opponent.id))
            if not defender_team:
                return await ctx.send(f"❌ {opponent.display_name} has no battle team set.")
            defender_name = opponent.display_name
            mode = "pvp"
        elif difficulty:
            defender_team = self.generate_npc_team(difficulty)
            if not defender_team:
                return await ctx.send("❌ Invalid difficulty. Choose: easy, normal, hard, expert, nightmare, hell.")
            defender_name = f"{difficulty.capitalize()} NPC"
            mode = difficulty.lower()
        else:
            return await ctx.send("❓ Who are you fighting? Use `!battle @user` or `!battle easy`.")

        msg = await ctx.send(f"⚔️ **BATTLE START:** {ctx.author.display_name} vs {defender_name}...")
        await asyncio.sleep(1)

        # 2. Skill Phase: Active Effects Collection
        atk_active = SkillHandler.get_active_skills(attacker_team, context='b')
        def_active = SkillHandler.get_active_skills(defender_team, context='b')

        # 3. Skill Phase: Kamikaze (Removes units before power sum)
        atk_ignore = SkillHandler.handle_kamikaze(defender_team, atk_active)
        def_ignore = SkillHandler.handle_kamikaze(attacker_team, def_active)

        # 4. Power Calculation (Individual Buffs + Sum)
        atk_power = 0
        for i, char in enumerate(attacker_team):
            if i in def_ignore: continue
            p = SkillHandler.apply_individual_battle_skills(char['true_power'], char)
            atk_power += p

        def_power = 0
        for i, char in enumerate(defender_team):
            if i in atk_ignore: continue
            p = SkillHandler.apply_individual_battle_skills(char['true_power'], char)
            def_power += p

        # 5. Power Calculation (Team Debuffs like Guard)
        atk_final_power = SkillHandler.apply_team_battle_mods(atk_power, def_active)
        def_final_power = SkillHandler.apply_team_battle_mods(def_power, atk_active)

        # 6. Simulate Standoff
        # Note: simulate_standoff in game_math returns (WinnerLabel, Chance)
        winner_label, chance = simulate_standoff(atk_final_power, def_final_power)
        won = (winner_label == "Player A")

        # 7. Skill Phase: Revive
        final_result = SkillHandler.handle_revive(won, atk_active)

        # 8. Database Update (Tasks)
        pool = await get_db_pool()
        task_key = "pvp" if mode == "pvp" else mode
        await pool.execute("""
            INSERT INTO daily_tasks (user_id, task_key, progress)
            VALUES ($1, $2, 1)
            ON CONFLICT (user_id, task_key) DO UPDATE SET progress = 1
        """, user_id, task_key)

        # 9. Result Embed
        color = 0x00ff00 if final_result == "WIN" else (0xffff00 if final_result == "DRAW" else 0xff0000)
        embed = discord.Embed(title="Combat Results", color=color)
        embed.add_field(name=ctx.author.display_name, value=f"Power: **{int(atk_final_power):,}**", inline=True)
        embed.add_field(name=defender_name, value=f"Power: **{int(def_final_power):,}**", inline=True)
        
        res_text = "🏆 **YOU WON!**" if final_result == "WIN" else ("🤝 **IT'S A DRAW!**" if final_result == "DRAW" else "💀 **YOU LOST...**")
        embed.description = f"{res_text}\nWin Probability: `{chance:.1f}%`"
        
        if atk_ignore: embed.set_footer(text=f"Kamikaze took out {len(atk_ignore)} enemies!")

        await msg.edit(content=None, embed=embed)

async def setup(bot):
    await bot.add_cog(Battle(bot))