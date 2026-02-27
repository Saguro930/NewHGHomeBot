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
    # /set_count（管理者のみ）
    # -----------------------------
    @commands.hybrid_command(name="set_count")
    @commands.has_permissions(administrator=True)
    async def set_count(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        channel_id = ctx.channel.id
        doc_ref = self.db.collection("guilds").document(guild_id)
        doc_ref.set({
            "count_channel": channel_id,
            "count": 1,
            "recent_authors": []   # 履歴もリセット
        }, merge=True)
        await ctx.reply(
            f"✅ カウントチャンネルを {ctx.channel.mention} に設定しますた\n"
            f"🔢 カウントは **1** からスタートです！"
        )

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

        # 数字 or 式以外は無視
        content = message.content.replace(" ", "")
        if not re.fullmatch(r"[0-9+\-*/%]+", content):
            return

        value = safe_eval(content)
        if value is None:
            return

        author_id = message.author.id

        # -----------------------------
        # 連続投稿チェック（4回連続でリセット）
        # -----------------------------
        # 直近4件が全て同じユーザーなら弾く
        if len(recent_authors) >= 4 and all(uid == author_id for uid in recent_authors[-4:]):
            doc_ref.update({
                "count": 1,
                "recent_authors": []
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
            # 直近4件だけ保持してFirestoreに保存
            new_history = (recent_authors + [author_id])[-4:]
            doc_ref.update({
                "count": current_count + 1,
                "recent_authors": new_history
            })
            await message.add_reaction("✅")
        else:
            doc_ref.update({
                "count": 1,
                "recent_authors": []   # ミス時も履歴リセット
            })
            await message.add_reaction("❌")
            await message.channel.send(
                f"❌ 間違いです！\n"
                f"正解は **{current_count}** です。\n"
                f"🔁 **1 からやり直しになりました You are 戦犯！**"
            )


async def setup(bot: commands.Bot, db):
    await bot.add_cog(Count(bot, db))
