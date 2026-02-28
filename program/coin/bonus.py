import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta
from typing import Literal

class Bonus(commands.Cog):
    def __init__(self, bot, db):
        self.bot = bot
        self.db = db

    def get_user_ref(self, user_id):
        return self.db.collection("users").document(str(user_id))

    async def get_user_data(self, user_id):
        doc = self.get_user_ref(user_id).get()
        data = doc.to_dict() if doc.exists else {}
        data.setdefault("coins", 0)
        data.setdefault("streak", 0)
        data.setdefault("last_daily", None)
        data.setdefault("last_weekly", None)
        data.setdefault("last_monthly", None)
        return data

    async def set_user_data(self, user_id, data):
        self.get_user_ref(user_id).set(data, merge=True)

    async def add_coins(self, user_id, amount):
        ref = self.get_user_ref(user_id)
        doc = ref.get()
        coins = doc.to_dict().get("coins", 0) + amount if doc.exists else amount
        ref.set({"coins": coins}, merge=True)
        return coins

    @app_commands.command(name="bonus", description="ボーナスを受け取る")
    @app_commands.describe(type="ボーナスの種類を選択してください")
    async def bonus(
        self,
        interaction: discord.Interaction,
        type: Literal["daily", "weekly", "monthly"]
    ):
        user_id = interaction.user.id
        data = await self.get_user_data(user_id)
        now = datetime.utcnow()

        # タイプごとの設定
        config = {
            "daily":   {"key": "last_daily",   "cooldown": timedelta(hours=20), "reward": None,  "label": "デイリー",     "emoji": "🎁"},
            "weekly":  {"key": "last_weekly",  "cooldown": timedelta(days=7),   "reward": 700,   "label": "ウィークリー", "emoji": "💎"},
            "monthly": {"key": "last_monthly", "cooldown": timedelta(days=30),  "reward": 3000,  "label": "マンスリー",   "emoji": "🌙"},
        }
        cfg = config[type]
        last_key = cfg["key"]
        last_claim = data.get(last_key)

        # クールダウンチェック
        if last_claim:
            last_time = datetime.fromisoformat(last_claim)
            diff = now - last_time

            if diff < cfg["cooldown"]:
                remaining = cfg["cooldown"] - diff
                total_sec = int(remaining.total_seconds())
                days, r = divmod(total_sec, 86400)
                hours, r = divmod(r, 3600)
                minutes, seconds = divmod(r, 60)

                parts = []
                if days:    parts.append(f"{days}日")
                if hours:   parts.append(f"{hours}時間")
                if minutes: parts.append(f"{minutes}分")
                parts.append(f"{seconds}秒")

                await interaction.response.send_message(
                    f"⏳ まだ受け取れません。あと {''.join(parts)} 待ってください。",
                    ephemeral=True
                )
                return

        # デイリーのみ連続ログイン処理
        streak = data.get("streak", 0)
        bonus_coins = 0
        streak_msg = ""

        if type == "daily":
            if last_claim:
                diff = now - datetime.fromisoformat(last_claim)
                streak = 1 if diff > timedelta(hours=48) else streak + 1
            else:
                streak = 1

            base_reward = 100
            bonus_coins = min(streak * 10, 200)
            reward = base_reward + bonus_coins
            streak_msg = f"\n🔥 連続ログイン {streak} 日目！"

            await self.set_user_data(user_id, {"streak": streak})
        else:
            reward = cfg["reward"]

        # コイン付与 & 最終受取時刻を更新
        await self.add_coins(user_id, reward)
        await self.set_user_data(user_id, {last_key: now.isoformat()})

        # 返信メッセージ
        detail = f"（基本 {base_reward} + ボーナス {bonus_coins}）" if type == "daily" else ""
        await interaction.response.send_message(
            f"{cfg['emoji']} {cfg['label']}ボーナスを受け取りました！\n"
            f"💰 獲得：{reward} コイン {detail}"
            f"{streak_msg}"
        )

async def setup(bot, db):
    await bot.add_cog(Bonus(bot, db))
