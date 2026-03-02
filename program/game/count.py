import discord
from discord.ext import commands
from discord import app_commands
import re
import ast
import operator
import math

# =============================
# 安全な演算子
# =============================
OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.floordiv,  # 割り算は切り捨て
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,       # ** 対応
}

# =============================
# 前処理： ^ → ** / √ → sqrt()
# =============================
def preprocess(expr: str) -> str:
    expr = expr.replace("^", "**")

    # √9 / √(16+9) → sqrt(9) / sqrt(16+9)
    expr = re.sub(
        r"√(\d+|\([^()]+\))",
        lambda m: f"sqrt{m.group(1)}",
        expr
    )
    return expr

# =============================
# 安全 eval
# =============================
def safe_eval(expr: str) -> int | None:
    try:
        expr = preprocess(expr)
        node = ast.parse(expr, mode="eval").body
        return int(_eval_node(node))
    except Exception:
        return None

def _eval_node(node):
    if isinstance(node, ast.Num):  # Python <=3.10
        return node.n

    if isinstance(node, ast.Constant):  # Python 3.11+
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError

    if isinstance(node, ast.BinOp) and type(node.op) in OPERATORS:
        return OPERATORS[type(node.op)](
            _eval_node(node.left),
            _eval_node(node.right)
        )

    # sqrt(x)
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id == "sqrt":
            value = _eval_node(node.args[0])
            if value < 0:
                raise ValueError
            return int(math.sqrt(value))

    raise ValueError("Invalid expression")

# =============================
# MVP / 戦犯 算出
# =============================
def get_mvp(user_stats: dict):
    if not user_stats:
        return None
    uid, stats = max(user_stats.items(), key=lambda x: x[1].get("success", 0))
    return {"user_id": uid, "success_count": stats.get("success", 0)}

def get_warcriminal(user_stats: dict):
    if not user_stats:
        return None
    uid, stats = max(user_stats.items(), key=lambda x: x[1].get("fail", 0))
    return {"user_id": uid, "fail_count": stats.get("fail", 0)}

# =============================
# Cog
# =============================
class Count(commands.Cog):
    def __init__(self, bot: commands.Bot, db):
        self.bot = bot
        self.db = db

    # -----------------------------
    # メッセージ監視
    # -----------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        doc_ref = self.db.collection("guilds").document(str(message.guild.id))
        doc = doc_ref.get()
        if not doc.exists:
            return

        data = doc.to_dict()
        count_channel = data.get("count_channel")
        count = data.get("count", {})

        if message.channel.id != count_channel:
            return

        content = message.content.replace(" ", "")
        if not re.fullmatch(r"[0-9+\-*/%^().√]+", content):
            return

        value = safe_eval(content)
        if value is None:
            return

        # 現在の状態
        current = count.get("current", 1)
        recent_authors = count.get("recent_authors", [])
        user_stats = count.get("user_stats", {})

        uid = str(message.author.id)
        if uid not in user_stats:
            user_stats[uid] = {"success": 0, "fail": 0}

        # -----------------------------
        # 5連投チェック
        # -----------------------------
        if len(recent_authors) >= 4 and all(a == uid for a in recent_authors[-4:]):
            user_stats[uid]["fail"] += 1

            doc_ref.update({
                "count": {
                    "current": 1,
                    "recent_authors": [],
                    "last_correct_message_id": None,
                    "total_success": count.get("total_success", 0),
                    "total_fail": count.get("total_fail", 0) + 1,
                    "user_stats": user_stats,
                    "mvp": get_mvp(user_stats),
                    "warcriminal": get_warcriminal(user_stats)
                }
            })

            await message.add_reaction("🚫")
            await message.channel.send(
                f"🚫 {message.author.mention} が5連投！\n"
                f"🔁 **1からやり直し（戦犯）**"
            )
            return

        # -----------------------------
        # 正誤判定
        # -----------------------------
        if value == current:
            user_stats[uid]["success"] += 1
            new_history = (recent_authors + [uid])[-4:]

            doc_ref.update({
                "count": {
                    "current": current + 1,
                    "recent_authors": new_history,
                    "last_correct_message_id": message.id,
                    "total_success": count.get("total_success", 0) + 1,
                    "total_fail": count.get("total_fail", 0),
                    "user_stats": user_stats,
                    "mvp": get_mvp(user_stats),
                    "warcriminal": get_warcriminal(user_stats)
                }
            })

            await message.add_reaction("✅")

        else:
            user_stats[uid]["fail"] += 1

            doc_ref.update({
                "count": {
                    "current": 1,
                    "recent_authors": [],
                    "last_correct_message_id": None,
                    "total_success": count.get("total_success", 0),
                    "total_fail": count.get("total_fail", 0) + 1,
                    "user_stats": user_stats,
                    "mvp": get_mvp(user_stats),
                    "warcriminal": get_warcriminal(user_stats)
                }
            })

            await message.add_reaction("❌")
            await message.channel.send(
                f"❌ 間違い！正解は **{current}**\n"
                f"🔁 **1からやり直し（戦犯）**"
            )

    # -----------------------------
    # メッセージ削除監視
    # -----------------------------
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild:
            return

        doc = self.db.collection("guilds").document(str(message.guild.id)).get()
        if not doc.exists:
            return

        count = doc.to_dict().get("count", {})
        if message.id == count.get("last_correct_message_id"):
            await message.channel.send(
                f"🗑️ 最新の数字が削除されたよ\n"
                f"➡️ **次は `{count.get('current', 1)}`**"
            )

    # -----------------------------
    # /countstatus
    # -----------------------------
    @app_commands.command(name="countstatus", description="このサーバーのカウント統計を表示します")
    async def countstatus(self, interaction: discord.Interaction):
        doc = self.db.collection("guilds").document(str(interaction.guild.id)).get()
        if not doc.exists:
            await interaction.response.send_message("📊 データがありません", ephemeral=True)
            return

        count = doc.to_dict().get("count", {})
        user_stats = count.get("user_stats", {})

        uid = str(interaction.user.id)
        my = user_stats.get(uid, {"success": 0, "fail": 0})

        def name(uid):
            if not uid:
                return "なし"
            m = interaction.guild.get_member(int(uid))
            return m.mention if m else "不明"

        mvp = count.get("mvp")
        wc = count.get("warcriminal")

        msg = (
            f"📊 **カウント統計**\n\n"
            f"🔢 現在：**{count.get('current', 1)}**\n"
            f"✅ 成功：{count.get('total_success', 0)}\n"
            f"❌ 失敗：{count.get('total_fail', 0)}\n\n"
            f"🏆 MVP：{name(mvp['user_id']) if mvp else 'なし'}"
            f"（{mvp.get('success_count', 0) if mvp else 0}）\n"
            f"💥 戦犯：{name(wc['user_id']) if wc else 'なし'}"
            f"（{wc.get('fail_count', 0) if wc else 0}）\n\n"
            f"🙋 あなた\n"
            f"✅ {my['success']} / ❌ {my['fail']}"
        )

        await interaction.response.send_message(msg)

# =============================
# setup
# =============================
async def setup(bot: commands.Bot, db):
    await bot.add_cog(Count(bot, db))
