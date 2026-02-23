import discord
from discord.ext import commands
from discord import app_commands

class Top(commands.Cog):
    def __init__(self, bot, db):
        self.bot = bot
        self.db = db

    # 🔹 /top コマンド
    @app_commands.command(name="top", description="ランキングを表示します")
    @app_commands.describe(type="ランキングの種類を選択してください")
    @app_commands.choices(
        type=[        
            app_commands.Choice(name="💰 所持金ランキング", value="coin"),       
            app_commands.Choice(name="🏦 銀行残高ランキング", value="bank"),       
            app_commands.Choice(name="💼 職業レベルランキング", value="work_level"),      
            app_commands.Choice(name="💵 合計資産ランキング", value="total"),  
            app_commands.Choice(name="💲 所持ドルランキング", value="dollar_rank"), 
        ]
    )

    async def top(self, interaction: discord.Interaction, type: app_commands.Choice[str]):
        ranking_type = type.value
        users_ref = self.db.collection("users")
        docs = users_ref.stream()

        ranking = []
        for doc in docs:
            data = doc.to_dict()
            if ranking_type == "coin":
                value = data.get("coins", 0)
            elif ranking_type == "bank":
                value = data.get("bank", 0)
            elif ranking_type == "work_level":
                value = data.get("work_level", 0)
            elif ranking_type == "total":
                value = data.get("coins", 0) + data.get("bank", 0)
            elif ranking_type == "dollar_rank":
                value = data.get("dollar", 0.0)
            ranking.append((doc.id, value))

        # 🔹 降順ソート（上位10人）
        ranking.sort(key=lambda x: x[1], reverse=True)
        top_10 = ranking[:10]

        # 🔹 埋め込み作成
        embed = discord.Embed(
            title=f"🏆 {type.name}",
            color=discord.Color.gold()
        )

        if not top_10:
            embed.description = "データがありません。"
        else:
            for i, (user_id, value) in enumerate(top_10, start=1):
                try:
                    user = await self.bot.fetch_user(int(user_id))
                    name = user.display_name
                except:
                    name = "不明なユーザー"
                if ranking_type == "dollar_rank":
                    display_value = f"${value:,.2f}"  # ドル表示
                else:
                    display_value = f"{value:,}"
                embed.add_field(
                    name=f"#{i} {name}",
                    value=display_value,
                    inline=False
                )

        await interaction.response.send_message(embed=embed)

# 🔹 Cog登録
async def setup(bot, db):
    await bot.add_cog(Top(bot, db))
