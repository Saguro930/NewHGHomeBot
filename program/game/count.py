import discord
from discord.ext import commands
from discord import app_commands
import re
import ast
import operator
import math

# 安全な演算子だけ許可
OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

def preprocess(expr: str) -> str:
    """√4+1 → sqrt(4)+1、√(4+1) → sqrt(4+1) に変換する"""
    # √(... ) → sqrt(... )
    expr = re.sub(r"√\(", "sqrt(", expr)
    # √数字 → sqrt(数字)
    expr = re.sub(r"√(\d+)", r"sqrt(\1)", expr)
    return expr

def safe_eval(expr: str) -> int | None:
    try:
        expr = preprocess(expr)
        node = ast.parse(expr, mode="eval").body
        result = _eval_node(node)
        # 結果が整数に変換できる場合のみ許可（√の結果が整数でない場合は弾く）
        if isinstance(result, float):
            if result.is_integer():
                return int(result)
            return None
        return int(result)
    except Exception:
        return None

def _eval_node(node):
    # Python 3.8+ は ast.Constant を使う（ast.Num は非推奨）
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.Num):  # 旧バージョン互換
        return node.n
    if isinstance(node, ast.BinOp) and type(node.op) in OPERATORS:
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        return OPERATORS[type(node.op)](left, right)
    # √x → x**0.5 のための単項処理（ast.Call で sqrt(x) 形式）
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id == "sqrt":
            if len(node.args) == 1:
                arg = _eval_node(node.args[0])
                return math.sqrt(arg)
    raise ValueError("Invalid expression")


class Count(commands.Cog):
    def __init__(self, bot: commands.Bot, db):
        self.bot = bot
        self.db = db

    # ── Firestore 参照 ────────────────────────────────────────────

    def count_ref(self, guild_id: int):
        return (
            self.db.collection("guilds")
            .document(str(guild_id))
            .collection("count")
            .document("data")
        )

    # -----------------------------
    # メッセージ監視
    # -----------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        doc_ref = self.count_ref(message.guild.id)
        doc = doc_ref.get()
        if not doc.exists:
            return

        data = doc.to_dict()
        count_channel = data.get("channel")
        current_count = data.get("count", 1)
        recent_authors: list = data.get("recent_authors", [])

        if not count_channel or message.channel.id != int(count_channel):
            return

        content = message.content.replace(" ", "")
        # sqrt() と数字・演算子を許可
        if not re.fullmatch(r"[0-9+\-*/%\*\*()sqrta-z√]+", content):
            return

        value = safe_eval(content)
        if value is None:
            return

        author_id = message.author.id

        # -----------------------------
        # 連続投稿チェック
        # -----------------------------
        if len(recent_authors) >= 4 and all(uid == author_id for uid in recent_authors[-4:]):
            doc_ref.update({
                "count": 1,
                "recent_authors": [],
                "last_correct_message_id": None,
                "mistakes": data.get("mistakes", 0) + 1,
            })
            await message.add_reaction("🚫")
            await message.channel.send(
                f"🚫 {message.author.mention} が5回連続で投稿しました！\n"
                f"🔁 **1 からやり直しになりました You are 戦犯！**"
            )
            return

        # -----------------------------
        # 正誤判定
        # -----------------------------
        if value == current_count:
            new_history = (recent_authors + [author_id])[-4:]
            doc_ref.update({
                "count": current_count + 1,
                "recent_authors": new_history,
                "last_correct_message_id": message.id,
                "corrects": data.get("corrects", 0) + 1,
                "best": max(data.get("best", 0), current_count),
            })
            await message.add_reaction("✅")
        else:
            doc_ref.update({
                "count": 1,
                "recent_authors": [],
                "last_correct_message_id": None,
                "mistakes": data.get("mistakes", 0) + 1,
            })
            await message.add_reaction("❌")
            await message.channel.send(
                f"❌ 間違いです！\n"
                f"正解は **{current_count}** です。\n"
                f"🔁 **1 からやり直しになりました You are 戦犯！**"
            )

    # -----------------------------
    # メッセージ削除監視
    # -----------------------------
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild:
            return

        doc = self.count_ref(message.guild.id).get()
        if not doc.exists:
            return

        data = doc.to_dict()
        count_channel = data.get("channel")
        last_id = data.get("last_correct_message_id")
        current_count = data.get("count", 1)

        if not count_channel or message.channel.id != int(count_channel):
            return

        if last_id and message.id == last_id:
            await message.channel.send(
                f"🗑️ 最新の数字が削除されたので再送します\n"
                f"➡️ **次は `{current_count}` です**"
            )

    # -----------------------------
    # /count-stats
    # -----------------------------
    @app_commands.command(name="count-stats", description="カウントゲームの統計を表示します")
    async def count_stats(self, interaction: discord.Interaction):
        doc = self.count_ref(interaction.guild.id).get()

        if not doc.exists:
            await interaction.response.send_message("❌ データが見つかりません。", ephemeral=True)
            return

        data = doc.to_dict()
        best = data.get("best", 0)
        total_correct = data.get("corrects", 0)
        total_mistake = data.get("mistakes", 0)
        total = total_correct + total_mistake
        accuracy = f"{total_correct / total * 100:.1f}%" if total > 0 else "N/A"

        embed = discord.Embed(title="📊 カウントゲーム 統計", color=0x1DA1F2)
        embed.add_field(name="🏆 最高記録", value=f"`{best}`", inline=True)
        embed.add_field(name="✅ 総正解数", value=f"`{total_correct}` 回", inline=True)
        embed.add_field(name="❌ 総ミス数", value=f"`{total_mistake}` 回", inline=True)
        embed.add_field(name="🎯 正解率", value=f"`{accuracy}`", inline=True)

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot, db):
    await bot.add_cog(Count(bot, db))
