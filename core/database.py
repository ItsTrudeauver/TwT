import asyncpg
import os
import json

DATABASE_URL = os.getenv("DATABASE_URL")
_pool = None

async def get_db_pool():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=5,
            max_size=20,
            command_timeout=60
        )
    return _pool

async def init_db():
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS achievements (
                user_id TEXT,
                achievement_id TEXT,
                earned_at TEXT,
                PRIMARY KEY (user_id, achievement_id)
            );
        """)
        
        # USERS: Gems, Pity, Starter Flag, Daily Boat Pulls
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS banners (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                rate_up_ids INTEGER[] NOT NULL,
                rate_up_chance FLOAT DEFAULT 0.5,
                is_active BOOLEAN DEFAULT FALSE,
                end_timestamp BIGINT NOT NULL -- Stores Unix timestamp
            );
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                gacha_gems INTEGER DEFAULT 0,
                boat_credits_spent BIGINT DEFAULT 0,
                pity_counter INTEGER DEFAULT 0,
                luck_boost_stacks INTEGER DEFAULT 0,
                last_daily_exchange TIMESTAMP WITH TIME ZONE,
                last_expedition_claim TIMESTAMP WITH TIME ZONE,
                daily_boat_pulls INTEGER DEFAULT 0,
                last_boat_pull_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                has_claimed_starter BOOLEAN DEFAULT FALSE
            )
        """)

        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS team_level INTEGER DEFAULT 1;")
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS team_xp INTEGER DEFAULT 0;")
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_boat_pulls INTEGER DEFAULT 0;")
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_boat_pull_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;")
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS boat_credits_spent BIGINT DEFAULT 0;")
        
        # NEW: Daily Shop Table
        # Stores the date and a JSON list of {id, price, rarity}
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_shop (
                date TEXT PRIMARY KEY,
                items JSONB
            );
        """)
        
        # Ensure column type is BIGINT even if it was created as INTEGER previously
        await conn.execute("ALTER TABLE users ALTER COLUMN boat_credits_spent TYPE BIGINT;")

        # INVENTORY: Unique ID for every unit owned
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id SERIAL PRIMARY KEY,
                user_id TEXT REFERENCES users(user_id),
                anilist_id INTEGER,
                dupe_level INTEGER DEFAULT 0, -- 0 = base unit, 1 = first dupe, etc.
                obtained_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_locked BOOLEAN DEFAULT FALSE,
                UNIQUE(user_id, anilist_id) -- Prevents multiple rows for the same character
            )
        """)

        # --- MIGRATION GUARDS ---
        # Ensure existing databases get the column and constraint
        await conn.execute("ALTER TABLE inventory ADD COLUMN IF NOT EXISTS dupe_level INTEGER DEFAULT 0;")
        
        # This adds the unique constraint if it doesn't exist (PostgreSQL 9.1+)
        await conn.execute("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'unique_user_character') THEN
                    ALTER TABLE inventory ADD CONSTRAINT unique_user_character UNIQUE (user_id, anilist_id);
                END IF;
            END $$;
        """)

        # TEAMS: Battle squad (5 slots)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS teams (
                user_id TEXT PRIMARY KEY REFERENCES users(user_id),
                slot_1 INTEGER DEFAULT NULL,
                slot_2 INTEGER DEFAULT NULL,
                slot_3 INTEGER DEFAULT NULL,
                slot_4 INTEGER DEFAULT NULL,
                slot_5 INTEGER DEFAULT NULL
            )
        """)

        # EXPEDITIONS: Passive gem earners
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS expeditions (
                user_id TEXT PRIMARY KEY REFERENCES users(user_id),
                slot_ids INTEGER[] DEFAULT '{}',
                start_time TIMESTAMP,
                last_claim TIMESTAMP
            )
        """)

        # CACHE: Stores AniList data to save API calls
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS characters_cache (
                anilist_id INTEGER PRIMARY KEY,
                name TEXT,
                image_url TEXT,
                rarity TEXT DEFAULT 'R',
                rank INTEGER DEFAULT 10000,
                base_power INTEGER DEFAULT 0,
                true_power INTEGER DEFAULT 0,
                ability_tags JSONB DEFAULT '[]'::jsonb,
                squash_resistance FLOAT DEFAULT 0.0,
                is_overridden BOOLEAN DEFAULT FALSE -- Protects manual edits
            )
        """)

        # DAILY TASKS: Tracks progress for Battle/NPC tasks
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_tasks (
                user_id TEXT,
                task_key TEXT,
                progress INTEGER DEFAULT 0,
                is_claimed BOOLEAN DEFAULT FALSE,
                last_updated DATE DEFAULT CURRENT_DATE,
                PRIMARY KEY (user_id, task_key)
            )
        """)

        # GLOBAL SETTINGS: Fairness toggles
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS global_settings (
                key TEXT PRIMARY KEY,
                value_bool BOOLEAN DEFAULT TRUE
            )
        """)

    print("✅ Database initialized successfully.")

