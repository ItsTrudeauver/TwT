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
        "UPSTART": Achievement(
        id="UPSTART",
        name="Upstart",
        description="Own 5 unique SSR characters.",
        badge_emote=Emotes.UPSTART,
        gem_reward=1000,
        coin_reward=0,
        check_sql="""
            SELECT (SELECT COUNT(*) FROM inventory i
            JOIN characters_cache c ON i.anilist_id = c.anilist_id
            WHERE i.user_id = $1 AND c.rarity = 'SSR') >= 5
        """
    ),

    "THE_ELITE": Achievement(
        id="THE_ELITE",
        name="The Elite",
        description="Own 10 unique SSR characters.",
        badge_emote=Emotes.ELITE,
        gem_reward=5000,
        coin_reward=0,
        check_sql="""
            SELECT (SELECT COUNT(*) FROM inventory i
            JOIN characters_cache c ON i.anilist_id = c.anilist_id
            WHERE i.user_id = $1 AND c.rarity = 'SSR') >= 10
        """
    ),

    "SUPERNOVAE": Achievement(
        id="SUPERNOVAE",
        name="Supernovae",
        description="Own 50 unique SSR characters.",
        badge_emote=Emotes.SUPERNOVAE,
        gem_reward=20000,
        coin_reward=0,
        check_sql="""
            SELECT (SELECT COUNT(*) FROM inventory i
            JOIN characters_cache c ON i.anilist_id = c.anilist_id
            WHERE i.user_id = $1 AND c.rarity = 'SSR') >= 50
        """
    ),

    "ARMY_OF_MANY": Achievement(
        id="ARMY_OF_MANY",
        name="Army of Many",
        description="Own 500 total units including dupes.",
        badge_emote=Emotes.ARMY,
        gem_reward=5000,
        coin_reward=0,
        check_sql="""
            SELECT (SELECT COALESCE(SUM(dupe_level + 1), 0)
            FROM inventory WHERE user_id = $1) >= 500
        """
    ),

    "PERFECT_COPY": Achievement(
        id="PERFECT_COPY",
        name="Perfect Copy",
        description="Reach Dupe Level 10 on any character.",
        badge_emote=Emotes.PERFECT_COPY,
        gem_reward=5000,
        coin_reward=0,
        check_sql="""
            SELECT EXISTS(SELECT 1 FROM inventory WHERE user_id = $1 AND dupe_level >= 10)
        """
    ),
    
    "PRISMATIC_TRANSCENDENCE": Achievement(
        id="PRISMATIC_TRANSCENDENCE",
        name="Prismatic Transcendence",
        description="Reach Dupe Level 10 on any SSR character.",
        badge_emote=Emotes.PRISMATIC,
        gem_reward=50000,
        coin_reward=1000,
        check_sql="""
            SELECT EXISTS (
            SELECT 1
            FROM inventory i
            JOIN characters_cache c ON i.anilist_id = c.anilist_id
            WHERE i.user_id = $1
            AND i.dupe_level >= 10
            AND c.rarity = 'SSR'
        );
        """
    ),

    "DEEP_POCKETS": Achievement(
        id="DEEP_POCKETS",
        name="Deep Pockets",
        description="Reach 300 Spark Points on a single banner.",
        badge_emote=Emotes.DEEP_POCKETS,
        gem_reward=10000,
        coin_reward=0,
        check_sql="""
            SELECT (SELECT banner_points FROM users WHERE user_id = $1) >= 300
        """
    ),

    "NOVICE_GAMBLER": Achievement(
        id="NOVICE_GAMBLER",
        name="Novice Gambler",
        description="Perform 100 total pulls",
        badge_emote=Emotes.NOVICE_GAMBER,
        gem_reward=1000,
        coin_reward=0,
        check_sql="""
            SELECT (SELECT total_pulls FROM users WHERE user_id = $1) >= 100
        """
    ),

    "BIG_PLAYER": Achievement(
        id="BIG_PLAYER",
        name="Big Player",
        description="Perform 500 pulls",
        badge_emote=Emotes.BIG_PLAYER,
        gem_reward=5000,
        coin_reward=0,
        check_sql="""
            SELECT (SELECT total_pulls FROM users WHERE user_id = $1) >= 500
        """
    ),

    "THOUSAND_PULL_CLUB": Achievement(
        id="THOUSAND_PULL_CLUB",
        name="Thousand-Pull Club",
        description="Perform 1,000 total pulls",
        badge_emote=Emotes.ATHOUSANDCLUB,
        gem_reward=10000,
        coin_reward=0,
        check_sql="""
            SELECT (SELECT total_pulls FROM users WHERE user_id = $1) >= 1000
        """
    ),

    # --- Section 2: Bounties & Bosses ---
    "R_TAKEDOWN": Achievement(
        id="R_TAKEDOWN",
        name="R-Tier Takedown",
        description="Defeat an R-Tier Bounty.",
        badge_emote=Emotes.R_TAKEDOWN,
        gem_reward=500,
        coin_reward=0,
        check_sql="""
            SELECT EXISTS(SELECT 1 FROM boss_kills WHERE user_id = $1 AND boss_id = 'BOUNTY_R')
        """
    ),

    "SR_TAKEDOWN": Achievement(
        id="SR_TAKEDOWN",
        name="SR-Tier Takedown",
        description="Defeat an SR-Tier Bounty.",
        badge_emote=Emotes.SR_TAKEDOWN,
        gem_reward=2000,
        coin_reward=0,
        check_sql="""
            SELECT EXISTS(SELECT 1 FROM boss_kills WHERE user_id = $1 AND boss_id = 'BOUNTY_SR')
        """
    ),

    "SSR_TAKEDOWN": Achievement(
        id="SSR_TAKEDOWN",
        name="SSR-Tier Takedown",
        description="Defeat an SSR-Tier Bounty.",
        badge_emote=Emotes.SSR_TAKEDOWN,
        gem_reward=10000,
        coin_reward=0,
        check_sql="""
            SELECT EXISTS(SELECT 1 FROM boss_kills WHERE user_id = $1 AND boss_id = 'BOUNTY_SSR')
        """
    ),

    "UR_TAKEDOWN": Achievement(
        id="UR_TAKEDOWN",
        name="UR-Tier Takedown",
        description="Defeat a UR-Tier Bounty.",
        badge_emote=Emotes.UR_TAKEDOWN,
        gem_reward=25000,
        coin_reward=0,
        check_sql="""
            SELECT EXISTS(SELECT 1 FROM boss_kills WHERE user_id = $1 AND boss_id = 'BOUNTY_UR')
        """
    ),

    "VETERAN_HUNTER": Achievement(
        id="VETERAN_HUNTER",
        name="Veteran Hunter",
        description="Complete 100 total Bounties.",
        badge_emote=Emotes.VETERAN_HUNTER,
        gem_reward=10000,
        coin_reward=0,
        check_sql="""
            SELECT (SELECT total_bounties FROM users WHERE user_id = $1) >= 100
        """
    ),

    # --- Section 3: Power & Team Progression ---
    "FORMIDABLE_TEAM": Achievement(
        id="FORMIDABLE_TEAM",
        name="Formidable Team",
        description="Reach 50,000 Team Power.",
        badge_emote=Emotes.FORMIDABLE_TEAM,
        gem_reward=5000,
        coin_reward=0,
        check_sql="""
            SELECT (SELECT SUM(FLOOR(c.true_power * (1 + (i.dupe_level * 0.05))))
            FROM teams t
            JOIN inventory i ON i.id IN (t.slot_1, t.slot_2, t.slot_3, t.slot_4, t.slot_5)
            JOIN characters_cache c ON i.anilist_id = c.anilist_id
            WHERE t.user_id = $1) >= 50000
        """
    ),

    "TITAN_SQUAD": Achievement(
        id="TITAN_SQUAD",
        name="Titan Squad",
        description="Reach 100,000 Team Power.",
        badge_emote=Emotes.TITAN_TEAM,
        gem_reward=20000,
        coin_reward=0,
        check_sql="""
            SELECT (SELECT SUM(FLOOR(c.true_power * (1 + (i.dupe_level * 0.05))))
            FROM teams t
            JOIN inventory i ON i.id IN (t.slot_1, t.slot_2, t.slot_3, t.slot_4, t.slot_5)
            JOIN characters_cache c ON i.anilist_id = c.anilist_id
            WHERE t.user_id = $1) >= 100000
        """
    ),

    "BOND_INITIATE": Achievement(
        id="BOND_INITIATE",
        name="Bond Initiate",
        description="Reach Bond Level 10 with any character.",
        badge_emote=Emotes.BOND_INITIATE,
        gem_reward=1000,
        coin_reward=0,
        check_sql="""
            SELECT EXISTS(SELECT 1 FROM inventory WHERE user_id = $1 AND bond_level >= 10)
        """
    ),

    "SOUL_BOUND": Achievement(
        id="SOUL_BOUND",
        name="Soul Bound",
        description="Reach Bond Level 50 with any character.",
        badge_emote=Emotes.SOUL_BOUND,
        gem_reward=10000,
        coin_reward=0,
        check_sql="""
            SELECT EXISTS(SELECT 1 FROM inventory WHERE user_id = $1 AND bond_level >= 50)
        """
    ),

    "COMMANDING_OFFICER": Achievement(
        id="COMMANDING_OFFICER",
        name="Commanding Officer",
        description="Reach Team Level 10.",
        badge_emote=Emotes.COMMAND_OFFICER,
        gem_reward=5000,
        coin_reward=0,
        check_sql="""
            SELECT (SELECT team_level FROM users WHERE user_id = $1) >= 10
        """
    ),

    "SUPREME_COMMANDER": Achievement(
        id="SUPREME_COMMANDER",
        name="Supreme Commander",
        description="Reach Team Level 50.",
        badge_emote=Emotes.SUPREME_COMMANDER,
        gem_reward=50000,
        coin_reward=0,
        check_sql="""
            SELECT (SELECT team_level FROM users WHERE user_id = $1) >= 50
        """
    ),

    "GOLDEN_VANGUARD": Achievement(
        id="GOLDEN_VANGUARD",
        name="Golden Vanguard",
        description="Active team consisting of 5 SSRs.",
        badge_emote=Emotes.GOLDEN_VANGUARD,
        gem_reward=5000,
        coin_reward=0,
        check_sql="""
            SELECT (SELECT COUNT(*) FROM teams t
            JOIN inventory i ON i.id IN (t.slot_1, t.slot_2, t.slot_3, t.slot_4, t.slot_5)
            JOIN characters_cache c ON i.anilist_id = c.anilist_id
            WHERE t.user_id = $1 AND c.rarity = 'SSR') = 5
        """
    ),

    # --- Section 4: Expeditions & Scrapping ---
    "FIRST_VOYAGE": Achievement(
        id="FIRST_VOYAGE",
        name="First Voyage",
        description="Complete your first Expedition.",
        badge_emote=Emotes.FIRST_VOYAGE,
        gem_reward=500,
        coin_reward=0,
        check_sql="""
            SELECT EXISTS(SELECT 1 FROM expeditions WHERE user_id = $1 AND last_claim IS NOT NULL)
        """
    ),

    "TREASURE_HUNTER": Achievement(
        id="TREASURE_HUNTER",
        name="Treasure Hunter",
        description="Earn 500,000 total Gems from Expeditions.",
        badge_emote=Emotes.TREASURE_HUNTER,
        gem_reward=15000,
        coin_reward=0,
        check_sql="""
            SELECT (SELECT expedition_gems_total FROM users WHERE user_id = $1) >= 500000
        """
    ),

    "EFFICIENT_SCRAPPER": Achievement(
        id="EFFICIENT_SCRAPPER",
        name="Efficient Scrapper",
        description="Scrap 100 R-rank characters.",
        badge_emote=Emotes.EFFICIENT_SCRAPPER,
        gem_reward=5000,
        coin_reward=0,
        check_sql="""
            SELECT (SELECT total_scrapped FROM users WHERE user_id = $1) >= 100
        """
    ),

    "SAFE_KEEPING": Achievement(
        id="SAFE_KEEPING",
        name="Safe Keeping",
        description="Lock 10 characters in your inventory.",
        badge_emote=Emotes.KEEPSAKE,
        gem_reward=1000,
        coin_reward=0,
        check_sql="""
            SELECT (SELECT COUNT(*) FROM inventory WHERE user_id = $1 AND is_locked = TRUE) >= 10
        """
    ),

    # --- Section 5: Economy & Activity ---
    "COIN_COLLECTOR": Achievement(
        id="COIN_COLLECTOR",
        name="Coin Collector",
        description="Accumulate a balance of 5,000 Coins.",
        badge_emote=Emotes.COIN_COLLECTOR,
        gem_reward=2000,
        coin_reward=0,
        check_sql="""
            SELECT (SELECT coins FROM users WHERE user_id = $1) >= 5000
        """
    ),

    "WEEKLY_HABIT": Achievement(
        id="WEEKLY_HABIT",
        name="Weekly Habit",
        description="Claim !checkin reward 7 days in a row.",
        badge_emote=Emotes.WEEKLY_HABIT,
        gem_reward=5000,
        coin_reward=0,
        check_sql="""
            SELECT (SELECT checkin_streak FROM users WHERE user_id = $1) >= 7
        """
    ),

    "MONTHLY_DEVOTION": Achievement(
        id="MONTHLY_DEVOTION",
        name="Monthly Devotion",
        description="Claim !checkin reward 30 days in a row.",
        badge_emote=Emotes.MONTHLY_DEVOTION,
        gem_reward=50000,
        coin_reward=0,
        check_sql="""
            SELECT (SELECT checkin_streak FROM users WHERE user_id = $1) >= 30
        """
    ),
    
    "ULTIMATE_BATTLER": Achievement(
        id="ULTIMATE_BATTLER",
        name="Ultimate Battler",
        description="Defeat TwT in a team battle.",
        badge_emote=Emotes.ULTIMATE_BATTLER, # Replace with Emotes.GODSLAYER if defined in core/emotes.py
        gem_reward=50000,
        coin_reward=1000,
        check_sql="SELECT EXISTS(SELECT 1 FROM boss_kills WHERE user_id = $1 AND boss_id = '1463071276036788392')"
    ),
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