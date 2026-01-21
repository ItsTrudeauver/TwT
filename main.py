import discord
import os
import asyncio
from discord.ext import commands
from dotenv import load_dotenv
load_dotenv()

TOKEN = os.getenv('DISCORD_TOKEN')
PREFIX = os.getenv('COMMAND_PREFIX', '!')
from core.database import init_db  # Import your new Supabase init function
from aiohttp import web

# 1. Load Secrets


# 2. Setup Bot
intents = discord.Intents.all()
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# 3. Simple Health Check for Render
# This tells Render "I am alive" so it doesn't shut down the bot.
async def health_check(request):
    return web.Response(text="Stardust is Online!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    # Render provides the PORT variable automatically
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"📡 Health check server live on port {port}")

@bot.event
async def on_ready():
    print("--------------------------------------------------")
    print(f"✨ Project Stardust is Online as: {bot.user}")
    print("--------------------------------------------------")

# 4. Main Startup Logic
async def main():
    if not TOKEN:
        print("❌ CRITICAL ERROR: DISCORD_TOKEN not found.")
        return

    # Start the web server in the background for Render
    asyncio.create_task(start_web_server())

    # Initialize Supabase tables
    print("🗄️  Connecting to Supabase...")
    await init_db()

    # Load Cogs
    print("⚙️  Loading Modules...")
    if os.path.exists('./cogs'):
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                try:
                    await bot.load_extension(f'cogs.{filename[:-3]}')
                    print(f"   ✅ Loaded: {filename}")
                except Exception as e:
                    print(f"   ❌ Failed to load {filename}: {e}")

    # Start Bot
    async with bot:
        await bot.start(TOKEN)

# 5. Run the Script
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("👋 Shutting down...")