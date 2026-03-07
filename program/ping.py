import discord
from discord.ext import commands
from discord import app_commands
import time
import psutil
import os

class Ping(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # プロセスオブジェクトを使い回す（初回だけ取得）
        self._process = psutil.Process(os.getpid())

    @app_commands.command(name="ping", description="Botの応答速度とサーバー状態を確認する")
    async def ping(self, interaction: discord.Interaction):
        ws_latency = round(self.bot.latency * 1000)

        # APIレイテンシ計測
        start = time.perf_counter()
        await interaction.response.defer()
        end = time.perf_counter()
        api_latency = round((end - start) * 1000)

        # ── システム情報取得 ──────────────────────────────
        # CPU: interval=0.1 で直近の使用率（短めにして応答を遅らせない）
        cpu_percent = psutil.cpu_percent(interval=0.1)

        # メモリ: Bot プロセス自身の使用量
        mem_info   = self._process.memory_info()
        mem_mb     = mem_info.rss / 1024 / 1024          # RSS（MB）

        # システム全体のメモリ
        sys_mem      = psutil.virtual_memory()
        sys_mem_used = sys_mem.used  / 1024 / 1024       # MB
        sys_mem_total= sys_mem.total / 1024 / 1024       # MB
        sys_mem_pct  = sys_mem.percent

        # ── ステータス判定 ────────────────────────────────
        if ws_latency < 100:
            color, status = 0x2ECC71, "🟢 良好"
        elif ws_latency < 200:
            color, status = 0xF39C12, "🟡 普通"
        else:
            color, status = 0xE74C3C, "🔴 遅延あり"

        # CPU 色
        cpu_icon = "🟢" if cpu_percent < 50 else ("🟡" if cpu_percent < 80 else "🔴")
        # メモリ色
        mem_icon = "🟢" if sys_mem_pct < 60 else ("🟡" if sys_mem_pct < 85 else "🔴")

        # ── Embed 構築 ────────────────────────────────────
        embed = discord.Embed(title="🏓 Pong!", color=color)

        # レイテンシ
        embed.add_field(name="📡 WebSocket",  value=f"`{ws_latency} ms`",  inline=True)
        embed.add_field(name="🔁 API",        value=f"`{api_latency} ms`", inline=True)
        embed.add_field(name="状態",          value=status,                inline=True)

        # システム情報
        embed.add_field(
            name=f"{cpu_icon} CPU使用率",
            value=f"`{cpu_percent:.1f}%`",
            inline=True,
        )
        embed.add_field(
            name=f"{mem_icon} メモリ（システム全体）",
            value=f"`{sys_mem_used:.0f} MB / {sys_mem_total:.0f} MB ({sys_mem_pct:.1f}%)`",
            inline=True,
        )
        embed.add_field(
            name="🤖 Bot プロセス",
            value=f"`{mem_mb:.1f} MB`",
            inline=True,
        )

        embed.set_footer(text=f"要求者: {interaction.user.display_name}")
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Ping(bot))
