import asyncio
from core.database import init_db

# This script manually triggers the database creation
if __name__ == "__main__":
    try:
        asyncio.run(init_db())
        print("🎉 Success! 'data/stardust.db' has been created.")
    except Exception as e:
        print(f"❌ Error: {e}")