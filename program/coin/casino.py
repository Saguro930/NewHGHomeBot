import discord
from discord.ext import commands
from discord import app_commands
import random
from firebase_admin import firestore

class Casino(commands.Cog):
    def __init__(self, bot, db):
        self.bot = bot
        self.db = db

    def get_user_ref(self, user_id):
        return self.db.collection("users").document(str(user_id))

    async def add_coins(self, user_id, amount):
        ref = self.get_user_ref(user_id)
        doc = ref.get()
        if doc.exists:
            coins = doc.to_dict().get("coins", 0) + amount
        else:
            coins = amount
        ref.set({"coins": coins}, merge=True)
        return coins

    async def remove_coins(self, user_id, amount):
        ref = self.get_user_ref(user_id)
        doc = ref.get()
        coins = doc.to_dict().get("coins", 0) if doc.exists else 0
        if coins < amount:
            return False
        coins -= amount
        ref.set({"coins": coins}, merge=True)
        return True

    # 🔹 /cointoss
    @app_commands.command(name="cointoss", description="コイントスで勝負")
    @app_commands.describe(bet="賭けるコインの量")
    async def cointoss(self, interaction: discord.Interaction, bet: int):
        if bet <= 0:
            await interaction.response.send_message("❌ 1以上の値を指定してください。", ephemeral=True)
            return
        can_play = await self.remove_coins(interaction.user.id, bet)
        if not can_play:
            await interaction.response.send_message("❌ コインが不足しています。", ephemeral=True)
            return

        result = random.choice(["表", "裏"])
        if result == "表":  # 勝利
            await self.add_coins(interaction.user.id, bet * 2)
            await interaction.response.send_message(f"🎉 結果: 表！ {bet*2} コインを獲得しました！")
        else:
            await interaction.response.send_message(f"💔 結果: 裏。 {bet} コインを失いました。")

    # 🔹 /slot（倍率指定版）
    @app_commands.command(name="slot", description="スロットで遊ぶ（7=35倍、🍒=30倍、他=25倍）")
    @app_commands.describe(bet="賭けるコインの量")
    async def slot(self, interaction: discord.Interaction, bet: int):
        if bet <= 0:
            await interaction.response.send_message("❌ 1以上の値を指定してください。", ephemeral=True)
            return

        can_play = await self.remove_coins(interaction.user.id, bet)
        if not can_play:
            await interaction.response.send_message("❌ コインが不足しています。", ephemeral=True)
            return

        icons = ["🍒", "🍋", "🍊", "🍇", "7️⃣"]

        # 🎯 当たりやすくする（6%の確率で揃う）
        if random.random() < 0.06:
            symbol = random.choice(icons)
            result = [symbol, symbol, symbol]
            win = True
        else:
            result = [random.choice(icons) for _ in range(3)]
            win = result[0] == result[1] == result[2]

        if win:
            symbol = result[0]
            # 🔸倍率設定
            if symbol == "7️⃣":
                payout = bet * 35
            elif symbol == "🍒":
                payout = bet * 30
            else:
                payout = bet * 25

            await self.add_coins(interaction.user.id, payout)
            await interaction.response.send_message(
                f"🎰 {' '.join(result)}\n✨大当たり！{symbol} 揃い！ {payout} コインを獲得！✨"
            )
        else:
            await interaction.response.send_message(
                f"🎰 {' '.join(result)}\n残念、{bet} コインを失いました。"
            )



    # 🔹 /dice
    @app_commands.command(name="dice", description="1～6 の数字を予想して賭ける")
    @app_commands.describe(bet="賭けるコインの量", guess="予想する数字（1～6）")
    async def dice(self, interaction: discord.Interaction, bet: int, guess: int):
        if bet <= 0:
            await interaction.response.send_message("❌ 1以上の値を指定してください。", ephemeral=True)
            return
        if not (1 <= guess <= 6):
            await interaction.response.send_message("❌ 1～6 の数字を指定してください。", ephemeral=True)
            return

        can_play = await self.remove_coins(interaction.user.id, bet)
        if not can_play:
            await interaction.response.send_message("❌ コインが不足しています。", ephemeral=True)
            return

        result = random.randint(1, 6)
        if guess == result:
            payout = bet * 6
            await self.add_coins(interaction.user.id, payout)
            await interaction.response.send_message(f"🎲 出目: {result}！ おめでとう！ {payout} コインを獲得！")
        else:
            await interaction.response.send_message(f"🎲 出目: {result}。残念、{bet} コインを失いました。")

# 🔹 Cog登録用
async def setup(bot, db):
    await bot.add_cog(Casino(bot, db))
