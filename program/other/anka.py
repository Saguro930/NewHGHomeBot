import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))


class Anka(commands.Cog):
    def __init__(self, bot, db):
        self.bot = bot
        self.db = db
        # 実行中の安価セッションを管理
        # key: (guild_id, channel_id) → セッション情報
        self._sessions: dict[tuple[int, int], dict] = {}

    # ─── /anka ────────────────────────────────────────────────────

    @app_commands.command(name="anka", description="安価を実行します")
    @app_commands.describe(
        message="安価の内容（例：次の行動を決めてください）",
        count="何番目のメッセージを採用するか（例：3）"
    )
    async def anka(
        self,
        interaction: discord.Interaction,
        message: str,
        count: app_commands.Range[int, 1, 100]
    ):
        key = (interaction.guild_id, interaction.channel_id)

        # すでに同チャンネルで安価が進行中の場合は拒否
        if key in self._sessions:
            await interaction.response.send_message(
                "⚠️ このチャンネルではすでに安価が進行中です。",
                ephemeral=True
            )
            return

        # 安価メッセージを送信
        embed = discord.Embed(
            description=message,
            color=0xe67e22,
            timestamp=datetime.now(JST)
        )
        embed.set_author(
            name=f"{interaction.user.display_name} の安価",
            icon_url=interaction.user.display_avatar.url
        )
        embed.set_footer(text=f"▶ {count} 番目のメッセージを採用します")

        await interaction.response.send_message(embed=embed)
        sent_msg = await interaction.original_response()

        # セッションを登録
        self._sessions[key] = {
            "host_id": interaction.user.id,
            "message": message,
            "count": count,
            "current": 0,
            "anchor_message_id": sent_msg.id,
            "channel_id": interaction.channel_id,
        }

    # ─── メッセージ監視 ────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        key = (message.guild.id, message.channel.id)
        session = self._sessions.get(key)
        if not session:
            return

        # 安価主自身のメッセージはカウントしない
        if message.author.id == session["host_id"]:
            return

        session["current"] += 1
        remaining = session["count"] - session["current"]

        # カウントダウン（残り3件以下で通知）
        if 0 < remaining <= 3:
            await message.add_reaction("🔢")

        # 採用メッセージに到達
        if session["current"] >= session["count"]:
            del self._sessions[key]

            embed = discord.Embed(
                color=0x2ecc71,
                timestamp=datetime.now(JST)
            )
            embed.set_author(
                name="✅ 安価が決定しました",
                icon_url=message.author.display_avatar.url
            )
            embed.add_field(
                name="📋 安価内容",
                value=session["message"],
                inline=False
            )
            embed.add_field(
                name="🎯 採用メッセージ",
                value=message.content or "（テキストなし）",
                inline=False
            )
            embed.add_field(
                name="👤 投稿者",
                value=message.author.mention,
                inline=True
            )
            embed.add_field(
                name="🔢 採用番号",
                value=f"{session['count']} 番目",
                inline=True
            )

            # 安価元メッセージへの返信として結果を送信
            try:
                anchor = await message.channel.fetch_message(session["anchor_message_id"])
                await anchor.reply(embed=embed)
            except discord.NotFound:
                await message.channel.send(embed=embed)

            # 採用メッセージにリアクションをつける
            await message.add_reaction("✅")

    # ─── !status ──────────────────────────────────────────────────

    @commands.command(name="status")
    async def anka_status(self, ctx: commands.Context):
        key = (ctx.guild.id, ctx.channel.id)
        session = self._sessions.get(key)

        if not session:
            await ctx.send("📭 このチャンネルで進行中の安価はありません。")
            return

        remaining = session["count"] - session["current"]
        host = ctx.guild.get_member(session["host_id"])

        embed = discord.Embed(
            title="📊 安価の進行状況",
            color=0xe67e22,
            timestamp=datetime.now(JST)
        )
        embed.add_field(name="📋 内容", value=session["message"], inline=False)
        embed.add_field(name="👤 安価主", value=host.mention if host else "不明", inline=True)
        embed.add_field(name="🔢 進捗", value=f"{session['current']} / {session['count']} 件", inline=True)
        embed.add_field(name="⏳ 残り", value=f"あと {remaining} 件", inline=True)

        await ctx.send(embed=embed)

    # ─── エラー処理 ────────────────────────────────────────────────

    @anka.error
    async def anka_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ このコマンドを実行する権限がありません。",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"❌ エラーが発生しました：{error}",
                ephemeral=True
            )


# ─── Cog登録 ──────────────────────────────────────────────────────

async def setup(bot, db):
    await bot.add_cog(Anka(bot, db))
