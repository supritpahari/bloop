import discord
from discord import app_commands
from discord.ext import commands


class Info(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="ping")
    async def ping(self, ctx: commands.Context):
        latency = round(self.bot.latency * 1000, 2)
        await ctx.send(f"Pong! {latency}ms")

    @commands.command(name="echo")
    async def echo(self, ctx: commands.Context, *, message: str):
        await ctx.send(message)

    @commands.command(name="avatar")
    async def avatar(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author
        embed = discord.Embed(
            title=f"{member.display_name}'s avatar",
            color=member.color,
            url=member.display_avatar.url,
        )
        embed.set_image(url=member.display_avatar.url)
        embed.add_field(name="Open original", value=f"[Click here]({member.display_avatar.url})")
        await ctx.send(embed=embed)

    @commands.command(name="userinfo")
    async def userinfo(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author
        embed = discord.Embed(title=member.display_name, color=member.color)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="User ID", value=member.id, inline=True)
        embed.add_field(name="Mention", value=member.mention, inline=True)
        embed.add_field(name="Bot", value="Yes" if member.bot else "No", inline=True)
        embed.add_field(name="Status", value=str(member.status).title(), inline=True)
        embed.add_field(
            name="Account created",
            value=discord.utils.format_dt(member.created_at, style="R"),
            inline=False,
        )
        embed.add_field(
            name="Joined server",
            value=discord.utils.format_dt(member.joined_at, style="R"),
            inline=False,
        )
        roles = [role.mention for role in member.roles if role != ctx.guild.default_role][::-1]
        embed.add_field(
            name=f"Roles ({len(roles)})",
            value=", ".join(roles) if roles else "None",
            inline=False,
        )
        embed.set_footer(text=f"Requested by {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    @app_commands.command(name="ping", description="Check the bot's latency")
    async def slash_ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000, 2)
        await interaction.response.send_message(f"Pong! {latency}ms")

    @app_commands.command(name="echo", description="Repeat a message back")
    @app_commands.describe(message="The message to echo")
    async def slash_echo(self, interaction: discord.Interaction, message: str):
        await interaction.response.send_message(message)

    @app_commands.command(name="avatar", description="Show a user's profile picture")
    @app_commands.describe(member="The user to show the avatar of (defaults to you)")
    async def slash_avatar(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        embed = discord.Embed(
            title=f"{member.display_name}'s avatar",
            color=member.color,
            url=member.display_avatar.url,
        )
        embed.set_image(url=member.display_avatar.url)
        embed.add_field(name="Open original", value=f"[Click here]({member.display_avatar.url})")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="userinfo", description="Show details about a user")
    @app_commands.describe(member="The user to inspect (defaults to you)")
    async def slash_userinfo(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        embed = discord.Embed(title=member.display_name, color=member.color)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="User ID", value=member.id, inline=True)
        embed.add_field(name="Mention", value=member.mention, inline=True)
        embed.add_field(name="Bot", value="Yes" if member.bot else "No", inline=True)
        embed.add_field(name="Status", value=str(member.status).title(), inline=True)
        embed.add_field(
            name="Account created",
            value=discord.utils.format_dt(member.created_at, style="R"),
            inline=False,
        )
        embed.add_field(
            name="Joined server",
            value=discord.utils.format_dt(member.joined_at, style="R"),
            inline=False,
        )
        roles = [role.mention for role in member.roles if role != interaction.guild.default_role][::-1]
        embed.add_field(
            name=f"Roles ({len(roles)})",
            value=", ".join(roles) if roles else "None",
            inline=False,
        )
        embed.set_footer(
            text=f"Requested by {interaction.user.display_name}",
            icon_url=interaction.user.display_avatar.url,
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Info(bot))
