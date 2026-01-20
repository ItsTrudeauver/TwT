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
    Initializes the database tables and performs schema migrations for new columns.
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
                rarity TEXT DEFAULT 'R',
                rank INTEGER DEFAULT 10000,
                base_power INTEGER DEFAULT 0,
                true_power INTEGER DEFAULT 0,
                squash_resistance FLOAT DEFAULT 0.0,
                ability_tags JSONB DEFAULT '[]'::jsonb
            )
        """)

        # SCHEMA MIGRATION: Force-add columns if the table already existed
        await conn.execute("ALTER TABLE characters_cache ADD COLUMN IF NOT EXISTS true_power INTEGER DEFAULT 0")
        await conn.execute("ALTER TABLE characters_cache ADD COLUMN IF NOT EXISTS rank INTEGER DEFAULT 10000")
        await conn.execute("ALTER TABLE characters_cache ADD COLUMN IF NOT EXISTS rarity TEXT DEFAULT 'R'")

    print("✅ Database schema verified and migrated.")

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

async def batch_add_to_inventory(user_id, character_ids):
    """Optimized: Adds multiple characters to inventory in one trip."""
    pool = await get_db_pool()
    data = [(str(user_id), cid) for cid in character_ids]
    async with pool.acquire() as conn:
        await conn.executemany(
            "INSERT INTO inventory (user_id, anilist_id) VALUES ($1, $2)",
            data
        )

async def batch_cache_characters(char_data_list):
    """Optimized: Caches multiple characters in one trip with full battle logic stats."""
    pool = await get_db_pool()
    # Format data for executemany: (id, name, url, favorites, true_power, rarity, rank)
    data = [
        (c['id'], c['name'], c['image_url'], c['favs'], c['true_power'], c['rarity'], c['page']) 
        for c in char_data_list
    ]
    async with pool.acquire() as conn:
        await conn.executemany("""
            INSERT INTO characters_cache (anilist_id, name, image_url, base_power, true_power, rarity, rank)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT(anilist_id) DO UPDATE SET
                name=EXCLUDED.name,
                image_url=EXCLUDED.image_url,
                base_power=EXCLUDED.base_power,
                true_power=EXCLUDED.true_power,
                rarity=EXCLUDED.rarity,
                rank=EXCLUDED.rank
        """, data)

# core/database.py

async def get_inventory_details(user_id, sort_by="date"):
    pool = await get_db_pool()
    
    query = """
        SELECT 
            i.id,  -- Add this line to fetch the unique inventory ID
            i.anilist_id, 
            c.name, 
            c.true_power, 
            c.rarity,
            c.rank,
            i.obtained_at,
            COUNT(*) OVER(PARTITION BY i.anilist_id) as dupe_count
        FROM inventory i
        LEFT JOIN characters_cache c ON i.anilist_id = c.anilist_id
        WHERE i.user_id = $1
    """

    if sort_by == "power":
        query += " ORDER BY c.true_power DESC, i.obtained_at DESC"
    elif sort_by == "dupes":
        query += " ORDER BY dupe_count DESC, c.true_power DESC"
    else:  # Default: pull order (newest first)
        query += " ORDER BY i.obtained_at DESC"

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, str(user_id))
        return [dict(row) for row in rows]