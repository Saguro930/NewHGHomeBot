import discord
from discord.ext import commands
from discord import app_commands
import time
import psutil
import os

BOT_MEM_LIMIT_MB = 512  # Bot のメモリ上限（MB）
BAR_LENGTH = 10          # 棒グラフのブロック数


def make_bar(percent: float) -> str:
    """パーセントを横棒グラフ文字列に変換する"""
    filled = max(0, min(BAR_LENGTH, round(percent / 100 * BAR_LENGTH)))
    return "█" * filled + "░" * (BAR_LENGTH - filled)


class Ping(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._process = psutil.Process(os.getpid())

    @app_commands.command(name="ping", description="Botの応答速度とサーバー状態を確認する")
    async def ping(self, interaction: discord.Interaction):
        ws_latency = round(self.bot.latency * 1000)

        start = time.perf_counter()
        await interaction.response.defer()
        end = time.perf_counter()
        api_latency = round((end - start) * 1000)

        # ── システム情報取得 ──────────────────────────────
        cpu_percent = psutil.cpu_percent(interval=0.1)

        mem_info = self._process.memory_info()
        mem_mb   = mem_info.rss / 1024 / 1024
        mem_pct  = mem_mb / BOT_MEM_LIMIT_MB * 100

        sys_mem       = psutil.virtual_memory()
        sys_mem_used  = sys_mem.used  / 1024 / 1024
        sys_mem_total = sys_mem.total / 1024 / 1024
        sys_mem_pct   = sys_mem.percent

        # ── ステータス判定 ────────────────────────────────
        if ws_latency < 100:
            color, status = 0x2ECC71, "🟢 良好"
        elif ws_latency < 200:
            color, status = 0xF39C12, "🟡 普通"
        else:
            color, status = 0xE74C3C, "🔴 遅延あり"

        cpu_icon = "🟢" if cpu_percent < 50 else ("🟡" if cpu_percent < 80 else "🔴")
        mem_icon = "🟢" if sys_mem_pct  < 60 else ("🟡" if sys_mem_pct  < 85 else "🔴")
        bot_icon = "🟢" if mem_pct      < 60 else ("🟡" if mem_pct      < 85 else "🔴")

        # ── Embed 構築 ────────────────────────────────────
        embed = discord.Embed(title="🏓 Pong!", color=color)

        embed.add_field(name="📡 WebSocket", value=f"`{ws_latency} ms`",  inline=True)
        embed.add_field(name="🔁 API",       value=f"`{api_latency} ms`", inline=True)
        embed.add_field(name="状態",         value=status,                inline=True)

        embed.add_field(
            name=f"{cpu_icon} CPU使用率",
            value=f"`{make_bar(cpu_percent)}` {cpu_percent:.1f}%",
            inline=False,
        )
        embed.add_field(
            name=f"{mem_icon} メモリ（システム全体）",
            value=f"`{make_bar(sys_mem_pct)}` {sys_mem_used:.0f} MB / {sys_mem_total:.0f} MB ({sys_mem_pct:.1f}%)",
            inline=False,
        )
        embed.add_field(
            name=f"{bot_icon} Bot プロセス",
            value=f"`{make_bar(mem_pct)}` {mem_mb:.1f} MB / {BOT_MEM_LIMIT_MB} MB ({mem_pct:.1f}%)",
            inline=False,
        )

        embed.set_footer(text=f"要求者: {interaction.user.display_name}")
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Ping(bot))
