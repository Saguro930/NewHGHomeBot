import discord
from discord.ext import commands
from discord import app_commands
import time

class Ping(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="ping", description="Botの応答速度を確認する")
    async def ping(self, interaction: discord.Interaction):
        ws_latency = round(self.bot.latency * 1000)  # WebSocket レイテンシ（ms）

        # APIレイテンシ計測（送信にかかった時間）
        start = time.perf_counter()
        await interaction.response.defer()
        end = time.perf_counter()
        api_latency = round((end - start) * 1000)

        # WebSocket の値で色を決定
        if ws_latency < 100:
            color = 0x2ECC71   # 緑：良好
            status = "🟢 良好"
        elif ws_latency < 200:
            color = 0xF39C12   # オレンジ：普通
            status = "🟡 普通"
        else:
            color = 0xE74C3C   # 赤：遅い
            status = "🔴 遅延あり"

        embed = discord.Embed(title="🏓 Pong!", color=color)
        embed.add_field(name="WebSocket",  value=f"`{ws_latency} ms`",  inline=True)
        embed.add_field(name="API",        value=f"`{api_latency} ms`", inline=True)
        embed.add_field(name="ステータス", value=status,                inline=True)
        embed.set_footer(text=f"要求者: {interaction.user.display_name}")

        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Ping(bot))
