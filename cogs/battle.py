import discord
from discord.ext import commands
import random
import asyncio
import typing
from core.database import get_db_pool, get_user
from core.game_math import simulate_standoff, calculate_effective_power
from core.skill_handlers import SkillHandler
from core.image_gen import generate_battle_image # <--- Import this

class Battle(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def get_team_for_battle(self, user_id):
        """Fetches a user's battle team with full stats."""
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            team_row = await conn.fetchrow("SELECT slot_1, slot_2, slot_3, slot_4, slot_5 FROM teams WHERE user_id = $1", str(user_id))
            if not team_row: return []

            slot_ids = [v for v in team_row.values() if v is not None]
            if not slot_ids: return []

            # UPDATED SQL: Now fetches 'image_url'
            chars = await conn.fetch("""
                SELECT i.id, c.name, c.true_power, c.ability_tags, c.rarity, c.rank, c.image_url
                FROM inventory i
                JOIN characters_cache c ON i.anilist_id = c.anilist_id
                WHERE i.id = ANY($1)
            """, slot_ids)
            return [dict(c) for c in chars]

    def generate_npc_team(self, difficulty):
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
            mock_favs = int(600000 / (rank**0.5)) 
            power = calculate_effective_power(mock_favs, rarity, rank)
            
            team.append({
                'name': f"NPC {rarity}",
                'true_power': power,
                'ability_tags': [], 
                'rarity': rarity,
                'image_url': None # Generator handles this as a placeholder
            })
        return team

    @commands.command(name="battle")
    async def battle(self, ctx, target: typing.Union[discord.Member, str] = None):
        user_id = str(ctx.author.id)
        attacker_team = await self.get_team_for_battle(user_id)
        
        if not attacker_team:
            return await ctx.send("❌ Your battle team is empty! Use `!set_team` first.")

        opponent = None
        difficulty = None
        mode = None

        if isinstance(target, discord.Member):
            opponent = target
            mode = "pvp"
        elif isinstance(target, str):
            difficulty = target
            mode = difficulty.lower()
        else:
            return await ctx.send("❓ Who are you fighting? Use `!battle @user` or `!battle easy`.")

        defender_name = ""
        defender_team = []

        if mode == "pvp":
            defender_team = await self.get_team_for_battle(str(opponent.id))
            if not defender_team: return await ctx.send(f"❌ {opponent.display_name} has no battle team.")
            defender_name = opponent.display_name
        else:
            defender_team = self.generate_npc_team(difficulty)
            if not defender_team: return await ctx.send("❌ Invalid difficulty.")
            defender_name = f"{difficulty.capitalize()} NPC"

        # Notify Start
        loading_msg = await ctx.send(f"⚔️ **Generating Battle: {ctx.author.display_name} vs {defender_name}...**")

        # --- LOGIC & SIMULATION ---
        atk_active = SkillHandler.get_active_skills(attacker_team, context='b')
        def_active = SkillHandler.get_active_skills(defender_team, context='b')
        atk_ignore = SkillHandler.handle_kamikaze(defender_team, atk_active)
        def_ignore = SkillHandler.handle_kamikaze(attacker_team, def_active)

        atk_power = sum(SkillHandler.apply_individual_battle_skills(c['true_power'], c) for i, c in enumerate(attacker_team) if i not in def_ignore)
        def_power = sum(SkillHandler.apply_individual_battle_skills(c['true_power'], c) for i, c in enumerate(defender_team) if i not in atk_ignore)

        atk_final = SkillHandler.apply_team_battle_mods(atk_power, def_active)
        def_final = SkillHandler.apply_team_battle_mods(def_power, atk_active)

        winner_label, chance = simulate_standoff(atk_final, def_final)
        final_result = SkillHandler.handle_revive(winner_label == "Player A", atk_active)

        # 0 = Draw, 1 = Player Wins, 2 = Player Loses
        win_code = 1 if final_result == "WIN" else (2 if final_result == "LOSS" else 0)

        # --- DB UPDATE ---
        pool = await get_db_pool()
        task_key = "pvp" if mode == "pvp" else mode 
        await pool.execute("""
            INSERT INTO daily_tasks (user_id, task_key, progress)
            VALUES ($1, $2, 1)
            ON CONFLICT (user_id, task_key) DO UPDATE SET progress = daily_tasks.progress + 1
        """, user_id, task_key)

        # --- IMAGE GENERATION ---
        # Pass COPY of teams to avoid modifying the original dicts during image gen logic
        img_bytes = await generate_battle_image(
            attacker_team, 
            defender_team, 
            ctx.author.display_name, 
            defender_name, 
            winner_idx=win_code
        )

        # --- EMBED ---
        color = 0x00ff00 if final_result == "WIN" else (0xff0000 if final_result == "LOSS" else 0xffff00)
        embed = discord.Embed(title="Combat Result", color=color)
        embed.add_field(name=f"{ctx.author.display_name} {'👑' if win_code==1 else ''}", value=f"Power: **{int(atk_final):,}**", inline=True)
        embed.add_field(name=f"{defender_name} {'👑' if win_code==2 else ''}", value=f"Power: **{int(def_final):,}**", inline=True)
        
        embed.set_image(url="attachment://battle.png")
        embed.set_footer(text=f"Win Probability: {chance:.1f}%")

        await loading_msg.delete()
        await ctx.send(file=discord.File(fp=img_bytes, filename="battle.png"), embed=embed)

async def setup(bot):
    await bot.add_cog(Battle(bot))