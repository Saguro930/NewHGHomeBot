import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta, timezone
import io

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False


JST = timezone(timedelta(hours=9))


class Server(commands.Cog):
    def __init__(self, bot, db):
        self.bot = bot
        self.db = db
        self.daily_report.start()

    def cog_unload(self):
        self.daily_report.cancel()

    # ─── Firestore 参照 ───────────────────────────────────────────

    def get_server_ref(self, guild_id: int, date_str: str):
        """guilds/{guild_id}/server/{date}"""
        return (
            self.db.collection("guilds")
            .document(str(guild_id))
            .collection("server")
            .document(date_str)
        )

    def get_channel_ref(self, guild_id: int):
        """guilds/{guild_id}/server_channel"""
        return (
            self.db.collection("guilds")
            .document(str(guild_id))
        )

    def today_str(self) -> str:
        return datetime.now(JST).strftime("%Y-%m-%d")

    def yesterday_str(self) -> str:
        return (datetime.now(JST) - timedelta(days=1)).strftime("%Y-%m-%d")

    # ─── 今日のデータ取得・初期化 ─────────────────────────────────

    def get_today_data(self, guild_id: int) -> dict:
        doc = self.get_server_ref(guild_id, self.today_str()).get()
        if doc.exists:
            return doc.to_dict()
        return {
            "date":          self.today_str(),
            "message_count": 0,
            "member_join":   0,
            "member_leave":  0,
            "reactions":     {},   # {emoji_str: count}
        }

    def save_today_data(self, guild_id: int, data: dict):
        self.get_server_ref(guild_id, self.today_str()).set(data)

    # ─── イベントリスナー ────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        data = self.get_today_data(message.guild.id)
        data["message_count"] += 1
        self.save_today_data(message.guild.id, data)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        data = self.get_today_data(member.guild.id)
        data["member_join"] += 1
        self.save_today_data(member.guild.id, data)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        data = self.get_today_data(member.guild.id)
        data["member_leave"] += 1
        self.save_today_data(member.guild.id, data)

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        if user.bot or not reaction.message.guild:
            return
        data = self.get_today_data(reaction.message.guild.id)
        emoji_str = str(reaction.emoji)
        reactions = data.get("reactions", {})
        reactions[emoji_str] = reactions.get(emoji_str, 0) + 1
        data["reactions"] = reactions
        self.save_today_data(reaction.message.guild.id, data)

    @commands.Cog.listener()
    async def on_reaction_remove(self, reaction: discord.Reaction, user: discord.User):
        if user.bot or not reaction.message.guild:
            return
        data = self.get_today_data(reaction.message.guild.id)
        emoji_str = str(reaction.emoji)
        reactions = data.get("reactions", {})
        current = reactions.get(emoji_str, 0)
        if current > 1:
            reactions[emoji_str] = current - 1
        elif current == 1:
            del reactions[emoji_str]  # 0になったらキーごと削除
        data["reactions"] = reactions
        self.save_today_data(reaction.message.guild.id, data)

    # ─── 線グラフ生成 ─────────────────────────────────────────────

    def generate_graph(self, guild_id: int) -> io.BytesIO | None:
        if not MATPLOTLIB_AVAILABLE:
            return None

        docs = (
            self.db.collection("guilds")
            .document(str(guild_id))
            .collection("server")
            .order_by("date")
            .limit(30)
            .stream()
        )

        records = [d.to_dict() for d in docs]
        if len(records) < 2:
            return None

        dates    = [datetime.strptime(r["date"], "%Y-%m-%d") for r in records]
        messages = [r.get("message_count", 0) for r in records]
        joins    = [r.get("member_join", 0)   for r in records]
        leaves   = [r.get("member_leave", 0)  for r in records]

        fig, ax1 = plt.subplots(figsize=(10, 4))
        fig.patch.set_facecolor("#2b2d31")
        ax1.set_facecolor("#2b2d31")

        ax1.plot(dates, messages, color="#5865F2", linewidth=2, marker="o", markersize=4, label="メッセージ数")
        ax1.set_ylabel("メッセージ数", color="#dcddde")
        ax1.tick_params(axis="y", labelcolor="#dcddde")
        ax1.tick_params(axis="x", labelcolor="#dcddde", rotation=30)
        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
        ax1.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, len(dates)//10)))

        ax2 = ax1.twinx()
        ax2.plot(dates, joins,  color="#57F287", linewidth=2, marker="^", markersize=4, label="参加")
        ax2.plot(dates, leaves, color="#ED4245", linewidth=2, marker="v", markersize=4, label="退出")
        ax2.set_ylabel("メンバー数", color="#dcddde")
        ax2.tick_params(axis="y", labelcolor="#dcddde")

        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, facecolor="#40444b", labelcolor="#dcddde", loc="upper left")

        for spine in ax1.spines.values():
            spine.set_edgecolor("#40444b")
        for spine in ax2.spines.values():
            spine.set_edgecolor("#40444b")

        plt.title("過去30日間のサーバー統計", color="#dcddde", pad=10)
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=120, facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)
        return buf

    # ─── 毎日0時にレポート送信 ───────────────────────────────────

    @tasks.loop(time=datetime.now(JST).replace(hour=0, minute=0, second=0, microsecond=0).timetz())
    async def daily_report(self):
        yesterday = self.yesterday_str()
        now_jst   = datetime.now(JST)
        date_label = (now_jst - timedelta(days=1)).strftime("%m/%d")

        for guild in self.bot.guilds:
            # 送信チャンネル取得
            doc = self.get_channel_ref(guild.id).get()
            if not doc.exists:
                continue
            channel_id = doc.to_dict().get("server_channel")
            if not channel_id:
                continue
            channel = guild.get_channel(int(channel_id))
            if not channel:
                continue

            # 昨日のデータ取得
            data_doc = self.get_server_ref(guild.id, yesterday).get()
            if not data_doc.exists:
                data = {"message_count": 0, "member_join": 0, "member_leave": 0, "reactions": {}}
            else:
                data = data_doc.to_dict()

            msg_count   = data.get("message_count", 0)
            join_count  = data.get("member_join", 0)
            leave_count = data.get("member_leave", 0)
            reactions   = data.get("reactions", {})
            net_member  = join_count - leave_count

            # 一番多く使われた絵文字
            top_emoji = (
                max(reactions, key=reactions.get) + f"（{reactions[max(reactions, key=reactions.get)]}回）"
                if reactions else "なし"
            )

            # メンバー増減の表示
            if net_member > 0:
                member_str = f"+{net_member}人（参加 {join_count}人 / 退出 {leave_count}人）"
            elif net_member < 0:
                member_str = f"{net_member}人（参加 {join_count}人 / 退出 {leave_count}人）"
            else:
                member_str = f"増減なし（参加 {join_count}人 / 退出 {leave_count}人）"

            embed = discord.Embed(
                title=f"📊 {guild.name} デイリーレポート",
                description=f"**{date_label}** に送信された統計です",
                color=discord.Color.blurple(),
                timestamp=now_jst
            )
            embed.add_field(name="💬 メッセージ数",   value=f"{msg_count} 件",  inline=True)
            embed.add_field(name="👥 メンバー増減",   value=member_str,         inline=True)
            embed.add_field(name="🏆 最多リアクション", value=top_emoji,         inline=True)
            embed.set_footer(text="毎日0時に集計")

            # グラフ生成
            graph_buf = self.generate_graph(guild.id)
            if graph_buf:
                file = discord.File(graph_buf, filename="stats.png")
                embed.set_image(url="attachment://stats.png")
                await channel.send(embed=embed, file=file)
            else:
                await channel.send(embed=embed)

    @daily_report.before_loop
    async def before_daily_report(self):
        await self.bot.wait_until_ready()

    # ─── /set-server コマンド ────────────────────────────────────

    @app_commands.command(
        name="set-server",
        description="デイリーレポートを送信するチャンネルを設定します"
    )
    @app_commands.describe(channel="レポートを送信するチャンネル")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_server(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel
    ):
        self.get_channel_ref(interaction.guild.id).set(
            {"server_channel": channel.id},
            merge=True
        )
        await interaction.response.send_message(
            f"✅ デイリーレポートの送信先を {channel.mention} に設定しました。",
            ephemeral=True
        )

    @set_server.error
    async def set_server_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ このコマンドは管理者のみ使用できます。",
                ephemeral=True
            )


# ─── Cog登録 ──────────────────────────────────────────────────────

async def setup(bot, db):
    await bot.add_cog(Server(bot, db))
