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
    expr = re.sub(r"√\(", "sqrt(", expr)
    expr = re.sub(r"√(\d+)", r"sqrt(\1)", expr)
    return expr

def safe_eval(expr: str) -> int | None:
    try:
        expr = preprocess(expr)
        node = ast.parse(expr, mode="eval").body
        result = _eval_node(node)
        if isinstance(result, float):
            return int(result) if result.is_integer() else None
        return int(result)
    except Exception:
        return None

def _eval_node(node):
    # Python 3.8+ は ast.Constant（ast.Num は非推奨）
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.Num):  # 旧バージョン互換
        return node.n
    if isinstance(node, ast.BinOp) and type(node.op) in OPERATORS:
        return OPERATORS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id == "sqrt" and len(node.args) == 1:
            return math.sqrt(_eval_node(node.args[0]))
    raise ValueError("Invalid expression")


class Count(commands.Cog):
    def __init__(self, bot: commands.Bot, db):
        self.bot = bot
        self.db = db

    def count_ref(self, guild_id: int):
        return (
            self.db.collection("guilds")
            .document(str(guild_id))
            .collection("count")
            .document("data")
        )

    # ── メッセージ監視 ────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        try:
            doc_ref = self.count_ref(message.guild.id)
            doc = doc_ref.get()
            if not doc.exists:
                return

            data = doc.to_dict()
            count_channel = data.get("channel")
            if not count_channel:
                return

            # Firestore は int/str どちらで保存されているか不定なので両方対応
            if message.channel.id != int(count_channel):
                return

            content = message.content.replace(" ", "")
            if not re.fullmatch(r"[0-9+\-*/%\*\*()sqrta-z√]+", content):
                return

            value = safe_eval(content)
            if value is None:
                return

            current_count = data.get("count", 1)
            # Firestore から取得した author IDs を確実に int に変換
            recent_authors = [int(uid) for uid in data.get("recent_authors", [])]
            author_id = message.author.id

            # 連続投稿チェック（同一ユーザーが直近4投稿を独占）
            if len(recent_authors) >= 4 and all(uid == author_id for uid in recent_authors[-4:]):
                doc_ref.set({
                    "count": 1,
                    "recent_authors": [],
                    "last_correct_message_id": None,
                    "mistakes": data.get("mistakes", 0) + 1,
                }, merge=True)
                await message.add_reaction("🚫")
                await message.channel.send(
                    f"🚫 {message.author.mention} が5回連続で投稿しました！\n"
                    f"🔁 **1 からやり直しになりました You are 戦犯！**"
                )
                return

            # 正誤判定
            if value == current_count:
                new_history = (recent_authors + [author_id])[-4:]
                doc_ref.set({
                    "count": current_count + 1,
                    "recent_authors": new_history,
                    "last_correct_message_id": message.id,
                    "corrects": data.get("corrects", 0) + 1,
                    "best": max(data.get("best", 0), current_count),
                }, merge=True)
                await message.add_reaction("✅")
            else:
                doc_ref.set({
                    "count": 1,
                    "recent_authors": [],
                    "last_correct_message_id": None,
                    "mistakes": data.get("mistakes", 0) + 1,
                }, merge=True)
                await message.add_reaction("❌")
                await message.channel.send(
                    f"❌ 間違いです！\n"
                    f"正解は **{current_count}** です。\n"
                    f"🔁 **1 からやり直しになりました You are 戦犯！**"
                )

        except Exception as e:
            print(f"[Count] on_message エラー: {e}")

    # ── メッセージ削除監視 ────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild:
            return

        try:
            doc = self.count_ref(message.guild.id).get()
            if not doc.exists:
                return

            data = doc.to_dict()
            count_channel = data.get("channel")
            last_id = data.get("last_correct_message_id")
            current_count = data.get("count", 1)

            if not count_channel or message.channel.id != int(count_channel):
                return

            if last_id and message.id == int(last_id):
                await message.channel.send(
                    f"🗑️ 最新の数字が削除されたので再送します\n"
                    f"➡️ **次は `{current_count}` です**"
                )

        except Exception as e:
            print(f"[Count] on_message_delete エラー: {e}")

    # ── /count-stats ─────────────────────────────────────────────
    @app_commands.command(name="count-stats", description="カウントゲームの統計を表示します")
    async def count_stats(self, interaction: discord.Interaction):
        try:
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

        except Exception as e:
            print(f"[Count] count_stats エラー: {e}")
            await interaction.response.send_message("❌ エラーが発生しました。", ephemeral=True)


async def setup(bot: commands.Bot, db):
    await bot.add_cog(Count(bot, db))
