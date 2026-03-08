import asyncio
import discord
from discord.ext import commands
from discord import app_commands
import re
import ast
import operator
import math
import logging

logger = logging.getLogger("count_cog")
logging.basicConfig(level=logging.INFO)

# =============================
# 安全な演算子（ASTノード -> Python関数）
# =============================
OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.floordiv,  # 切り捨て整数除算
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,       # ** に対応
}

# =============================
# 文字正規化：全角→半角 等
# =============================
FULLWIDTH_MAP = str.maketrans({
    '０':'0','１':'1','２':'2','３':'3','４':'4','５':'5','６':'6','７':'7','８':'8','９':'9',
    '＋':'+','－':'-','＊':'*','／':'/','％':'%','＾':'^',
    '（':'(','）':')','．':'.','　':' ',
    '√':'√'
})

def normalize_input(s: str) -> str:
    return s.translate(FULLWIDTH_MAP)

# =============================
# 前処理：^ -> ** , √ を sqrt(...) にする等
# =============================
def preprocess(expr: str) -> str:
    expr = normalize_input(expr)
    expr = expr.replace("^", "**")
    expr = expr.replace("√", "sqrt")
    expr = re.sub(r"sqrt\s*(\d+(\.\d+)?)", lambda m: f"sqrt({m.group(1)})", expr)
    expr = expr.strip()
    return expr

# =============================
# 安全 eval（ASTベース）
# =============================
def safe_eval(expr: str) -> int | None:
    try:
        expr = preprocess(expr)
        if not re.fullmatch(r"[0-9+\-*/%^().sqrt\s*]+", expr):
            return None

        node = ast.parse(expr, mode="eval").body
        val = _eval_node(node)
        return int(val)
    except Exception as e:
        logger.debug("safe_eval failed for %r: %s", expr, e, exc_info=True)
        return None

def _eval_node(node):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("Invalid constant type")
    if isinstance(node, ast.Num):  # Python <=3.10
        return node.n

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval_node(node.operand)

    if isinstance(node, ast.BinOp) and type(node.op) in OPERATORS:
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        return OPERATORS[type(node.op)](left, right)

    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id == "sqrt":
            if len(node.args) != 1:
                raise ValueError("sqrt takes exactly one argument")
            value = _eval_node(node.args[0])
            if value < 0:
                raise ValueError("sqrt of negative")
            return math.sqrt(value)
        raise ValueError("Only sqrt() is allowed as function")

    raise ValueError("Invalid expression node")

