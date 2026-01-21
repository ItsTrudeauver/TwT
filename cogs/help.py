import discord
from discord.ext import commands
import os

class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.prefix = os.getenv("COMMAND_PREFIX", "g!")

    @commands.command(name="help")
    async def help_menu(self, ctx, command_name: str = None):
        """
        Displays the help menu.
        Usage: !help [optional: command name]
        """
        
        # 1. SPECIFIC COMMAND HELP (e.g., !help pull)
        if command_name:
            cmd = self.bot.get_command(command_name)
            if not cmd or cmd.hidden:
                return await ctx.send("❌ Command not found.")

            embed = discord.Embed(title=f"📖 Help: {cmd.name.upper()}", color=0xF1C40F)
            
            # Syntax
            params = " ".join([f"[{p}]" for p in cmd.clean_params.keys()])
            embed.add_field(name="Usage", value=f"`{self.prefix}{cmd.name} {params}`", inline=False)
            
            # Description (Docstring)
            desc = cmd.help or "No description provided."
            embed.add_field(name="Description", value=desc, inline=False)
            
            # Aliases
            if cmd.aliases:
                embed.add_field(name="Aliases", value=", ".join([f"`{a}`" for a in cmd.aliases]), inline=False)

            await ctx.send(embed=embed)
            return

        # 2. GENERAL HELP MENU (e.g., !help)
        embed = discord.Embed(
            title="✨ Project Stardust Command Menu",
            description=f"Prefix: `{self.prefix}`\nUse `{self.prefix}help [command]` for more details.",
            color=0x9B59B6
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        # Iterate through all loaded Cogs
        for cog_name, cog in self.bot.cogs.items():
            # Skip the Help cog itself to keep it clean
            if cog_name.lower() == "help":
                continue
                
            # Filter commands (hide owner-only checks usually, but we list them with a tag here)
            command_list = []
            for cmd in cog.get_commands():
                if cmd.hidden:
                    continue
                
                desc = cmd.help.split("\n")[0] if cmd.help else "No description."
                if len(desc) > 30: desc = desc[:30] + "..."
                
                # Check for Admin checks (naive check)
                is_admin = "Owner" if "is_owner" in [x.__qualname__ for x in cmd.checks] else ""
                
                entry = f"`{self.prefix}{cmd.name}`"
                if is_admin: entry += " 🔒"
                
                command_list.append(entry)

            if command_list:
                # Add a field for this Category (Cog)
                embed.add_field(
                    name=f"**{cog_name}**", 
                    value=" ".join(command_list), 
                    inline=False
                )

        # Footer
        embed.set_footer(text="🔒 = Admin Only | [] = Optional Arg")
        await ctx.send(embed=embed)

async def setup(bot):
    # FIXED: removed 'await' from this line
    bot.remove_command("help") 
    await bot.add_cog(Help(bot))    