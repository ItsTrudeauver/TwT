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
                boat_credits_spent INTEGER DEFAULT 0,
                pity_counter INTEGER DEFAULT 0,
                luck_boost_stacks INTEGER DEFAULT 0,
                last_daily_exchange TIMESTAMP,
                last_expedition_claim TIMESTAMP,
                daily_boat_pulls INTEGER DEFAULT 0,
                last_boat_pull_at TIMESTAMP DEFAULT '1970-01-01',
                has_claimed_starter BOOLEAN DEFAULT FALSE
            )
        """)

        # INVENTORY: Unique ID for every unit owned
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id SERIAL PRIMARY KEY,
                user_id TEXT REFERENCES users(user_id),
                anilist_id INTEGER,
                obtained_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_locked BOOLEAN DEFAULT FALSE
            )
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
                squash_resistance FLOAT DEFAULT 0.0
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

async def batch_add_to_inventory(user_id, character_ids):
    pool = await get_db_pool()
    data = [(str(user_id), cid) for cid in character_ids]
    await pool.executemany("INSERT INTO inventory (user_id, anilist_id) VALUES ($1, $2)", data)

async def batch_cache_characters(chars):
    pool = await get_db_pool()
    data = [(c['id'], c['name'], c['image_url'], c['rarity'], c['page'], c['favs'], c['true_power'], json.dumps(c.get('tags', []))) for c in chars]
    await pool.executemany("""
        INSERT INTO characters_cache (anilist_id, name, image_url, rarity, rank, base_power, true_power, ability_tags)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (anilist_id) DO UPDATE SET true_power = EXCLUDED.true_power
    """, data)

async def get_inventory_details(user_id, sort_by="date"):
    pool = await get_db_pool()
    # Updated to include ID column
    query = """
        SELECT i.id, i.anilist_id, c.name, c.true_power, c.rarity, c.rank, 
               COUNT(*) OVER(PARTITION BY i.anilist_id) as dupe_count
        FROM inventory i
        LEFT JOIN characters_cache c ON i.anilist_id = c.anilist_id
        WHERE i.user_id = $1
    """
    if sort_by == "power": query += " ORDER BY c.true_power DESC"
    else: query += " ORDER BY i.obtained_at DESC"
    
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