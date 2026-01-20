# core/economy.py

import os
import aiohttp
import datetime
from core.database import get_db_pool

# --- CONSTANTS ---
GEMS_PER_PULL = 1000  # 1 Multi = 10,000 Gems
BOAT_COST_PER_PULL = 10_000_000  # 10 Million
MAX_BOAT_PULLS_DAILY = 10
UNBELIEVABOAT_TOKEN = os.getenv("UNBELIEVABOAT_TOKEN")

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
        10M credits = 1 Pull. Max 10 per day.
        """
        if count <= 0 or count > MAX_BOAT_PULLS_DAILY:
            return {"success": False, "message": f"You can only buy 1 to {MAX_BOAT_PULLS_DAILY} pulls."}

        pool = await get_db_pool()
        async with pool.acquire() as conn:
            # Check Daily Limit
            user = await conn.fetchrow("SELECT daily_boat_pulls, last_boat_pull_at FROM users WHERE user_id = $1", str(user_id))
            now = datetime.datetime.utcnow()
            
            # Reset daily counter if it's a new day
            current_pulls = user['daily_boat_pulls'] if user['last_boat_pull_at'].date() == now.date() else 0
            
            if current_pulls + count > MAX_BOAT_PULLS_DAILY:
                return {"success": False, "message": f"Daily limit reached. You have {MAX_BOAT_PULLS_DAILY - current_pulls} pulls left for today."}

            # Unbelievaboat API Call
            total_cost = count * BOAT_COST_PER_PULL
            headers = {"Authorization": UNBELIEVABOAT_TOKEN, "Accept": "application/json"}
            url = f"https://unbelievaboat.com/api/v1/guilds/{guild_id}/users/{user_id}"
            
            async with aiohttp.ClientSession() as session:
                # Deduct money (negative value in the 'bank' or 'cash' field depending on API usage)
                # We use the PATCH method to update balance
                data = {"bank": -total_cost}
                async with session.patch(url, headers=headers, json=data) as resp:
                    if resp.status != 200:
                        error_data = await resp.json()
                        return {"success": False, "message": f"Unbelievaboat Error: {error_data.get('message', 'Insufficient funds in bank.')}"}

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