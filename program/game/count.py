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
    # 全角→半角等の基本正規化、空白は残す（後で削る）
    return s.translate(FULLWIDTH_MAP)

# =============================
# 前処理：^ -> ** , √ を sqrt(...) にする等
# より頑健な処理を行う（例：√9 -> sqrt(9) , √(4+5) -> sqrt(4+5)）
# =============================
def preprocess(expr: str) -> str:
    expr = normalize_input(expr)
    expr = expr.replace("^", "**")

    # '√' を 'sqrt' に置換して、数値直後の場合は括弧で囲む
    # 例: sqrt9 -> sqrt(9)
    # 例: sqrt( ... ) はそのまま
    expr = expr.replace("√", "sqrt")

    # sqrt followed by digits (possibly with spaces): sqrt  9  -> sqrt(9)
    expr = re.sub(r"sqrt\s*(\d+(\.\d+)?)", lambda m: f"sqrt({m.group(1)})", expr)

    # sqrt( はそのまま。これ handles sqrt( ... )
    # 不要な空白を削除（演算子間の空白は気にしないため全体で strip）
    expr = expr.strip()
    return expr

# =============================
# 安全 eval（ASTベース）
# - 許可されたノードだけ評価
# - sqrt() は許可（引数は評価してから math.sqrt）
# - 結果は int にキャスト（小数は切り捨て）
# =============================
def safe_eval(expr: str) -> int | None:
    try:
        expr = preprocess(expr)
        # セーフチェック：allow only characters we expect after preprocess
        if not re.fullmatch(r"[0-9+\-*/%^().sqrt\s*]+", expr):
            # ここでは sqrt が入った文字列も許可
            # ただし念のため厳しく弾く（アルファベット等は 'sqrt' のみ許可）
            # 例外ではなく None を返して静かに無視する運用にしている
            return None

        node = ast.parse(expr, mode="eval").body
        val = _eval_node(node)
        # 最終的に整数で扱う（小数は切り捨て）
        return int(val)
    except Exception as e:
        logger.debug("safe_eval failed for %r: %s", expr, e, exc_info=True)
        return None

def _eval_node(node):
    # 数値リテラル (Pythonバージョンに合わせて対応)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("Invalid constant type")
    if isinstance(node, ast.Num):  # Python <=3.10
        return node.n

    # 単項演算子（負号）
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval_node(node.operand)

    # 二項演算
    if isinstance(node, ast.BinOp) and type(node.op) in OPERATORS:
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        # 防御: rightが0での除算などが来た場合は例外させる
        return OPERATORS[type(node.op)](left, right)

    # 関数呼び出し（sqrt のみ許可）
    if isinstance(node, ast.Call):
        # 形式: sqrt(<expr>)
        if isinstance(node.func, ast.Name) and node.func.id == "sqrt":
            # 1引数のみ許可
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
    # success が最大の user を返す
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

    # -----------------------------
    # メッセージ監視
    # -----------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # bot の発言は無視
        if message.author.bot or not message.guild:
            return

        try:
            doc_ref = self.db.collection("guilds").document(str(message.guild.id))
            doc = doc_ref.get()  # Firestore の同期 API を想定
            if not doc.exists:
                return

            data = doc.to_dict()
            count_channel = data.get("count_channel")
            count = data.get("count", {})

            if message.channel.id != count_channel:
                return

            # 正規化：全角→半角、空白除去は safe_eval 前に行う
            content_raw = message.content
            content = re.sub(r"\s+", "", normalize_input(content_raw))

            # 許可する文字だけか（数字、演算子、括弧、√など）
            if not re.fullmatch(r"[0-9+\-*/%^().√]+", content):
                return

            value = safe_eval(content)
            if value is None:
                return

            # 現在の状態を読み出し
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
                # Firestore の上書き（ここはトランザクションで扱うのが望ましい）
                doc_ref.update({"count": new_count_obj})

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

                doc_ref.update({"count": new_count_obj})
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

                doc_ref.update({"count": new_count_obj})
                await message.add_reaction("❌")
                await message.channel.send(
                    f"❌ 間違い！正解は **{current}**\n"
                    f"🔁 **1からやり直し（戦犯）**"
                )

        except Exception as e:
            # ここで swallow せずログ出しておく
            logger.exception("on_message handler failed: %s", e)

    # -----------------------------
    # メッセージ削除監視
    # -----------------------------
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        # メッセージ削除後の通知（最新正解が消えたら知らせる）
        if not message.guild:
            return

        try:
            doc = self.db.collection("guilds").document(str(message.guild.id)).get()
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
        # Interaction は 3 秒以内の応答が必要 → DB等で時間かかる可能性があるため defer する
        try:
            await interaction.response.defer()  # thinking
        except Exception:
            # defer に失敗しても続行して try で followup 送る
            logger.debug("defer failed; continuing", exc_info=True)

        try:
            guild = interaction.guild
            if not guild:
                await interaction.followup.send("❌ サーバー内で実行してください", ephemeral=True)
                return

            doc = self.db.collection("guilds").document(str(guild.id)).get()
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
            # 可能ならユーザーにエラーメッセージを送る（非エフェメラル）
            try:
                await interaction.followup.send("⚠️ 統計の読み込み中にエラーが発生しました。管理者にログを確認してください。")
            except Exception:
                logger.debug("failed to send followup error message", exc_info=True)

# =============================
# setup
# =============================
# NOTE: 環境によって setup シグネチャが異なるので既存の呼び出し方に合わせてください。
# 例:
#   await bot.add_cog(Count(bot, db))
# または拡張機能として読み込む場合、db を bot に設定しておきます（例: bot.db = db）
async def setup(bot: commands.Bot, db):
    await bot.add_cog(Count(bot, db))
