import discord
from discord.ext import commands
from discord import app_commands
import aiohttp

class Trade(commands.Cog):
    def __init__(self, bot, db):
        self.bot = bot
        self.db = db
        self.API_URL = "https://www.alphavantage.co/query?function=CURRENCY_EXCHANGE_RATE&from_currency=USD&to_currency=JPY&apikey=demo"
        self.COIN_RATE = 10  # 1コイン = 10円固定

    # 🔹 ドル円レートを取得
    async def get_usd_jpy_rate(self):
        async with aiohttp.ClientSession() as session:
            async with session.get(self.API_URL) as resp:
                data = await resp.json()
                return float(data["Realtime Currency Exchange Rate"]["5. Exchange Rate"])

    # 🔹 ユーザーデータ取得
    async def get_user_data(self, user_id):
        doc_ref = self.db.collection("users").document(str(user_id))
        doc = doc_ref.get()
        return doc.to_dict() if doc.exists else {}

    # 🔹 ユーザーデータ更新
    async def update_user_data(self, user_id, data):
        self.db.collection("users").document(str(user_id)).set(data, merge=True)

    # 💵 レート表示コマンド
    @app_commands.command(name="dollar", description="現在のドル円レートを表示します")
    async def dollar(self, interaction: discord.Interaction):
        try:
            rate = await self.get_usd_jpy_rate()
            embed = discord.Embed(
                title="💵 為替レート情報",
                description=f"1 🇺🇸 USD = 🇯🇵 {rate:.2f} 円",
                color=discord.Color.green()
            )
            embed.add_field(name="💰 換算レート", value="1コイン = 10円（固定）", inline=False)
            embed.add_field(name="🧮 計算例", value=f"100コイン ≒ {100 * 10 / rate:.2f} USD", inline=False)
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await interaction.response.send_message(f"❌ 為替情報の取得に失敗しました: {e}", ephemeral=True)

    # 💱 トレードコマンド
    @app_commands.command(name="trade", description="コインとドルを交換します")
    @app_commands.describe(
        type="トレードの種類を選択してください",
        amount="交換する金額を入力してください（コインまたはドル）"
    )
    @app_commands.choices(
        type=[
            app_commands.Choice(name="💰 コイン → ドル", value="coin_to_dollar"),
            app_commands.Choice(name="💵 ドル → コイン", value="dollar_to_coin"),
        ]
    )
    async def trade(self, interaction: discord.Interaction, type: app_commands.Choice[str], amount: int):
        user_id = str(interaction.user.id)
        data = await self.get_user_data(user_id)
        if data is None:
            data = {"coins": 0, "dollar": 0}

        coins = data.get("coins", 0)
        dollars = data.get("dollar", 0)
        rate = await self.get_usd_jpy_rate()

        if type.value == "coin_to_dollar":
            if coins < amount:
                await interaction.response.send_message("❌ コインが不足しています。", ephemeral=True)
                return
            yen_value = amount * self.COIN_RATE
            dollar_value = yen_value / rate
            coins -= amount
            dollars += dollar_value
            await self.update_user_data(user_id, {"coins": coins, "dollar": dollars})

            await interaction.response.send_message(
                f"✅ {amount}コインを {dollar_value:.2f}ドル に交換しました！\n"
                f"💰 現在の残高: {coins}コイン / {dollars:.2f}ドル"
            )

        elif type.value == "dollar_to_coin":
            if dollars < amount:
                await interaction.response.send_message("❌ ドルが不足しています。", ephemeral=True)
                return
            yen_value = amount * rate
            coin_value = yen_value / self.COIN_RATE
            dollars -= amount
            coins += coin_value
            await self.update_user_data(user_id, {"coins": coins, "dollar": dollars})

            await interaction.response.send_message(
                f"✅ {amount}ドルを {coin_value:.0f}コイン に交換しました！\n"
                f"💰 現在の残高: {coins:.0f}コイン / {dollars:.2f}ドル"
            )

# Cog登録
async def setup(bot, db):
    await bot.add_cog(Trade(bot, db))
