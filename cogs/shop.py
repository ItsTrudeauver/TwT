import discord
from discord.ext import commands
import datetime
import json
import random
from core.database import get_db_pool, get_user
from core.emotes import Emotes

# --- CONFIGURATION ---
# Add new items here in the future
STANDARD_ITEMS = [
    {
        "id": "SSR Token",
        "name": "SSR Token",
        "description": "Upgrades an SSR unit by +1 Dupe Level.",
        "price": 1000,
        "currency": "coins",  # Use 'coins' or 'gems'
        "emoji": "<:SSRToken:1464467899346583849>"
    }
    # Example of a future item:
    # {
    #     "id": "Stamina Potion",
    #     "name": "Stamina Potion", 
    #     "description": "Restores 50 Expedition Stamina.",
    #     "price": 100,
    #     "currency": "gems",
    #     "emoji": "🧪"
    # }
]

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
                await conn.execute(
                    "INSERT INTO inventory (user_id, anilist_id, dupe_level) VALUES ($1, $2, 0)",
                    user_id, target_item['anilist_id']
                )
                msg = f"✅ **Purchased!**\n**{target_item['name']}** added to your inventory!"

            # Add discount note
            if discount_active:
                msg += f"\n📉 **Level 30 Discount Applied:** Saved {target_item['base_price'] - final_price:,} {Emotes.GEMS}!"

            await interaction.response.send_message(msg, ephemeral=False)

# --- ITEM SHOP CLASSES ---

class ItemShopView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=60)
        self.bot = bot
        self.add_item(ItemShopDropdown())

