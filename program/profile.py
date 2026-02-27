import discord
from discord.ext import commands
from discord import app_commands

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
        else:
            return {"coins": 0, "bank": 0, "work_level": 1, "dollar": 0.0}

    @app_commands.command(name="profile", description="自分のプロフィールを表示します")
    async def profile(self, interaction: discord.Interaction):
        user = interaction.user
        data = await self.get_user_data(user.id)

        coins      = data.get("coins", 0)
        bank       = data.get("bank", 0)
        work_level = data.get("work_level", 1)
        dollar     = data.get("dollar", 0.0)
        steal_level = data.get("steal_level", 1)
        steal_exp   = data.get("steal_exp", 0)
        total = coins + bank

        # 借金状態で赤、通常は blurple
        color = discord.Color.red() if coins < 0 else discord.Color.blurple()

        embed = discord.Embed(
            title=f"👤 {user.display_name} のプロフィール",
            color=color
        )

        # 所持金：借金なら ⚠️ 表示
        if coins < 0:
            coins_display = f"⚠️ **-{abs(coins)} コイン（借金）**"
        else:
            coins_display = f"{coins:,} コイン"

        # 合計資産：マイナスになる場合も対応
        if total < 0:
            total_display = f"⚠️ **-{abs(total):,} コイン（債務超過）**"
        else:
            total_display = f"{total:,} コイン"

        embed.add_field(name="💰 所持金",    value=coins_display,            inline=True)
        embed.add_field(name="🏦 銀行残高",  value=f"{bank:,} コイン",       inline=True)
        embed.add_field(name="💵 所持ドル",  value=f"${dollar:,.2f} USD",    inline=True)
        embed.add_field(name="💼 職業レベル", value=f"Lv.{work_level}",       inline=True)
        embed.add_field(name="💀 窃盗レベル", value=f"Lv.{steal_level} ({steal_exp} exp)", inline=True)
        embed.add_field(name="💰 合計資産",  value=total_display,            inline=False)

        embed.set_thumbnail(url=user.display_avatar.url)
        await interaction.response.send_message(embed=embed)


async def setup(bot, db):
    await bot.add_cog(Profile(bot, db))