async def get_user(user_id):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", str(user_id))
        if row: return dict(row)
        await conn.execute("INSERT INTO users (user_id) VALUES ($1)", str(user_id))
        return dict(await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", str(user_id)))

async def add_currency(user_id, amount):
    pool = await get_db_pool()
    await pool.execute("UPDATE users SET gacha_gems = gacha_gems + $1 WHERE user_id = $2", amount, str(user_id))

async def batch_add_to_inventory(user_id, characters):
    """
    Adds characters to inventory. Increments dupe_level up to 10.
    If already at 10, scraps the character for gems based on rarity.
    Returns total gems gained from scrapping.
    """
    pool = await get_db_pool()
    # Define your scrap values here
    scrap_values = {"R": 200, "SR": 1000, "SSR": 5000}
    total_scrapped_gems = 0
    
    async with pool.acquire() as conn:
        for char in characters:
            cid = char['id']
            rarity = char['rarity']
            
            # Check current status of character in user's inventory
            row = await conn.fetchrow(
                "SELECT dupe_level FROM inventory WHERE user_id = $1 AND anilist_id = $2", 
                str(user_id), cid
            )
            
            if not row:
                # New character: insert with dupe_level 0
                await conn.execute(
                    "INSERT INTO inventory (user_id, anilist_id, dupe_level) VALUES ($1, $2, 0)", 
                    str(user_id), cid
                )
            elif row['dupe_level'] < 10:
                # Under the cap: increment dupe level
                await conn.execute(
                    "UPDATE inventory SET dupe_level = dupe_level + 1 WHERE user_id = $1 AND anilist_id = $2", 
                    str(user_id), cid
                )
            else:
                # At max dupes (10): add to scrap total
                total_scrapped_gems += scrap_values.get(rarity, 0)
        
        # If any characters were scrapped, update the user's gem balance
        if total_scrapped_gems > 0:
            await conn.execute(
                "UPDATE users SET gacha_gems = gacha_gems + $1 WHERE user_id = $2", 
                total_scrapped_gems, str(user_id)
            )
            
    return total_scrapped_gems
async def batch_cache_characters(chars):
    pool = await get_db_pool()
    # Ensure we include the default for is_overridden if needed, 
    # though the DB default FALSE handles it.
    data = [(c['id'], c['name'], c['image_url'], c['rarity'], c['page'], c['favs'], c['true_power'], json.dumps(c.get('tags', []))) for c in chars]
    await pool.executemany("""
        INSERT INTO characters_cache (anilist_id, name, image_url, rarity, rank, base_power, true_power, ability_tags)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (anilist_id) DO UPDATE 
        SET true_power = EXCLUDED.true_power,
            rarity = EXCLUDED.rarity
        WHERE characters_cache.is_overridden = FALSE
    """, data)

async def get_inventory_details(user_id, sort_by="date"):
    pool = await get_db_pool()
    query = """
        SELECT 
            i.id, 
            i.anilist_id, 
            c.name, 
            -- Calculation: Base Power * (1 + (dupe_level * 0.05))
            FLOOR(c.true_power * (1 + (i.dupe_level * 0.05))) as true_power, 
            c.rarity, 
            c.rank, 
            i.dupe_level + 1 as dupe_count -- Displaying total units (base + dupes)
        FROM inventory i
        LEFT JOIN characters_cache c ON i.anilist_id = c.anilist_id
        WHERE i.user_id = $1
    """
    
    if sort_by == "power": 
        query += " ORDER BY true_power DESC"
    else: 
        query += " ORDER BY i.obtained_at DESC"
    
    async with pool.acquire() as conn:
        return [dict(r) for r in await conn.fetch(query, str(user_id))]

# core/database.py

async def scrap_character_from_db(user_id, inventory_id):
    """
    Removes an 'R' rarity character from inventory and adds 200 gems.
    Returns (success_bool, message).
    """
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        # Check if the character exists, belongs to the user, and is rarity 'R'
        query = """
            SELECT i.id FROM inventory i
            JOIN characters_cache c ON i.anilist_id = c.anilist_id
            WHERE i.id = $1 AND i.user_id = $2 AND c.rarity = 'R'
        """
        row = await conn.fetchrow(query, inventory_id, str(user_id))
        if not row:
            return False, "Character not found or is not an 'R' rarity."

        # Execute scrap in a transaction
        async with conn.transaction():
            await conn.execute("DELETE FROM inventory WHERE id = $1", inventory_id)
            await conn.execute("UPDATE users SET gacha_gems = gacha_gems + 200 WHERE user_id = $1", str(user_id))
            
        return True, "Successfully scrapped for 200 Gems!"

# core/database.py

async def mass_scrap_r_rarity(user_id):
    """
    Deletes all unlocked 'R' characters in a user's inventory 
    and rewards 200 gems per character.
    """
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Identify R characters that are NOT locked
            query = """
                DELETE FROM inventory
                WHERE user_id = $1 
                AND is_locked = FALSE
                AND anilist_id IN (
                    SELECT anilist_id FROM characters_cache WHERE rarity = 'R'
                )
                RETURNING id
            """
            deleted_rows = await conn.fetch(query, str(user_id))
            count = len(deleted_rows)
            
            if count > 0:
                reward = count * 200
                await conn.execute(
                    "UPDATE users SET gacha_gems = gacha_gems + $1 WHERE user_id = $2", 
                    reward, str(user_id)
                )
                return count, reward
            return 0, 0

