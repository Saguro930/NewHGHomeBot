import discord
from discord import app_commands
from discord.ext import commands
import random
from datetime import datetime, timedelta
import asyncio

class StealAgainView(discord.ui.View):
    """成功後に「もう一度盗む」ボタンを表示する View"""

    def __init__(self, cog: "Steal", thief: discord.Member, target: discord.User, steal_cap: float):
        super().__init__(timeout=30)
        self.cog = cog
        self.thief = thief
        self.target = target
        # 今回の上限倍率（最初は target_coins * 0.3、以降は * 0.5 ずつ縮小）
        self.steal_cap = steal_cap

    @discord.ui.button(label="💀 もう一度盗む！（上限 1/2）", style=discord.ButtonStyle.danger)
    async def steal_again(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 操作者がオリジナルの泥棒本人か確認
        if interaction.user.id != self.thief.id:
            await interaction.response.send_message("❌ あなたはこの盗みに関係ありません。", ephemeral=True)
            return

        # ボタンを無効化（二重押し防止）
        button.disabled = True
        await interaction.response.edit_message(view=self)

        await self.cog._do_steal(
            interaction=interaction,
            thief=self.thief,
            target=self.target,
            steal_cap=self.steal_cap,
            followup=True,   # response は edit_message 済みなので followup を使う
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class Steal(commands.Cog):
    def __init__(self, bot, db):
        self.bot = bot
        self.db = db
        self.cooldowns = {}

    # ── Firestore ──────────────────────────────────────────────────
    async def get_user_data(self, user_id: int):
        ref = self.db.collection("users").document(str(user_id))
        doc = await asyncio.to_thread(ref.get)
        if doc.exists:
            return doc.to_dict()
        data = {"coins": 0, "steal_exp": 0, "steal_level": 1, "work_locked_until": None}
        await asyncio.to_thread(ref.set, data)
        return data

    async def set_user_data(self, user_id: int, new_data: dict):
        ref = self.db.collection("users").document(str(user_id))
        await asyncio.to_thread(ref.set, new_data, {"merge": True})

    # ── レベルアップ判定 ───────────────────────────────────────────
    def check_level_up(self, exp: int, level: int):
        next_exp = level * 50
        leveled_up = False
        while exp >= next_exp:
            exp -= next_exp
            level += 1
            leveled_up = True
            next_exp = level * 50
        return exp, level, leveled_up

    # ── 盗み本体（初回・連続共通） ─────────────────────────────────
    async def _do_steal(
        self,
        interaction: discord.Interaction,
        thief: discord.Member,
        target: discord.User,
        steal_cap: float,       # target_coins に掛ける上限倍率
        followup: bool = False, # True のとき interaction.followup.send を使う
    ):
        thief_data  = await self.get_user_data(thief.id)
        target_data = await self.get_user_data(target.id)

        thief_coins  = thief_data.get("coins", 0)
        target_coins = target_data.get("coins", 0)
        steal_exp    = thief_data.get("steal_exp", 0)
        steal_level  = thief_data.get("steal_level", 1)

        if target_coins < 10:
            msg = "😅 相手はもうほとんどお金を持っていません！"
            if followup:
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return

        # 成功率（レベル補正）
        success_chance = min(0.45 + steal_level * 0.02, 0.9)

        send = interaction.followup.send if followup else interaction.response.send_message

        # ── 成功 ──────────────────────────────────────────────────
        if random.random() < success_chance:
            max_steal = max(5, int(target_coins * steal_cap))
            stolen = random.randint(5, max_steal)
            target_coins -= stolen
            thief_coins  += stolen

            steal_exp += 10
            steal_exp, steal_level, leveled_up = self.check_level_up(steal_exp, steal_level)

            await self.set_user_data(target.id, {"coins": target_coins})
            await self.set_user_data(thief.id, {
                "coins": thief_coins,
                "steal_exp": steal_exp,
                "steal_level": steal_level,
            })

            msg = (
                f"💀 {thief.mention} は {target.mention} から **{stolen} コイン** を盗みました！\n"
                f"🔻 盗める上限は残り **{int(steal_cap * 100)}%** 分でした。"
            )
            if leveled_up:
                msg += f"\n📈 窃盗レベルが **Lv.{steal_level}** に上がった！"

            # 次回の上限は今回の 1/2
            next_cap = steal_cap / 2

            # 上限が小さすぎる（5コイン未満になる可能性が高い）場合はボタンを出さない
            if target_coins >= 10 and int(target_coins * next_cap) >= 5:
                view = StealAgainView(
                    cog=self,
                    thief=thief,
                    target=target,
                    steal_cap=next_cap,
                )
                await send(msg, view=view)
            else:
                await send(msg)

        # ── 失敗 ──────────────────────────────────────────────────
        else:
            intended = random.randint(5, max(5, int(target_coins * steal_cap)))
            fine = max(1, intended // 10)
            thief_coins -= fine

            steal_exp += 3
            steal_exp, steal_level, leveled_up = self.check_level_up(steal_exp, steal_level)

            work_locked_until = datetime.utcnow() + timedelta(days=1)
            await self.set_user_data(thief.id, {
                "coins": thief_coins,
                "steal_exp": steal_exp,
                "steal_level": steal_level,
                "work_locked_until": work_locked_until.isoformat(),
            })

            debt_msg = (
                f"\n💸 所持金が足りず **{abs(thief_coins)} コインの借金** 状態になった！"
                if thief_coins < 0 else ""
            )
            msg = (
                f"🚨 {thief.mention} は盗みに失敗！警察に捕まり **{fine} コイン** の罰金！\n"
                f"⏳ 1日間 `/work` が使用できません。"
                f"{debt_msg}"
            )
            if leveled_up:
                msg += f"\n📈 でも経験で学び、窃盗レベルが **Lv.{steal_level}** に上がった！"

            await send(msg)

    # ── /steal コマンド ────────────────────────────────────────────
    @app_commands.command(name="steal", description="他のユーザーからコインを盗もう！(失敗のリスクあり)")
    @app_commands.describe(user="盗む対象のユーザー")
    async def steal(self, interaction: discord.Interaction, user: discord.User):
        thief_id  = interaction.user.id
        target_id = user.id

        if thief_id == target_id:
            await interaction.response.send_message("❌ 自分自身からは盗めません。", ephemeral=True)
            return

        # クールダウン（6時間）
        now = datetime.utcnow()
        if thief_id in self.cooldowns and self.cooldowns[thief_id] > now:
            remaining = self.cooldowns[thief_id] - now
            hours   = remaining.seconds // 3600
            minutes = (remaining.seconds % 3600) // 60
            await interaction.response.send_message(
                f"⏳ もう少し待って！あと **{hours}時間 {minutes}分** 後に再挑戦できます。",
                ephemeral=True,
            )
            return

        self.cooldowns[thief_id] = now + timedelta(hours=6)

        # 初回は target_coins の 30% が上限
        await self._do_steal(
            interaction=interaction,
            thief=interaction.user,
            target=user,
            steal_cap=0.3,
            followup=False,
        )


# ── setup ──────────────────────────────────────────────────────────
async def setup(bot, db):
    await bot.add_cog(Steal(bot, db))
