import discord
from discord import app_commands, Interaction
from discord.ext import commands
from datetime import datetime, timedelta
import random

# ── 職業テーブル（レベル帯ごとに職業名・仕事内容が変わる）────────
JOB_TABLE = [
    # (最小Lv, 職業名, [(仕事内容, コイン倍率)])
    (1,  "🧹 清掃員",    [
        ("ゴミを集めて回った",       1.0),
        ("トイレを磨いた",           0.9),
        ("廊下をモップで拭いた",     1.1),
    ]),
    (3,  "🍔 店員",      [
        ("レジを打ち続けた",         1.2),
        ("接客で笑顔を振りまいた",   1.1),
        ("フライヤーで揚げ続けた",   1.3),
    ]),
    (5,  "🔧 整備士",    [
        ("エンジンをオーバーホールした", 1.5),
        ("タイヤ交換を5台こなした",      1.4),
        ("油まみれになって修理した",     1.6),
    ]),
    (8,  "👨‍💻 プログラマー", [
        ("バグを10個潰した",             1.8),
        ("徹夜でデプロイした",           2.0),
        ("コードレビューをこなした",     1.7),
    ]),
    (12, "⚕️ 医師",      [
        ("夜間救急を担当した",           2.5),
        ("難しい手術を成功させた",       3.0),
        ("大勢の患者を診察した",         2.3),
    ]),
    (18, "🏦 投資家",    [
        ("市場を読んで大勝ちした",       3.5),
        ("先物取引で利益を得た",         4.0),
        ("ヘッジファンドを運用した",     3.8),
    ]),
    (25, "🚀 CEO",       [
        ("企業買収を成功させた",         5.0),
        ("IPOを指揮した",               5.5),
        ("世界規模の契約を締結した",     6.0),
    ]),
]

# ── ランダムイベント ───────────────────────────────────────────────
EVENTS = [
    # (確率weight, 絵文字, テキスト, コイン倍率, expボーナス)
    (40, "",   None,                                     1.0,  0),    # 通常
    (20, "🌟", "残業を頼まれた！ボーナスが入った！",     1.5,  5),
    (15, "🤝", "顧客に気に入られ臨時報酬をもらった！",  1.3,  3),
    (10, "📈", "成果を評価されて特別手当が出た！",       2.0,  8),
    (10, "😴", "ミスをして給料が少し引かれた…",         0.6, -2),
    (5,  "🎰", "仕事中にギャンブルが当たった！！",       3.0, 10),
]


def get_job(level: int) -> tuple[str, list]:
    """レベルに対応する職業を返す（最大レベル帯を優先）"""
    job = JOB_TABLE[0]
    for min_lv, name, tasks in JOB_TABLE:
        if level >= min_lv:
            job = (min_lv, name, tasks)
    return job[1], job[2]


def roll_event():
    weights = [e[0] for e in EVENTS]
    return random.choices(EVENTS, weights=weights, k=1)[0]


def streak_bonus(streak: int) -> float:
    """連続労働ストリークのコイン倍率（最大 +50%）"""
    return min(0.05 * streak, 0.5)


