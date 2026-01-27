# core/achievements.py
from dataclasses import dataclass
from typing import Dict, List, Optional
from core.database import get_db_pool
from core.emotes import Emotes

@dataclass
class Achievement:
    id: str
    name: str
    description: str
    badge_emote: str  # The badge displayed in the profile row
    gem_reward: int = 0
    coin_reward: int = 0
    # SQL logic to check if requirement is met
    check_sql: str = "" 

# --- REGISTRY ---
ACHIEVEMENTS: Dict[str, Achievement] = {
    "FIRST_PULL": Achievement(
        id="FIRST_PULL",
        name="First Contact",
        description="Perform your very first gacha pull.",
        badge_emote=Emotes.FIRST_CONTRACT,
        gem_reward=500,
        check_sql="SELECT EXISTS(SELECT 1 FROM inventory WHERE user_id = $1)"
    ),
    "COLLECTOR_100": Achievement(
        id="COLLECTOR_100",
        name="Centurion",
        description="Own 100 unique characters.",
        badge_emote=Emotes.CENTURION,
        gem_reward=10000,
        coin_reward=100,
        check_sql="SELECT (SELECT COUNT(*) FROM inventory WHERE user_id = $1) >= 100"
    )
}

class AchievementEngine:
    @staticmethod
    async def process_all(user_id: str) -> List[Achievement]:
        """Scans DB for met conditions and grants rewards/badges."""
        user_id = str(user_id)
        pool = await get_db_pool()
        newly_earned = []

        async with pool.acquire() as conn:
            # Get already earned IDs
            earned_rows = await conn.fetch("SELECT achievement_id FROM achievements WHERE user_id = $1", user_id)
            earned_ids = {r['achievement_id'] for r in earned_rows}

            for aid, ach in ACHIEVEMENTS.items():
                if aid in earned_ids: continue

                # Run the self-contained SQL check
                if await conn.fetchval(ach.check_sql, user_id):
                    async with conn.transaction():
                        await conn.execute(
                            "INSERT INTO achievements (user_id, achievement_id, earned_at) VALUES ($1, $2, CURRENT_TIMESTAMP)",
                            user_id, aid
                        )
                        await conn.execute(
                            "UPDATE users SET gacha_gems = gacha_gems + $1, coins = coins + $2 WHERE user_id = $3",
                            ach.gem_reward, ach.coin_reward, user_id
                        )
                    newly_earned.append(ach)
        return newly_earned