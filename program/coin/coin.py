import discord
from discord import app_commands, Interaction
from discord.ext import commands
from datetime import datetime, timedelta
import random

class Coin(commands.Cog):
    def __init__(self, bot, db):
        self.bot = bot
        self.db = db

    # Firebase ドキュメント参照
    def get_user_ref(self, user_id):
        return self.db.collection("users").document(str(user_id))

    # ユーザーデータ取得（必要な項目を初期化）
    async def get_user_data(self, user_id):
        doc = self.get_user_ref(user_id).get()
        if doc.exists:
            data = doc.to_dict()
        else:
            data = {}

        # 必須フィールドを保証
        data.setdefault("coins", 0)
        data.setdefault("work_level", 1)
        data.setdefault("work_exp", 0)
        data.setdefault("last_work", None)
        data.setdefault("last_daily", None)
        data.setdefault("streak", 0)
        data.setdefault("work_locked_until", None)  # 窃盗失敗によるワークロック
        return data

    # データ保存（部分更新）
    async def set_user_data(self, user_id, data):
        self.get_user_ref(user_id).set(data, merge=True)

    # コイン加算
    async def add_coins(self, user_id, amount):
        ref = self.get_user_ref(user_id)
        doc = ref.get()
        if doc.exists:
            coins = doc.to_dict().get("coins", 0) + amount
        else:
            coins = amount
        ref.set({"coins": coins}, merge=True)
        return coins

    # コイン減算
    async def remove_coins(self, user_id, amount):
        ref = self.get_user_ref(user_id)
        doc = ref.get()
        coins = doc.to_dict().get("coins", 0) if doc.exists else 0
        if coins < amount:
            return False
        ref.set({"coins": coins - amount}, merge=True)
        return True

    # 🔹 /give_coin コマンド
    @app_commands.command(name="give_coin", description="指定ユーザーにコインを渡す")
    @app_commands.describe(user="受け取るユーザー", price="渡すコイン数")
    async def give_coin(self, interaction: Interaction, user: discord.Member, price: int):
        if price <= 0:
            await interaction.response.send_message("❌ 1以上の値を指定してください。", ephemeral=True)
            return

        can_send = await self.remove_coins(interaction.user.id, price)
        if not can_send:
            await interaction.response.send_message("❌ コインが不足しています。", ephemeral=True)
            return

        await self.add_coins(user.id, price)
        await interaction.response.send_message(f"✅ {user.display_name} に {price} コインを渡しました！")

    # 🔹 /work コマンド
    @app_commands.command(name="work", description="仕事をしてコインと経験値を得る（4時間ごと）")
    async def work(self, interaction: Interaction):
        user_id = interaction.user.id
        data = await self.get_user_data(user_id)
        now = datetime.utcnow()

        # 🔒 窃盗失敗による work ロックチェック
        work_locked_until_str = data.get("work_locked_until")
        if work_locked_until_str:
            work_locked_until = datetime.fromisoformat(work_locked_until_str)
            if now < work_locked_until:
                remaining = work_locked_until - now
                hours = remaining.seconds // 3600
                minutes = (remaining.seconds % 3600) // 60
                await interaction.response.send_message(
                    f"⏳ 窃盗失敗により現在 `/work` は使えません。\n"
                    f"残り時間: {hours}時間 {minutes}分",
                    ephemeral=True
                )
                return

        # 🔹 既存のクールダウンチェック（4時間）
        last_work = data.get("last_work")
        if last_work:
            last_time = datetime.fromisoformat(last_work)
            if now - last_time < timedelta(hours=4):
                remaining = timedelta(hours=4) - (now - last_time)
                hours, remainder = divmod(int(remaining.total_seconds()), 3600)
                minutes, seconds = divmod(remainder, 60)
                await interaction.response.send_message(
                    f"⏳ まだ働けません。あと {hours}時間 {minutes}分 {seconds}秒 待ってください。",
                    ephemeral=True
                )
                return

        # 🔹 労働処理（報酬・経験値・レベルアップ）
        level = data["work_level"]
        earned_coins = random.randint(50, 100) * level
        earned_exp = random.randint(15, 30)

        data["coins"] += earned_coins
        data["work_exp"] += earned_exp
        data["last_work"] = now.isoformat()

        # レベルアップ判定
        required_exp = data["work_level"] * 100
        leveled_up = False
        while data["work_exp"] >= required_exp:
            data["work_exp"] -= required_exp
            data["work_level"] += 1
            required_exp = data["work_level"] * 100
            leveled_up = True

        await self.set_user_data(user_id, data)

        msg = f"💼 労働完了！\n💰 +{earned_coins} コイン\n✨ +{earned_exp} 経験値"
        if leveled_up:
            msg += f"\n🎉 **レベルアップ！ 現在の労働レベル: {data['work_level']}**"

        await interaction.response.send_message(msg)

# Cog 登録
async def setup(bot, db):
    await bot.add_cog(Coin(bot, db))
