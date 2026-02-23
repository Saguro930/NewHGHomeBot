import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta
import random

class Bonus(commands.Cog):
    def __init__(self, bot, db):
        self.bot = bot
        self.db = db

    # Firestore ドキュメント参照
    def get_user_ref(self, user_id):
        return self.db.collection("users").document(str(user_id))

    # ユーザーデータ取得
    async def get_user_data(self, user_id):
        doc = self.get_user_ref(user_id).get()
        data = doc.to_dict() if doc.exists else {}
        data.setdefault("coins", 0)
        data.setdefault("streak", 0)
        data.setdefault("last_daily", None)
        data.setdefault("last_weekly", None)
        data.setdefault("last_monthly", None)
        return data

    # データ更新
    async def set_user_data(self, user_id, data):
        self.get_user_ref(user_id).set(data, merge=True)

    # コイン加算
    async def add_coins(self, user_id, amount):
        ref = self.get_user_ref(user_id)
        doc = ref.get()
        coins = doc.to_dict().get("coins", 0) + amount if doc.exists else amount
        ref.set({"coins": coins}, merge=True)
        return coins

    # 🔹 /daily コマンド（連続ボーナス付き）
    @app_commands.command(name="daily", description="毎日のログインボーナス")
    async def daily(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        data = await self.get_user_data(user_id)
        now = datetime.utcnow()

        last_claim = data.get("last_daily")
        streak = data.get("streak", 0)

        if last_claim:
            last_time = datetime.fromisoformat(last_claim)
            diff = now - last_time

            if diff < timedelta(hours=20):
                remaining = timedelta(hours=20) - diff
                hours, remainder = divmod(int(remaining.total_seconds()), 3600)
                minutes, seconds = divmod(remainder, 60)
                await interaction.response.send_message(
                    f"⏳ まだ受け取れません。あと {hours}時間 {minutes}分 {seconds}秒 待ってください。",
                    ephemeral=True
                )
                return
            elif diff > timedelta(hours=48):
                streak = 1
            else:
                streak += 1
        else:
            streak = 1

        base_reward = 100
        bonus = min(streak * 10, 200)
        reward = base_reward + bonus

        await self.add_coins(user_id, reward)
        await self.set_user_data(user_id, {
            "last_daily": now.isoformat(),
            "streak": streak
        })

        msg = (
            f"🎁 デイリーボーナスを受け取りました！\n"
            f"💰 獲得：{reward} コイン（基本 {base_reward} + ボーナス {bonus}）\n"
            f"🔥 連続ログイン {streak} 日目！"
        )
        await interaction.response.send_message(msg)

    # 🔹 /weekly コマンド（週1ボーナス）
    @app_commands.command(name="weekly", description="週に一度のボーナスを受け取る")
    async def weekly(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        data = await self.get_user_data(user_id)
        now = datetime.utcnow()

        last_claim = data.get("last_weekly")

        if last_claim:
            last_time = datetime.fromisoformat(last_claim)
            diff = now - last_time

            if diff < timedelta(days=7):
                remaining = timedelta(days=7) - diff
                days, remainder = divmod(int(remaining.total_seconds()), 86400)
                hours, remainder = divmod(remainder, 3600)
                minutes, seconds = divmod(remainder, 60)
                await interaction.response.send_message(
                    f"⏳ まだ受け取れません。あと {days}日 {hours}時間 {minutes}分 待ってください。",
                    ephemeral=True
                )
                return

        reward = 700
        await self.add_coins(user_id, reward)
        await self.set_user_data(user_id, {
            "last_weekly": now.isoformat()
        })

        await interaction.response.send_message(
            f"💎 ウィークリーボーナスを受け取りました！\n💰 +{reward} コイン\n📅 次回は1週間後に受け取れます！"
        )

      # 🔹 /monthly コマンド（月1ボーナス）
    @app_commands.command(name="monthly", description="月に一度のボーナスを受け取る")
    async def monthly(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        data = await self.get_user_data(user_id)
        now = datetime.utcnow()

        last_claim = data.get("last_monthly")

        if last_claim:
            last_time = datetime.fromisoformat(last_claim)
            diff = now - last_time

            if diff < timedelta(days=30):
                remaining = timedelta(days=30) - diff
                days, remainder = divmod(int(remaining.total_seconds()), 86400)
                hours, remainder = divmod(remainder, 3600)
                minutes, seconds = divmod(remainder, 60)
                await interaction.response.send_message(
                    f"⏳ まだ受け取れません。あと {days}日 {hours}時間 {minutes}分 待ってください。",
                    ephemeral=True
                )
                return

        reward = 3000
        await self.add_coins(user_id, reward)
        await self.set_user_data(user_id, {
            "last_monthly": now.isoformat()
        })

        await interaction.response.send_message(
            f"🌙 マンスリーボーナスを受け取りました！\n💰 +{reward} コイン\n📅 次回は30日後に受け取れます！"
        )

# Cog登録
async def setup(bot, db):
    await bot.add_cog(Bonus(bot, db))
