import discord
from discord.ext import commands
import re
import ast
import operator

# 安全な演算子だけ許可
OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.floordiv,
    ast.Mod: operator.mod,
}

def safe_eval(expr: str) -> int | None:
    try:
        node = ast.parse(expr, mode="eval").body
        return _eval_node(node)
    except Exception:
        return None

def _eval_node(node):
    if isinstance(node, ast.Num):
        return node.n
    if isinstance(node, ast.BinOp) and type(node.op) in OPERATORS:
        return OPERATORS[type(node.op)](
            _eval_node(node.left),
            _eval_node(node.right)
        )
    raise ValueError("Invalid expression")


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

        guild_id = str(message.guild.id)
        doc_ref = self.db.collection("guilds").document(guild_id)
        doc = doc_ref.get()
        if not doc.exists:
            return

        data = doc.to_dict()
        count_channel = data.get("count_channel")
        current_count = data.get("count", 1)
        recent_authors: list = data.get("recent_authors", [])

        if message.channel.id != count_channel:
            return

        content = message.content.replace(" ", "")
        if not re.fullmatch(r"[0-9+\-*/%]+", content):
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
                "last_correct_message_id": None
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
                "last_correct_message_id": message.id
            })
            await message.add_reaction("✅")
        else:
            doc_ref.update({
                "count": 1,
                "recent_authors": [],
                "last_correct_message_id": None
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

        guild_id = str(message.guild.id)
        doc_ref = self.db.collection("guilds").document(guild_id)
        doc = doc_ref.get()
        if not doc.exists:
            return

        data = doc.to_dict()
        count_channel = data.get("count_channel")
        last_id = data.get("last_correct_message_id")
        current_count = data.get("count", 1)

        if message.channel.id != count_channel:
            return

        # 最新の正解メッセージが消された場合
        if last_id and message.id == last_id:
            channel = message.channel
            await channel.send(
                f"🗑️ 最新の数字が削除されたので再送します\n"
                f"➡️ **次は `{current_count}` です**"
            )


async def setup(bot: commands.Bot, db):
    await bot.add_cog(Count(bot, db))