class Coin(commands.Cog):
    def __init__(self, bot, db):
        self.bot = bot
        self.db = db

    def get_user_ref(self, user_id):
        return self.db.collection("users").document(str(user_id))

    async def get_user_data(self, user_id):
        doc = self.get_user_ref(user_id).get()
        data = doc.to_dict() if doc.exists else {}
        data.setdefault("coins", 0)
        data.setdefault("work_level", 1)
        data.setdefault("work_exp", 0)
        data.setdefault("last_work", None)
        data.setdefault("last_daily", None)
        data.setdefault("streak", 0)
        data.setdefault("work_locked_until", None)
        data.setdefault("work_streak", 0)        # 連続労働ストリーク
        data.setdefault("total_earned", 0)       # 累計獲得コイン
        return data

    async def set_user_data(self, user_id, data):
        self.get_user_ref(user_id).set(data, merge=True)

    async def add_coins(self, user_id, amount):
        ref = self.get_user_ref(user_id)
        doc = ref.get()
        coins = (doc.to_dict().get("coins", 0) if doc.exists else 0) + amount
        ref.set({"coins": coins}, merge=True)
        return coins

    async def remove_coins(self, user_id, amount):
        ref = self.get_user_ref(user_id)
        doc = ref.get()
        coins = doc.to_dict().get("coins", 0) if doc.exists else 0
        if coins < amount:
            return False
        ref.set({"coins": coins - amount}, merge=True)
        return True

    # ── /give_coin ────────────────────────────────────────────────
    @app_commands.command(name="give_coin", description="指定ユーザーにコインを渡す")
    @app_commands.describe(user="受け取るユーザー", price="渡すコイン数")
    async def give_coin(self, interaction: Interaction, user: discord.Member, price: int):
        if price <= 0:
            await interaction.response.send_message("❌ 1以上の値を指定してください。", ephemeral=True)
            return
        if not await self.remove_coins(interaction.user.id, price):
            await interaction.response.send_message("❌ コインが不足しています。", ephemeral=True)
            return
        await self.add_coins(user.id, price)
        await interaction.response.send_message(
            f"✅ {user.display_name} に **{price:,} コイン** を渡しました！"
        )

    # ── /work ─────────────────────────────────────────────────────
    @app_commands.command(name="work", description="仕事をしてコインと経験値を得る（4時間ごと）")
    async def work(self, interaction: Interaction):
        user_id = interaction.user.id
        data = await self.get_user_data(user_id)
        now = datetime.utcnow()

        # 🔒 窃盗失敗ロックチェック
        lock_str = data.get("work_locked_until")
        if lock_str:
            locked_until = datetime.fromisoformat(lock_str)
            if now < locked_until:
                remaining = locked_until - now
                h, m = remaining.seconds // 3600, (remaining.seconds % 3600) // 60
                await interaction.response.send_message(
                    f"🔒 **窃盗失敗ペナルティ中**\n⏳ 解除まであと **{h}時間 {m}分**",
                    ephemeral=True
                )
                return

        # ⏳ クールダウンチェック（4時間）
        last_work = data.get("last_work")
        if last_work:
            last_time = datetime.fromisoformat(last_work)
            elapsed = now - last_time
            if elapsed < timedelta(hours=4):
                remaining = timedelta(hours=4) - elapsed
                h, m, s = (
                    remaining.seconds // 3600,
                    (remaining.seconds % 3600) // 60,
                    remaining.seconds % 60,
                )
                await interaction.response.send_message(
                    f"⏳ まだ休憩中です…\nあと **{h}時間 {m}分 {s}秒** で働けます。",
                    ephemeral=True
                )
                return

        # ── ストリーク更新 ─────────────────────────────────────────
        if last_work:
            last_time = datetime.fromisoformat(last_work)
            # 8時間以内に再労働でストリーク継続、それ以外はリセット
            if elapsed < timedelta(hours=8):
                data["work_streak"] = data.get("work_streak", 0) + 1
            else:
                data["work_streak"] = 1
        else:
            data["work_streak"] = 1
        work_streak = data["work_streak"]

        # ── 職業・タスク決定 ───────────────────────────────────────
        level = data["work_level"]
        job_name, tasks = get_job(level)
        task_text, task_multiplier = random.choice(tasks)

        # ── ランダムイベント ────────────────────────────────────────
        _, ev_emoji, ev_text, ev_multiplier, ev_exp = roll_event()

        # ── 報酬計算 ────────────────────────────────────────────────
        base_coins = random.randint(50, 100) * level
        sb = streak_bonus(work_streak)
        total_multiplier = task_multiplier * ev_multiplier * (1 + sb)
        earned_coins = int(base_coins * total_multiplier)

        base_exp = random.randint(15, 30)
        earned_exp = max(0, base_exp + ev_exp)

        data["coins"] += earned_coins
        data["work_exp"] += earned_exp
        data["total_earned"] = data.get("total_earned", 0) + earned_coins
        data["last_work"] = now.isoformat()

        # ── レベルアップ判定 ────────────────────────────────────────
        leveled_up = False
        new_job = None
        while data["work_exp"] >= data["work_level"] * 100:
            data["work_exp"] -= data["work_level"] * 100
            data["work_level"] += 1
            leveled_up = True
            new_job, _ = get_job(data["work_level"])

        await self.set_user_data(user_id, data)

        # ── Embed 構築 ──────────────────────────────────────────────
        color = 0xF1C40F if ev_multiplier >= 2.0 else (0xE74C3C if ev_multiplier < 1.0 else 0x2ECC71)

        embed = discord.Embed(
            title=f"{job_name}　として働いた",
            description=f"*{task_text}*",
            color=color
        )

        # イベント
        if ev_text:
            embed.add_field(name=f"{ev_emoji} イベント", value=ev_text, inline=False)

        # 報酬
        multiplier_text = ""
        if task_multiplier != 1.0:
            multiplier_text += f"　職業補正 ×{task_multiplier:.1f}"
        if ev_multiplier != 1.0:
            multiplier_text += f"　イベント ×{ev_multiplier:.1f}"
        if sb > 0:
            multiplier_text += f"　ストリーク +{int(sb*100)}%"

        embed.add_field(
            name="💰 獲得コイン",
            value=f"**+{earned_coins:,}** コイン{multiplier_text}",
            inline=True
        )
        embed.add_field(
            name="✨ 経験値",
            value=f"**+{earned_exp}** exp",
            inline=True
        )

        # レベル進捗
        next_exp = data["work_level"] * 100
        filled = int(data["work_exp"] / next_exp * 10)
        bar = "█" * filled + "░" * (10 - filled)
        embed.add_field(
            name=f"📊 Lv.{data['work_level']}　進捗",
            value=f"`{bar}` {data['work_exp']}/{next_exp} exp",
            inline=False
        )

        # ストリーク
        if work_streak > 1:
            embed.add_field(
                name="🔥 連続労働",
                value=f"**{work_streak}** 回連続　+{int(sb*100)}% ボーナス中",
                inline=True
            )

        # レベルアップ通知
        if leveled_up:
            embed.add_field(
                name="🎉 レベルアップ！",
                value=f"**Lv.{data['work_level']}** になりました！"
                      + (f"\n職業が **{new_job}** に変わった！" if new_job and new_job != job_name else ""),
                inline=False
            )
            embed.color = 0xFFD700

        embed.set_footer(text=f"累計獲得: {data['total_earned']:,} コイン　•　次の労働まで 4時間")
        embed.set_author(
            name=interaction.user.display_name,
            icon_url=interaction.user.display_avatar.url
        )

        await interaction.response.send_message(embed=embed)


async def setup(bot, db):
    await bot.add_cog(Coin(bot, db))
