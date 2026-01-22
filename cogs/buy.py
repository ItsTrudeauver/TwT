import discord
from discord.ext import commands
from core.economy import Economy

class Buy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="buy")
    async def buy_gems(self, ctx, amount: int):
        """
        Exchange Unbelievaboat credits for Gacha Gems.
        Usage: !buy <amount_of_pulls>
        """
        # Ensure the command is used in a guild
        if not ctx.guild:
            return await ctx.reply("❌ This command must be used in a server.")

        loading = await ctx.reply(f"🔄 Processing purchase for {amount} pull(s)...")

        # The Economy.buy_pulls_with_boat handles API calls and DB updates
        result = await Economy.buy_pulls_with_boat(
            user_id=ctx.author.id, 
            guild_id=ctx.guild.id, 
            count=amount
        )

        if result["success"]:
            embed = discord.Embed(
                title="✅ Purchase Successful",
                description=f"You successfully bought **{result['amount']:,} Gems**!",
                color=discord.Color.green()
            )
            embed.set_footer(text="Gems have been added to your gacha balance.")
            await loading.edit(content=None, embed=embed)
        else:
            # Displays the specific error (Daily limit reached or Insufficient funds)
            await loading.edit(content=f"❌ **Purchase Failed:** {result['message']}")

async def setup(bot):
    await bot.add_cog(Buy(bot))