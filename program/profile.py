import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone


# ── ユーティリティ ────────────────────────────────────────────────

def progress_bar(current: int, per_level: int, length: int = 10) -> str:
    """塗りつぶしブロックでレベルの進捗バーを生成"""
    filled = int((current % per_level) / per_level * length)
    return "█" * filled + "░" * (length - filled)

def level_exp_needed(level: int) -> int:
    """レベルアップに必要な累計exp（例：50 × level）"""
    return 50 * level

def rank_badge(level: int) -> str:
    if level >= 20: return "👑"
    if level >= 10: return "💎"
    if level >= 5:  return "🥇"
    if level >= 3:  return "🥈"
    return "🥉"

def steal_rank(level: int) -> str:
    if level >= 10: return "🕷 シャドウマスター"
    if level >= 7:  return "🗡 ゴーストシーフ"
    if level >= 5:  return "🎭 プロスリ"
    if level >= 3:  return "🃏 コソ泥"
    return "👣 見習い"

def coin_bar(coins: int, bank: int) -> str:
    """所持金と銀行のバランスを視覚化（10マス）"""
    total = coins + bank
    if total <= 0:
        return "░" * 10
    ratio = min(coins / total, 1.0)
    filled = int(ratio * 10)
    return "▰" * filled + "▱" * (10 - filled)


# ── Cog ──────────────────────────────────────────────────────────

class Profile(commands.Cog):
    def __init__(self, bot, db):
        self.bot = bot
        self.db = db

    async def get_user_data(self, user_id: int):
        ref = self.db.collection("users").document(str(user_id))
        doc = ref.get()
        if doc.exists:
            data = doc.to_dict()
            if "coins"      not in data: data["coins"]      = 0
            if "bank"       not in data: data["bank"]       = 0
            if "work_level" not in data: data["work_level"] = 1
            if "dollar"     not in data: data["dollar"]     = 0.0
            return data
        return {"coins": 0, "bank": 0, "work_level": 1, "dollar": 0.0}

    @app_commands.command(name="profile", description="自分のプロフィールを表示します")
    async def profile(self, interaction: discord.Interaction):
        user = interaction.user
        data = await self.get_user_data(user.id)

        coins       = data.get("coins", 0)
        bank        = data.get("bank", 0)
        work_level  = data.get("work_level", 1)
        dollar      = data.get("dollar", 0.0)
        steal_level = data.get("steal_level", 1)
        steal_exp   = data.get("steal_exp", 0)
        total       = coins + bank

        # ── カラー ──────────────────────────────────────────────
        if coins < 0:
            color = 0xE74C3C   # 赤：借金
        elif total >= 100_000:
            color = 0xF1C40F   # 金：富豪
        elif total >= 10_000:
            color = 0x2ECC71   # 緑：余裕
        else:
            color = 0x5865F2   # blurple：通常

        # ── 所持金表示 ────────────────────────────────────────────
        if coins < 0:
            coins_display = f"**⚠️ -{abs(coins):,}** コイン　*借金中*"
        else:
            coins_display = f"**{coins:,}** コイン"

        if total < 0:
            total_display = f"**⚠️ -{abs(total):,}** コイン　*債務超過*"
        else:
            total_display = f"**{total:,}** コイン"

        # ── 職業レベル進捗 ────────────────────────────────────────
        work_exp_needed = level_exp_needed(work_level)
        work_exp_current = data.get("work_exp", 0)
        work_bar = progress_bar(work_exp_current, work_exp_needed)
        work_display = (
            f"{rank_badge(work_level)} **Lv.{work_level}**\n"
            f"`{work_bar}` {work_exp_current}/{work_exp_needed} exp"
        )

        # ── 窃盗レベル進捗 ────────────────────────────────────────
        steal_exp_needed = level_exp_needed(steal_level)
        steal_bar = progress_bar(steal_exp, steal_exp_needed)
        steal_display = (
            f"{steal_rank(steal_level)} **Lv.{steal_level}**\n"
            f"`{steal_bar}` {steal_exp}/{steal_exp_needed} exp"
        )

        # ── 資産バランス ──────────────────────────────────────────
        bar = coin_bar(max(coins, 0), bank)
        asset_display = (
            f"手持ち {bar} 銀行\n"
            f"💰 `{max(coins,0):,}` ＋ 🏦 `{bank:,}`　＝　{total_display}"
        )

        # ── Embed 構築 ────────────────────────────────────────────
        embed = discord.Embed(color=color)

        embed.set_author(
            name=f"{user.display_name}  のプロフィール",
            icon_url=user.display_avatar.url
        )

        embed.set_thumbnail(url=user.display_avatar.url)

        # セクション区切り
        embed.add_field(
            name="─────  所持金  ─────",
            value=coins_display,
            inline=True
        )
        embed.add_field(
            name="─────  銀行残高  ─────",
            value=f"**{bank:,}** コイン",
            inline=True
        )
        embed.add_field(
            name="─────  所持ドル  ─────",
            value=f"**${dollar:,.2f}** USD",
            inline=True
        )

        embed.add_field(name="\u200b", value="\u200b", inline=False)  # spacer

        embed.add_field(
            name="💼  職業レベル",
            value=work_display,
            inline=True
        )
        embed.add_field(
            name="💀  窃盗レベル",
            value=steal_display,
            inline=True
        )

        embed.add_field(name="\u200b", value="\u200b", inline=False)  # spacer

        embed.add_field(
            name="📊  資産バランス",
            value=asset_display,
            inline=False
        )

        embed.set_footer(
            text=f"ID: {user.id}　•　{datetime.now(timezone.utc).strftime('%Y/%m/%d %H:%M')} UTC"
        )

        await interaction.response.send_message(embed=embed)


async def setup(bot, db):
    await bot.add_cog(Profile(bot, db))
