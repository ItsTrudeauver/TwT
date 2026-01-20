import asyncpg
import os
import json

# Fetch this from your Render Environment Variables
DATABASE_URL = os.getenv("DATABASE_URL")

async def get_db_connection():
    """Helper to create a connection to Supabase/Postgres."""
    return await asyncpg.connect(DATABASE_URL)

async def init_db():
    """
    Initializes the database tables in Supabase.
    """
    conn = await get_db_connection()
    try:
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
    finally:
        await conn.close()

async def get_user(user_id):
    """Fetches user data, creating a new row if they don't exist."""
    conn = await get_db_connection()
    try:
        row = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", str(user_id))
        if row:
            return dict(row)
        else:
            await conn.execute("INSERT INTO users (user_id) VALUES ($1)", str(user_id))
            new_row = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", str(user_id))
            return dict(new_row)
    finally:
        await conn.close()

async def add_currency(user_id, amount):
    conn = await get_db_connection()
    try:
        await conn.execute("""
            INSERT INTO users (user_id, gacha_gems) VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE 
            SET gacha_gems = users.gacha_gems + $2
        """, str(user_id), amount)
    finally:
        await conn.close()

async def add_character_to_inventory(user_id, anilist_id):
    conn = await get_db_connection()
    try:
        await conn.execute(
            "INSERT INTO inventory (user_id, anilist_id) VALUES ($1, $2)",
            str(user_id), anilist_id)
    finally:
        await conn.close()

async def cache_character(anilist_id, name, image_url, base_power):
    conn = await get_db_connection()
    try:
        await conn.execute("""
            INSERT INTO characters_cache (anilist_id, name, image_url, base_power)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT(anilist_id) DO UPDATE SET
                name=EXCLUDED.name,
                image_url=EXCLUDED.image_url,
                base_power=EXCLUDED.base_power
        """, anilist_id, name, image_url, base_power)
    finally:
        await conn.close()