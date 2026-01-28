from core.database import get_db_pool

class Tracker:
    @staticmethod
    async def increment_pulls(user_id, amount):
        pool = await get_db_pool()
        await pool.execute("UPDATE users SET total_pulls = total_pulls + $1 WHERE user_id = $2", amount, str(user_id))

    @staticmethod
    async def increment_bounty_wins(user_id):
        pool = await get_db_pool()
        await pool.execute("UPDATE users SET total_bounties = total_bounties + 1 WHERE user_id = $1", str(user_id))

    @staticmethod
    async def track_expedition_gain(user_id, gems):
        pool = await get_db_pool()
        await pool.execute("UPDATE users SET expedition_gems_total = expedition_gems_total + $1 WHERE user_id = $2", gems, str(user_id))
    
    @staticmethod
    async def increment_scrapped(user_id, amount):
        pool = await get_db_pool()
        await pool.execute("UPDATE users SET total_scrapped = total_scrapped + $1 WHERE user_id = $2", amount, str(user_id))

    @staticmethod
    async def update_streak(user_id, streak):
        pool = await get_db_pool()
        await pool.execute("UPDATE users SET checkin_streak = $1 WHERE user_id = $2", streak, str(user_id))