class ItemShopDropdown(discord.ui.Select):
    def __init__(self):
        options = []
        for item in STANDARD_ITEMS:
            # Determine emote based on currency
            currency_emote = Emotes.COINS if item['currency'] == 'coins' else Emotes.GEMS
            
            options.append(discord.SelectOption(
                label=f"{item['name']}",
                description=f"Cost: {item['price']:,} {item['currency'].title()}",
                value=item['id'],
                emoji=item['emoji']
            ))
        
        super().__init__(placeholder="Select an item to buy...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        item_id = self.values[0]
        item_data = next((i for i in STANDARD_ITEMS if i['id'] == item_id), None)
        
        if not item_data:
            return await interaction.response.send_message("❌ Error: Item data not found.", ephemeral=True)

        user_id = str(interaction.user.id)
        price = item_data['price']
        currency = item_data['currency'] # 'coins' or 'gems'
        
        pool = await get_db_pool()
        
        # 1. Check Balance
        # We construct the query dynamically based on currency type
        currency_col = "coins" if currency == "coins" else "gacha_gems"
        user_row = await pool.fetchrow(f"SELECT {currency_col} FROM users WHERE user_id = $1", user_id)
        
        if not user_row:
             return await interaction.response.send_message("❌ You are not registered.", ephemeral=True)

        balance = user_row[currency_col]
        
        if balance < price:
            currency_emote = Emotes.COINS if currency == "coins" else Emotes.GEMS
            return await interaction.response.send_message(f"❌ You need **{price:,} {currency_emote}** to buy this.", ephemeral=True)

        # 2. Process Transaction
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Deduct Currency
                await conn.execute(f"UPDATE users SET {currency_col} = {currency_col} - $1 WHERE user_id = $2", price, user_id)
                
                # Add Item
                await conn.execute("""
                    INSERT INTO user_items (user_id, item_id, quantity) 
                    VALUES ($1, $2, 1)
                    ON CONFLICT (user_id, item_id) 
                    DO UPDATE SET quantity = user_items.quantity + 1
                """, user_id, item_id)
        
        await interaction.response.send_message(f"✅ Purchased **{item_data['name']}** for **{price:,}**!", ephemeral=False)

class Shop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.RATE_UP_IDS = [] 

    async def _get_shop_rotation(self):
        """Fetches or Generates today's shop."""
        today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
        pool = await get_db_pool()
        
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT items FROM daily_shop WHERE date = $1", today)
            if row:
                return json.loads(row['items'])
            
            all_chars = await conn.fetch("SELECT anilist_id, name, rarity, image_url FROM characters_cache")
            if not all_chars: return [] 

            ssr_pool = [dict(c) for c in all_chars if c['rarity'] == 'SSR']
            sr_pool = [dict(c) for c in all_chars if c['rarity'] == 'SR']
            r_pool = [dict(c) for c in all_chars if c['rarity'] == 'R']

            shop_items = []
            def safe_sample(pool, k): return random.sample(pool, min(len(pool), k))

            shop_items.extend(safe_sample(ssr_pool, 2))
            shop_items.extend(safe_sample(sr_pool, 3))
            shop_items.extend(safe_sample(r_pool, 5))

            final_shop = []
            for item in shop_items:
                price = 1000 
                if item['rarity'] == 'SR': price = 20000
                elif item['rarity'] == 'SSR': price = 100000
                
                if item['anilist_id'] in self.RATE_UP_IDS:
                    price = int(price * 1.2)
                    item['rate_up'] = True
                else:
                    item['rate_up'] = False

                item['base_price'] = price
                final_shop.append(item)

            await conn.execute(
                "INSERT INTO daily_shop (date, items) VALUES ($1, $2) ON CONFLICT (date) DO NOTHING",
                today, json.dumps(final_shop)
            )
            return final_shop

    @commands.command(name="shop")
    async def view_shop(self, ctx):
        """Opens the Daily Character Shop."""
        items = await self._get_shop_rotation()
        if not items:
            return await ctx.reply("⚠️ The shop is currently empty.")

        user = await get_user(ctx.author.id)
        user_level = user.get('team_level', 1)
        discount = user_level >= 30
        
        embed = discord.Embed(
            title=f"🛒 Daily Character Shop",
            description=f"**Date:** {datetime.datetime.utcnow().strftime('%Y-%m-%d')}\n"
                        f"**Your Balance:** {user['gacha_gems']:,} {Emotes.GEMS}",
            color=discord.Color.gold()
        )
        
        if discount:
            embed.add_field(name="🌟 Platinum Member", value="You are **Level 30+**! All items are **25% OFF**.", inline=False)

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

        view = ShopView(items, self.bot)
        await ctx.reply(embed=embed, view=view)

    @commands.command(name="itemshop", aliases=["ishop", "items_shop"])
    async def view_item_shop(self, ctx):
        """Opens the Item Shop (Coins & Special Items)."""
        pool = await get_db_pool()
        user = await pool.fetchrow("SELECT coins, gacha_gems FROM users WHERE user_id = $1", str(ctx.author.id))
        
        coins = user['coins'] if user else 0
        gems = user['gacha_gems'] if user else 0

        embed = discord.Embed(title="🎒 Item Shop", color=0x9B59B6)
        embed.description = (
            f"**Your Wallet:**\n"
            f"{Emotes.COINS} Coins: `{coins:,}`\n"
            f"{Emotes.GEMS} Gems: `{gems:,}`\n"
            f"────────────────"
        )

        for item in STANDARD_ITEMS:
            currency_emote = Emotes.COINS if item['currency'] == 'coins' else Emotes.GEMS
            embed.add_field(
                name=f"{item['emoji']} {item['name']}",
                value=f"**Cost:** {item['price']:,} {currency_emote}\n*{item['description']}*",
                inline=False
            )
        
        embed.set_footer(text="Select an item below to purchase instantly.")
        view = ItemShopView(self.bot)
        await ctx.reply(embed=embed, view=view)

    @commands.command(name="buy_token")
    async def buy_ssr_token(self, ctx):
        """Quick command to buy an SSR Token."""
        # Find token data in standard items
        token_data = next((i for i in STANDARD_ITEMS if i['id'] == 'SSR Token'), None)
        
        if not token_data:
            return await ctx.reply("❌ SSR Token is currently not available.")
            
        price = token_data['price']
        
        pool = await get_db_pool()
        user = await pool.fetchrow("SELECT coins FROM users WHERE user_id = $1", str(ctx.author.id))
        if not user or user['coins'] < price:
            return await ctx.reply(f"❌ You need **{price:,} {Emotes.COINS}** to buy an SSR Token. (Current: {user['coins'] if user else 0})")

        async with pool.acquire() as conn:
            async with conn.transaction():
                # Deduct Coins
                await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", price, str(ctx.author.id))
                
                # Upsert the item
                await conn.execute("""
                    INSERT INTO user_items (user_id, item_id, quantity) 
                    VALUES ($1, 'SSR Token', 1)
                    ON CONFLICT (user_id, item_id) 
                    DO UPDATE SET quantity = user_items.quantity + 1
                """, str(ctx.author.id))
                
        await ctx.reply(f"✅ Purchased **1 SSR Token** for {price:,} {Emotes.COINS}!\nUse it with `!use_token <InventoryID>`.")

async def setup(bot):
    await bot.add_cog(Shop(bot))