import discord
import os
import asyncio
from discord.ext import commands
from dotenv import load_dotenv

# 1. Load Environment Variables (Secrets)
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
PREFIX = os.getenv('COMMAND_PREFIX', '!')

# 2. Setup Bot Intents (Permissions)
# We need 'all' intents to see members and read message content
intents = discord.Intents.all()
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# 3. The "On Ready" Event
@bot.event
async def on_ready():
    print("--------------------------------------------------")
    print(f"✨ Project Stardust is Online as: {bot.user}")
    print(f"🆔 Bot ID: {bot.user.id}")
    print(f"🎮 Prefix: {PREFIX}")
    print("--------------------------------------------------")

# 4. The Main Loader
async def main():
    # Check if Token exists first
    if not TOKEN:
        print("❌ CRITICAL ERROR: DISCORD_TOKEN not found in .env file.")
        print("   Please open .env and paste your bot token.")
        return

    # Load all files in the 'cogs' folder
    print("⚙️  Loading Modules...")
    if os.path.exists('./cogs'):
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                try:
                    await bot.load_extension(f'cogs.{filename[:-3]}')
                    print(f"   ✅ Loaded: {filename}")
                except Exception as e:
                    print(f"   ❌ Failed to load {filename}: {e}")
    else:
        print("   ⚠️ Warning: 'cogs' folder not found.")

    print("--------------------------------------------------")
    
    # Start the Bot
    async with bot:
        await bot.start(TOKEN)

if __name__ == '__main__':
    try:
        asyncio.run(main())