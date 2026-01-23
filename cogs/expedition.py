import discord
from discord.ext import commands
import datetime
import json
from core.database import get_db_pool, get_user
from core.economy import Economy, GEMS_PER_PULL
from core.skills import get_skill_info
from core.emotes import Emotes

class Expedition(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _get_next_level_req(self, level):
        """
        Calculates XP needed for the next level.
        Formula: Level^2 * 100
        Ex: Lvl 1->2 needs 100 XP. Lvl 10->11 needs 10,000 XP.
        """
        return (level ** 2) * 100

    def _get_active_skills(self, characters, context):
        """
        Helper to calculate active skills for a specific context (e.g., 'e' for expedition).
        Respects the 'stackable' flag from the skill registry.
        """
        counts = {}
        for char in characters:
            if not char: continue
            tags = char.get('ability_tags', [])
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except json.JSONDecodeError:
                    tags = []
            
            for tag in tags:
                info = get_skill_info(tag)
                if info and info.get('applies_in') == context:
                    is_stackable = info.get('stackable', False)
                    # If not stackable and we already have it, skip
                    if not is_stackable and tag in counts:
                        continue
                    counts[tag] = counts.get(tag, 0) + 1
        return counts

    async def get_expedition_data(self, user_id):
        """Fetches the user's current expedition squad and timing info."""
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT slot_ids, start_time, last_claim 
                FROM expeditions WHERE user_id = $1
            """, str(user_id))
            
            if not row:
                # Initialize row if missing
                await conn.execute("INSERT INTO expeditions (user_id) VALUES ($1)", str(user_id))
                return {'slot_ids': [], 'start_time': None, 'last_claim': None}
            return dict(row)

    async def get_detailed_team(self, slot_ids):
        """Fetches full character stats and skills for the assigned IDs."""
        if not slot_ids: return []
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            # Fetch details for the specific inventory IDs
            rows = await conn.fetch("""
                SELECT i.id, c.name, c.true_power, c.ability_tags 
                FROM inventory i
                JOIN characters_cache c ON i.anilist_id = c.anilist_id
                WHERE i.id = ANY($1)
            """, slot_ids)
            return [dict(r) for r in rows]

    @commands.command(name="set_expedition", aliases=["se"])
    async def set_expedition_team(self, ctx, *ids: int):
        """Assigns up to 5 characters to the expedition squad."""
        if len(ids) > 5:
            return await ctx.reply("❌ An expedition team can only have up to 5 characters.")
        
        pool = await get_db_pool()
        # Verify ownership of all IDs
        async with pool.acquire() as conn:
            owned = await conn.fetch("SELECT id FROM inventory WHERE user_id = $1 AND id = ANY($2)", str(ctx.author.id), list(ids))
            if len(owned) != len(ids):
                return await ctx.reply("❌ One or more IDs provided are not in your inventory.")

            await conn.execute("UPDATE expeditions SET slot_ids = $1 WHERE user_id = $2", list(ids), str(ctx.author.id))
        
        await ctx.reply(f"✅ Expedition team updated with {len(ids)} characters.")

    @commands.command(name="expedition", aliases=["ex"])
    async def expedition_status(self, ctx, action: str = "status"):
        user_id = str(ctx.author.id)
        data = await self.get_expedition_data(user_id)
        
        if action == "start":
            if not data['slot_ids']:
                return await ctx.reply("❌ Your expedition team is empty! Use `!set_expedition <ids>` first.")
            if data['start_time']:
                return await ctx.reply("⚠️ An expedition is already in progress.")
            
            pool = await get_db_pool()
            await pool.execute("UPDATE expeditions SET start_time = $1 WHERE user_id = $2", datetime.datetime.utcnow(), user_id)
            await ctx.reply("🚀 **Expedition Started!** Use `!ex claim` later to collect your gems.")

        elif action == "claim":
            if not data['start_time']:
                return await ctx.reply("❌ No expedition is currently running.")

            # 1. Timing
            now = datetime.datetime.utcnow()
            duration_seconds = (now - data['start_time']).total_seconds()
            
            if duration_seconds < 60: # 1 minute minimum for testing
                return await ctx.reply("⏳ Expedition has been running for less than a minute. Wait a bit longer!")

            # 2. Get Team & Skills
            team_chars = await self.get_detailed_team(data['slot_ids'])
            total_power = sum(c['true_power'] for c in team_chars)
            
            # Fetch all user characters for 'Global' skills like Master of Coin
            pool = await get_db_pool()
            all_inventory_rows = await pool.fetch("""
                SELECT c.ability_tags FROM inventory i 
                JOIN characters_cache c ON i.anilist_id = c.anilist_id 
                WHERE i.user_id = $1
            """, user_id)
            all_inventory = [dict(r) for r in all_inventory_rows]

            # 3. Calculate Base Yield (Gems)
            base_gems = Economy.calculate_expedition_yield(total_power, duration_seconds)
            
            # 4. Apply Multipliers from Skills
            # UPDATED: Use local helper instead of removed SkillHandler
            team_skills = self._get_active_skills(team_chars, context='e')
            global_skills = self._get_active_skills(all_inventory, context='g')

            multiplier = 1.0
            
            # Hardworker: Stackable, applies in 'e'
            if "Hardworker" in team_skills:
                multiplier += (0.15 * team_skills["Hardworker"])
            
            # Master of Coin: Stackable, applies in 'g'
            if "Master of Coin" in global_skills:
                multiplier += (0.10 * global_skills["Master of Coin"])
            
            # The Long Road: Not stackable, applies in 'e'
            if "The Long Road" in team_skills:
                duration_hours = min(duration_seconds / 3600, 24)
                long_road_bonus = 0.24 * (duration_hours / 24)
                multiplier += long_road_bonus

            final_gems = int(base_gems * multiplier)

            # --- LEVELING LOGIC START ---
            
            # A. Calculate XP (1 XP per minute)
            xp_gained = int(duration_seconds / 60)
            
            # B. Fetch Current Level & XP
            user_row = await pool.fetchrow("SELECT team_level, team_xp FROM users WHERE user_id = $1", user_id)
            cur_lvl = user_row['team_level'] if user_row and user_row['team_level'] else 1
            cur_xp = user_row['team_xp'] if user_row and user_row['team_xp'] else 0
            
            # C. Process Level Ups
            cur_xp += xp_gained
            leveled_up = False
            levels_gained = 0
            
            while True:
                req_xp = self._get_next_level_req(cur_lvl)
                if cur_xp >= req_xp:
                    cur_xp -= req_xp
                    cur_lvl += 1
                    leveled_up = True
                    levels_gained += 1
                else:
                    break
            
            # --- LEVELING LOGIC END ---

            # 5. Distribute Rewards (Gems + XP + Level) and Reset
            await pool.execute("""
                UPDATE users 
                SET gacha_gems = gacha_gems + $1, 
                    team_level = $2, 
                    team_xp = $3
                WHERE user_id = $4
            """, final_gems, cur_lvl, cur_xp, user_id)
            
            await pool.execute("""
                UPDATE expeditions SET start_time = NULL, last_claim = $1 WHERE user_id = $2
            """, now, user_id)

            # 6. Build Message
            msg = f"💰 **Expedition Complete!**\nEarned: **{final_gems:,} {Emotes.GEMS}**\n✨ **Team XP:** +{xp_gained}"
            
            if leveled_up:
                msg += f"\n\n🎉 **LEVEL UP!**\nYou reached **Team Level {cur_lvl}**!\n⚡ All units gained **+{levels_gained}% Power** (Total: +{cur_lvl}%)"
            else:
                req_next = self._get_next_level_req(cur_lvl)
                msg += f"\n📊 Progress: `{cur_xp}/{req_next} XP` to Level {cur_lvl + 1}"

            msg += f"\nMultipliers: `{multiplier:.2f}x`"
            
            await ctx.reply(msg)

        else: # Default: Status
            if not data['start_time']:
                await ctx.reply("🛰️ **Status:** Idle. Use `!ex start` to begin.")
            else:
                now = datetime.datetime.utcnow()
                elapsed = now - data['start_time']
                await ctx.reply(f"🛰️ **Status:** Expedition in progress...\nElapsed Time: `{str(elapsed).split('.')[0]}`")

async def setup(bot):
    await bot.add_cog(Expedition(bot))