# =============================
# MVP / 戦犯 算出ユーティリティ
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
# Cog 本体
# =============================
class Count(commands.Cog):
    def __init__(self, bot: commands.Bot, db):
        self.bot = bot
        self.db = db

    def _get_guild_ref(self, guild_id: int):
        return self.db.collection("guilds").document(str(guild_id))

    # -----------------------------
    # メッセージ監視
    # -----------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        try:
            doc_ref = self._get_guild_ref(message.guild.id)
            # [FIX 2] ブロッキング Firestore 呼び出しを別スレッドで実行
            doc = await asyncio.to_thread(doc_ref.get)
            if not doc.exists:
                return

            data = doc.to_dict()
            count_channel = data.get("count_channel")

            # [FIX 1] count_channel が str で保存されている場合に int へ変換して比較
            if not count_channel or message.channel.id != int(count_channel):
                return

            count = data.get("count", {})

            content_raw = message.content
            content = re.sub(r"\s+", "", normalize_input(content_raw))

            if not re.fullmatch(r"[0-9+\-*/%^().√]+", content):
                return

            value = safe_eval(content)
            if value is None:
                return

            current = int(count.get("current", 1))
            recent_authors = count.get("recent_authors", [])
            user_stats = count.get("user_stats", {})

            uid = str(message.author.id)
            if uid not in user_stats:
                user_stats[uid] = {"success": 0, "fail": 0}

            # -----------------------------
            # 5連投チェック（直近4件が同一ユーザー）
            # -----------------------------
            if len(recent_authors) >= 4 and all(a == uid for a in recent_authors[-4:]):
                user_stats[uid]["fail"] += 1

                new_count_obj = {
                    "current": 1,
                    "recent_authors": [],
                    "last_correct_message_id": None,
                    "total_success": count.get("total_success", 0),
                    "total_fail": count.get("total_fail", 0) + 1,
                    "user_stats": user_stats,
                    "mvp": get_mvp(user_stats),
                    "warcriminal": get_warcriminal(user_stats)
                }
                # [FIX 2] 同上
                await asyncio.to_thread(doc_ref.update, {"count": new_count_obj})

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

                new_count_obj = {
                    "current": current + 1,
                    "recent_authors": new_history,
                    "last_correct_message_id": message.id,
                    "total_success": count.get("total_success", 0) + 1,
                    "total_fail": count.get("total_fail", 0),
                    "user_stats": user_stats,
                    "mvp": get_mvp(user_stats),
                    "warcriminal": get_warcriminal(user_stats)
                }

                await asyncio.to_thread(doc_ref.update, {"count": new_count_obj})
                await message.add_reaction("✅")
            else:
                user_stats[uid]["fail"] += 1

                new_count_obj = {
                    "current": 1,
                    "recent_authors": [],
                    "last_correct_message_id": None,
                    "total_success": count.get("total_success", 0),
                    "total_fail": count.get("total_fail", 0) + 1,
                    "user_stats": user_stats,
                    "mvp": get_mvp(user_stats),
                    "warcriminal": get_warcriminal(user_stats)
                }

                await asyncio.to_thread(doc_ref.update, {"count": new_count_obj})
                await message.add_reaction("❌")
                await message.channel.send(
                    f"❌ 間違い！正解は **{current}**\n"
                    f"🔁 **1からやり直し（戦犯）**"
                )

        except Exception as e:
            logger.exception("on_message handler failed: %s", e)

    # -----------------------------
    # メッセージ削除監視
    # -----------------------------
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild:
            return

        try:
            doc_ref = self._get_guild_ref(message.guild.id)
            # [FIX 2] 同上
            doc = await asyncio.to_thread(doc_ref.get)
            if not doc.exists:
                return

            count = doc.to_dict().get("count", {})
            if message.id == count.get("last_correct_message_id"):
                await message.channel.send(
                    f"🗑️ 最新の数字が削除されたよ\n"
                    f"➡️ **次は `{count.get('current', 1)}`**"
                )
        except Exception:
            logger.exception("on_message_delete failed")

    # -----------------------------
    # /countstatus (slash)
    # -----------------------------
    @app_commands.command(name="countstatus", description="このサーバーのカウント統計を表示します")
    async def countstatus(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer()
        except Exception:
            logger.debug("defer failed; continuing", exc_info=True)

        try:
            guild = interaction.guild
            if not guild:
                await interaction.followup.send("❌ サーバー内で実行してください", ephemeral=True)
                return

            doc_ref = self._get_guild_ref(guild.id)
            # [FIX 2] 同上
            doc = await asyncio.to_thread(doc_ref.get)
            if not doc.exists:
                await interaction.followup.send("📊 データがありません", ephemeral=True)
                return

            count = doc.to_dict().get("count", {})
            user_stats = count.get("user_stats", {})

            uid = str(interaction.user.id)
            my = user_stats.get(uid, {"success": 0, "fail": 0})

            def name(uid_value):
                if not uid_value:
                    return "なし"
                m = guild.get_member(int(uid_value))
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

            await interaction.followup.send(msg)

        except Exception as e:
            logger.exception("countstatus failed: %s", e)
            try:
                await interaction.followup.send("⚠️ 統計の読み込み中にエラーが発生しました。管理者にログを確認してください。")
            except Exception:
                logger.debug("failed to send followup error message", exc_info=True)

# =============================
# setup
# =============================
async def setup(bot: commands.Bot, db):
    await bot.add_cog(Count(bot, db))
