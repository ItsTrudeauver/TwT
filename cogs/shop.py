import discord
from discord.ext import commands
import datetime
import json
import random
from core.database import get_db_pool, get_user
from core.emotes import Emotes  # Import Emotes

class ShopView(discord.ui.View):
    def __init__(self, shop_items, bot):
        super().__init__(timeout=60)
        self.shop_items = shop_items
        self.bot = bot
        self.add_item(ShopDropdown(shop_items))

class ShopDropdown(discord.ui.Select):
    def __init__(self, shop_items):
        options = []
        for idx, item in enumerate(shop_items):
            # We use the index as the unique value to identify the item
            options.append(discord.SelectOption(
                label=f"{item['name']} ({item['rarity']})",
                description=f"Base Cost: {item['base_price']:,} Gems",
                value=str(idx),
                emoji="🪙"
            ))
        
        super().__init__(placeholder="Select a character to buy...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        # 1. Identify Item
        item_index = int(self.values[0])
        target_item = self.view.shop_items[item_index]
        user_id = str(interaction.user.id)
        
        # 2. Fetch User Data (Balance & Level)
        pool = await get_db_pool()
        user_row = await pool.fetchrow("SELECT gacha_gems, team_level FROM users WHERE user_id = $1", user_id)
        
        if not user_row:
            return await interaction.response.send_message("❌ You are not registered! Type `!start` first.", ephemeral=True)
            
        gems = user_row['gacha_gems']
        level = user_row['team_level'] if user_row['team_level'] else 1
        
        # 3. Calculate Personalized Price
        # Level 30 Perk: -25% Cost
        discount_active = level >= 30
        final_price = int(target_item['base_price'] * (0.75 if discount_active else 1.0))
        
        # 4. Check Funds
        if gems < final_price:
            missing = final_price - gems
            return await interaction.response.send_message(f"❌ You cannot afford this!\nCost: **{final_price:,}** (Short: {missing:,})", ephemeral=True)
            
        # 5. Process Transaction
        async with pool.acquire() as conn:
            # Check Inventory for Dupe
            existing = await conn.fetchrow(
                "SELECT id, dupe_level FROM inventory WHERE user_id = $1 AND anilist_id = $2", 
                user_id, target_item['anilist_id']
            )
            
            # Deduct Gems
            await conn.execute("UPDATE users SET gacha_gems = gacha_gems - $1 WHERE user_id = $2", final_price, user_id)
            
            msg = ""
            if existing:
                new_dupe = existing['dupe_level'] + 1
                await conn.execute("UPDATE inventory SET dupe_level = $1 WHERE id = $2", new_dupe, existing['id'])
                msg = f"✅ **Purchased!**\n**{target_item['name']}** upgraded to Dupe Level **{new_dupe}**!"
            else:
                # FIXED: Removed 'level' and 'xp', added 'dupe_level' to match database schema
                await conn.execute(
                    "INSERT INTO inventory (user_id, anilist_id, dupe_level) VALUES ($1, $2, 0)",
                    user_id, target_item['anilist_id']
                )
                msg = f"✅ **Purchased!**\n**{target_item['name']}** added to your inventory!"

            # Add discount note
            if discount_active:
                msg += f"\n📉 **Level 30 Discount Applied:** Saved {target_item['base_price'] - final_price:,} Gems!"

            await interaction.response.send_message(msg, ephemeral=False)

class Shop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.RATE_UP_IDS = [] # Add specific IDs here if you want manual rate-ups

    async def _get_shop_rotation(self):
        """Fetches or Generates today's shop."""
        today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
        pool = await get_db_pool()
        
        async with pool.acquire() as conn:
            # 1. Check if shop exists for today
            row = await conn.fetchrow("SELECT items FROM daily_shop WHERE date = $1", today)
            
            if row:
                return json.loads(row['items'])
            
            # 2. Generate New Shop
            all_chars = await conn.fetch("SELECT anilist_id, name, rarity, image_url FROM characters_cache")
            
            if not all_chars:
                return [] # Database might be empty

            ssr_pool = [dict(c) for c in all_chars if c['rarity'] == 'SSR']
            sr_pool = [dict(c) for c in all_chars if c['rarity'] == 'SR']
            r_pool = [dict(c) for c in all_chars if c['rarity'] == 'R']

            shop_items = []
            
            # Helper to safely sample
            def safe_sample(pool, k):
                return random.sample(pool, min(len(pool), k))

            shop_items.extend(safe_sample(ssr_pool, 2)) # 2 SSRs
            shop_items.extend(safe_sample(sr_pool, 3))  # 3 SRs
            shop_items.extend(safe_sample(r_pool, 5))   # 5 Rs

            # Calculate Base Prices
            final_shop = []
            for item in shop_items:
                price = 1000 # Default R
                if item['rarity'] == 'SR': price = 20000
                elif item['rarity'] == 'SSR': price = 100000
                
                # Manual Rate Up (+20%)
                if item['anilist_id'] in self.RATE_UP_IDS:
                    price = int(price * 1.2)
                    item['rate_up'] = True
                else:
                    item['rate_up'] = False

                item['base_price'] = price
                final_shop.append(item)

            # Save to DB
            await conn.execute(
                "INSERT INTO daily_shop (date, items) VALUES ($1, $2) ON CONFLICT (date) DO NOTHING",
                today, json.dumps(final_shop)
            )
            return final_shop

    @commands.command(name="shop")
    async def view_shop(self, ctx):
        """Opens the Daily Shop with a Buy Menu."""
        items = await self._get_shop_rotation()
        
        if not items:
            return await ctx.reply("⚠️ The shop is currently empty (No characters found in cache).")

        user = await get_user(ctx.author.id)
        user_level = user.get('team_level', 1)
        discount = user_level >= 30
        
        # Build Embed
        embed = discord.Embed(
            title=f"🛒 Daily Character Shop",
            description=f"**Date:** {datetime.datetime.utcnow().strftime('%Y-%m-%d')}\n"
                        f"**Your Balance:** {user['gacha_gems']:,} {Emotes.GEMS}",
            color=discord.Color.gold()
        )
        
        if discount:
            embed.add_field(
                name="🌟 Platinum Member", 
                value="You are **Level 30+**! All items are **25% OFF**.", 
                inline=False
            )

        list_str = ""
        for item in items:
            price = item['base_price']
            price_display = f"{price:,}"
            
            if discount:
                discounted = int(price * 0.75)
                price_display = f"~~{price:,}~~ **{discounted:,}**"

            rate_up = "🔥" if item.get('rate_up') else ""
            list_str += f"**{item['name']}** `[{item['rarity']}]` {rate_up} — {Emotes.GEMS} {price_display}\n"

        embed.add_field(name="Today's Selection", value=list_str if list_str else "None", inline=False)
        embed.set_footer(text="Use the dropdown menu below to purchase.")

        # Attach Dropdown View
        view = ShopView(items, self.bot)
        await ctx.reply(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(Shop(bot))