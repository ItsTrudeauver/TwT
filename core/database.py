import aiosqlite
import os
import json

# Path relative to where main.py runs
DB_PATH = os.path.join("data", "stardust.db")

async def init_db():
    """
    Initializes the database tables if they do not exist.
    Run this once on bot startup.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        # 1. USERS TABLE
        await db.execute("""
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

        # 2. INVENTORY TABLE (Tracks instances of characters)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                anilist_id INTEGER,
                obtained_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_locked BOOLEAN DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        """)

        # 3. TEAMS TABLE (5 Slots)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS teams (
                user_id TEXT PRIMARY KEY,
                slot_1 INTEGER DEFAULT NULL,
                slot_2 INTEGER DEFAULT NULL,
                slot_3 INTEGER DEFAULT NULL,
                slot_4 INTEGER DEFAULT NULL,
                slot_5 INTEGER DEFAULT NULL,
                team_name TEXT DEFAULT 'New Team',
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        """)

        # 4. CHARACTERS CACHE (Local Metadata to save API calls)
        # We store 'ability_tags' as a JSON string
        await db.execute("""
            CREATE TABLE IF NOT EXISTS characters_cache (
                anilist_id INTEGER PRIMARY KEY,
                name TEXT,
                image_url TEXT,
                rarity_override TEXT DEFAULT NULL,
                base_power INTEGER DEFAULT 0,
                squash_resistance FLOAT DEFAULT 0.0,
                ability_tags TEXT DEFAULT '[]' 
            )
        """)
        
        await db.commit()
        print(f"✅ Database connected and checked at: {DB_PATH}")

# --- HELPER FUNCTIONS ---

async def get_user(user_id):
    """Fetches user data, creating a new row if they don't exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (str(user_id),)) as cursor:
            row = await cursor.fetchone()
            if row:
                return row
            else:
                await db.execute("INSERT INTO users (user_id) VALUES (?)", (str(user_id),))
                await db.commit()
                return await get_user(user_id)

async def add_currency(user_id, amount):
    """Safely adds (or subtracts) Gacha Gems."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Ensure user exists first
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (str(user_id),))
        await db.execute("UPDATE users SET gacha_gems = gacha_gems + ? WHERE user_id = ?", (amount, str(user_id)))
        await db.commit()

async def add_character_to_inventory(user_id, anilist_id):
    """Adds a character instance to the user's inventory."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO inventory (user_id, anilist_id) VALUES (?, ?)", (str(user_id), anilist_id))
        await db.commit()

async def cache_character(anilist_id, name, image_url, base_power):
    """Upserts character metadata into the cache."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO characters_cache (anilist_id, name, image_url, base_power)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(anilist_id) DO UPDATE SET
                name=excluded.name,
                image_url=excluded.image_url,
                base_power=excluded.base_power
        """, (anilist_id, name, image_url, base_power))
        await db.commit()