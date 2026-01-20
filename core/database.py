import asyncpg
import os
import json

# Fetch this from your Render Environment Variables
DATABASE_URL = os.getenv("DATABASE_URL")

# Global pool variable to be initialized once
_pool = None

async def get_db_pool():
    """Returns the existing connection pool or creates a new one if it doesn't exist."""
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
    """
    Initializes the database tables in Supabase.
    """
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        # 1. USERS TABLE
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                gacha_gems INTEGER DEFAULT 0,
                boat_credits_spent INTEGER DEFAULT 0,
                pity_counter INTEGER DEFAULT 0,
                luck_boost_stacks INTEGER DEFAULT 0,
                last_daily_exchange TIMESTAMP,
                last_expedition_claim TIMESTAMP
            )
        """)

        # 2. INVENTORY TABLE
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id SERIAL PRIMARY KEY,
                user_id TEXT REFERENCES users(user_id),
                anilist_id INTEGER,
                obtained_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_locked BOOLEAN DEFAULT FALSE
            )
        """)

        # 3. TEAMS TABLE
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS teams (
                user_id TEXT PRIMARY KEY REFERENCES users(user_id),
                slot_1 INTEGER DEFAULT NULL,
                slot_2 INTEGER DEFAULT NULL,
                slot_3 INTEGER DEFAULT NULL,
                slot_4 INTEGER DEFAULT NULL,
                slot_5 INTEGER DEFAULT NULL,
                team_name TEXT DEFAULT 'New Team'
            )
        """)

        # 4. CHARACTERS CACHE
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS characters_cache (
                anilist_id INTEGER PRIMARY KEY,
                name TEXT,
                image_url TEXT,
                rarity_override TEXT DEFAULT NULL,
                base_power INTEGER DEFAULT 0,
                squash_resistance FLOAT DEFAULT 0.0,
                ability_tags JSONB DEFAULT '[]'::jsonb
            )
        """)
    print("✅ Supabase Database tables verified.")

async def get_user(user_id):
    """Fetches user data, creating a new row if they don't exist using the pool."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", str(user_id))
        if row:
            return dict(row)
        else:
            await conn.execute("INSERT INTO users (user_id) VALUES ($1)", str(user_id))
            new_row = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", str(user_id))
            return dict(new_row)

async def add_currency(user_id, amount):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, gacha_gems) VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE 
            SET gacha_gems = users.gacha_gems + $2
        """, str(user_id), amount)

async def add_character_to_inventory(user_id, anilist_id):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO inventory (user_id, anilist_id) VALUES ($1, $2)",
            str(user_id), anilist_id)

async def batch_add_to_inventory(user_id, character_ids):
    """Optimized: Adds multiple characters to inventory in one trip."""
    pool = await get_db_pool()
    data = [(str(user_id), cid) for cid in character_ids]
    async with pool.acquire() as conn:
        await conn.executemany(
            "INSERT INTO inventory (user_id, anilist_id) VALUES ($1, $2)",
            data
        )

async def cache_character(anilist_id, name, image_url, base_power):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO characters_cache (anilist_id, name, image_url, base_power)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT(anilist_id) DO UPDATE SET
                name=EXCLUDED.name,
                image_url=EXCLUDED.image_url,
                base_power=EXCLUDED.base_power
        """, anilist_id, name, image_url, base_power)

async def batch_cache_characters(char_data_list):
    """Optimized: Caches multiple characters in one trip."""
    pool = await get_db_pool()
    # Format data for executemany: (id, name, url, power)
    data = [(c['id'], c['name'], c['image_url'], c['favs']) for c in char_data_list]
    async with pool.acquire() as conn:
        await conn.executemany("""
            INSERT INTO characters_cache (anilist_id, name, image_url, base_power)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT(anilist_id) DO UPDATE SET
                name=EXCLUDED.name,
                image_url=EXCLUDED.image_url,
                base_power=EXCLUDED.base_power
        """, data)

async def get_user_inventory_with_details(user_id, sort_by="date"):
    """
    Fetches the full inventory for a user with character details.
    Sorts by: 'date' (pull order), 'power' (base_power), or 'dupes' (frequency).
    """
    pool = await get_db_pool()
    
    # Base query joining inventory and cache
    # We use a subquery to count duplicates (count per anilist_id)
    query = """
        SELECT 
            i.anilist_id, 
            c.name, 
            c.base_power, 
            i.obtained_at,
            COUNT(*) OVER(PARTITION BY i.anilist_id) as dupe_count
        FROM inventory i
        LEFT JOIN characters_cache c ON i.anilist_id = c.anilist_id
        WHERE i.user_id = $1
    """

    if sort_by == "power":
        query += " ORDER BY c.base_power DESC, i.obtained_at DESC"
    elif sort_by == "dupes":
        query += " ORDER BY dupe_count DESC, c.base_power DESC"
    else:  # Default: pull order (newest first)
        query += " ORDER BY i.obtained_at DESC"

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, str(user_id))
        return [dict(row) for row in rows]