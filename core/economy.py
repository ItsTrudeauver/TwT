# core/economy.py

import os
import aiohttp
import datetime
import asyncio
from core.database import get_db_pool

# --- CONSTANTS ---
GEMS_PER_PULL = 1000  # 1 Multi = 10,000 Gems
BOAT_COST_PER_PULL = 100_000_000 # 100 Million
MAX_BOAT_PULLS_DAILY = 10
UNBELIEVABOAT_TOKEN = os.getenv("UNBELIEVABOAT_TOKEN")
ECONOMY_GUILD_ID = "1455361761388531746"

class Economy:
    @staticmethod
    async def is_free_pull(user, bot):
        """Checks if the user gets a free pull (Owner + Toggle)."""
        if not await bot.is_owner(user):
            return False
        
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT value_bool FROM global_settings WHERE key = 'owner_free_pulls'")
            return row['value_bool'] if row else True

    @staticmethod
    def calculate_expedition_yield(total_power, duration_seconds):
        """
        Calculates Gem yield based on power and time.
        Baseline: 20k Power -> 10 Pulls/Day (10k Gems)
        Cap: 60k Power -> 20 Pulls/Day (20k Gems)
        Abs Cap: 80k Power -> 25 Pulls/Day (25k Gems)
        """
        hours = duration_seconds / 3600
        
        # Calculate Pulls Per Day (PPD) based on piecewise logic
        if total_power < 20000:
            # Scale up to 10
            ppd = (total_power / 20000) * 10
        elif total_power < 60000:
            # Scale from 10 to 20
            ppd = 10 + ((total_power - 20000) / 4000)
        else:
            # Scale from 20 up to 25 (at 80k)
            ppd = min(25, 20 + ((total_power - 60000) / 4000))
        
        # Convert Pulls/Day to Gems/Hour
        gems_per_day = ppd * GEMS_PER_PULL
        gems_per_hour = gems_per_day / 24
        
        return int(gems_per_hour * hours)

    @staticmethod
    async def buy_pulls_with_boat(user_id, guild_id, count):
        """
        Interacts with Unbelievaboat API to buy pulls.
        100M credits = 1 Pull. Max 10 per day.
        """
        try:
            if count <= 0 or count > MAX_BOAT_PULLS_DAILY:
                return {"success": False, "message": f"You can only buy 1 to {MAX_BOAT_PULLS_DAILY} pulls."}

            pool = await get_db_pool()
            async with pool.acquire() as conn:
                # Check Daily Limit
                user = await conn.fetchrow("SELECT daily_boat_pulls, last_boat_pull_at FROM users WHERE user_id = $1", str(user_id))
                
                if not user:
                    return {"success": False, "message": "User profile not found. Please use the bot first."}

                now = datetime.datetime.utcnow()
                
                # FIX: Handle case where last_boat_pull_at is None (new users)
                last_pull_at = user['last_boat_pull_at']
                current_pulls = user['daily_boat_pulls'] if last_pull_at and last_pull_at.date() == now.date() else 0
                
                if current_pulls + count > MAX_BOAT_PULLS_DAILY:
                    return {"success": False, "message": f"Daily limit reached. You have {MAX_BOAT_PULLS_DAILY - current_pulls} pulls left for today."}

                # Unbelievaboat API Call
                total_cost = count * BOAT_COST_PER_PULL
                
                if not UNBELIEVABOAT_TOKEN:
                    return {"success": False, "message": "Unbelievaboat API token is not configured."}

                headers = {"Authorization": UNBELIEVABOAT_TOKEN, "Accept": "application/json"}
                
                # Use ECONOMY_GUILD_ID from variables if set, otherwise fall back to command's guild
                target_guild_id = ECONOMY_GUILD_ID if ECONOMY_GUILD_ID != 0 else guild_id
                url = f"https://unbelievaboat.com/api/v1/guilds/{target_guild_id}/users/{user_id}"
                
                # FIX: Added timeout to prevent the command from being stuck forever on network issues
                timeout = aiohttp.ClientTimeout(total=15)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    data = {"bank": -total_cost}
                    async with session.patch(url, headers=headers, json=data) as resp:
                        if resp.status != 200:
                            try:
                                error_data = await resp.json()
                                error_msg = error_data.get('message', 'Insufficient funds in bank.')
                            except:
                                error_msg = f"HTTP {resp.status} Error"
                            return {"success": False, "message": f"Unbelievaboat Error: {error_msg}"}

                # Update DB
                await conn.execute("""
                    UPDATE users 
                    SET gacha_gems = gacha_gems + $1, 
                        daily_boat_pulls = $2, 
                        last_boat_pull_at = $3,
                        boat_credits_spent = boat_credits_spent + $4
                    WHERE user_id = $5
                """, (count * GEMS_PER_PULL), (current_pulls + count), now, total_cost, str(user_id))

            return {"success": True, "amount": count * GEMS_PER_PULL}

        except Exception as e:
            # This ensures that if ANY logic fails, the command receives an error instead of hanging
            return {"success": False, "message": f"An unexpected system error occurred: {str(e)}"}