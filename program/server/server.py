import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta, timezone
import io

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False


JST = timezone(timedelta(hours=9))


class Server(commands.Cog):
    def __init__(self, bot, db):
        self.bot = bot
        self.db = db
        self._cache: dict[int, dict] = {}
        self._dirty: set[int] = set()

        self.flush_cache.start()
        self.daily_report.start()
        self.weekly_report.start()
        self.monthly_report.start()

    def cog_unload(self):
        self.flush_cache.cancel()
        self.daily_report.cancel()
        self.weekly_report.cancel()
        self.monthly_report.cancel()

    # ─── Firestore ─────────────────────────────

    def get_server_ref(self, guild_id: int, date_str: str):
        return (
            self.db.collection("guilds")
            .document(str(guild_id))
            .collection("server")
            .document(date_str)
        )

    def get_channel_ref(self, guild_id: int):
        return self.db.collection("guilds").document(str(guild_id))

    def today_str(self):
        return datetime.now(JST).strftime("%Y-%m-%d")

    def yesterday_str(self):
        return (datetime.now(JST) - timedelta(days=1)).strftime("%Y-%m-%d")

    # ─── キャッシュ ─────────────────────────────

    def _get_cache(self, guild_id: int):
        today = self.today_str()
        if guild_id not in self._cache:
            doc = self.get_server_ref(guild_id, today).get()
            self._cache[guild_id] = doc.to_dict() if doc.exists else {
                "date": today,
                "message_count": 0,
                "member_join": 0,
                "member_leave": 0,
                "reactions": {}
            }
        return self._cache[guild_id]

    def _mark_dirty(self, guild_id: int):
        self._dirty.add(guild_id)

    def _reset_cache_if_new_day(self, guild_id: int):
        cached = self._cache.get(guild_id)
        if cached and cached.get("date") != self.today_str():
            self._cache.pop(guild_id, None)

    # ─── Firestore flush ───────────────────────

    @tasks.loop(minutes=1)
    async def flush_cache(self):
        if not self._dirty:
            return

        today = self.today_str()
        targets = self._dirty.copy()
        self._dirty.clear()

        for gid in targets:
            data = self._cache.get(gid)
            if data:
                try:
                    self.get_server_ref(gid, today).set(data)
                except Exception:
                    self._dirty.add(gid)

    @flush_cache.before_loop
    async def before_flush(self):
        await self.bot.wait_until_ready()

    # ─── イベント ─────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        self._reset_cache_if_new_day(message.guild.id)
        data = self._get_cache(message.guild.id)
        data["message_count"] += 1
        self._mark_dirty(message.guild.id)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        self._reset_cache_if_new_day(member.guild.id)
        data = self._get_cache(member.guild.id)
        data["member_join"] += 1
        self._mark_dirty(member.guild.id)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        self._reset_cache_if_new_day(member.guild.id)
        data = self._get_cache(member.guild.id)
        data["member_leave"] += 1
        self._mark_dirty(member.guild.id)

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if user.bot or not reaction.message.guild:
            return
        self._reset_cache_if_new_day(reaction.message.guild.id)
        data = self._get_cache(reaction.message.guild.id)
        emoji = str(reaction.emoji)
        data["reactions"][emoji] = data["reactions"].get(emoji, 0) + 1
        self._mark_dirty(reaction.message.guild.id)

    @commands.Cog.listener()
    async def on_reaction_remove(self, reaction, user):
        if user.bot or not reaction.message.guild:
            return
        self._reset_cache_if_new_day(reaction.message.guild.id)
        data = self._get_cache(reaction.message.guild.id)
        emoji = str(reaction.emoji)
        if emoji in data["reactions"]:
            if data["reactions"][emoji] <= 1:
                del data["reactions"][emoji]
            else:
                data["reactions"][emoji] -= 1
        self._mark_dirty(reaction.message.guild.id)

    # ─── 共通集計 ─────────────────────────────

    def aggregate_period(self, guild_id: int, days: int):
        start = (datetime.now(JST) - timedelta(days=days)).strftime("%Y-%m-%d")

        docs = (
            self.db.collection("guilds")
            .document(str(guild_id))
            .collection("server")
            .where("date", ">=", start)
            .stream()
        )

        total_msg = total_join = total_leave = 0
        emoji_counter = {}
        max_day = None
        max_msg = 0
        day_count = 0
        daily_data = {}  # date_str -> {"msg": int, "join": int, "leave": int}

        for d in docs:
            data = d.to_dict()
            msg = data.get("message_count", 0)
            date = data.get("date")

            total_msg += msg
            total_join += data.get("member_join", 0)
            total_leave += data.get("member_leave", 0)

            if msg > max_msg:
                max_msg = msg
                max_day = date

            for e, c in data.get("reactions", {}).items():
                emoji_counter[e] = emoji_counter.get(e, 0) + c

            day_count += 1

            if date:
                daily_data[date] = {
                    "msg": msg,
                    "join": data.get("member_join", 0),
                    "leave": data.get("member_leave", 0),
                }

        avg_msg = round(total_msg / day_count) if day_count else 0

        if emoji_counter:
            top5 = sorted(emoji_counter.items(), key=lambda x: x[1], reverse=True)[:5]
            emoji_rank = "\n".join(
                f"{i+1}. {e}：{c}回" for i, (e, c) in enumerate(top5)
            )
        else:
            emoji_rank = "なし"

        active_day = f"{max_day}（{max_msg}件）" if max_day else "なし"

        return {
            "total_msg": total_msg,
            "avg_msg": avg_msg,
            "join": total_join,
            "leave": total_leave,
            "emoji_rank": emoji_rank,
            "active_day": active_day,
            "daily_data": daily_data,
            "emoji_counter": emoji_counter,
        }

    # ─── グラフ用データ取得 ────────────────────

    def fetch_daily_series(self, guild_id: int, days: int) -> dict:
        """指定日数分の日次生データを返す {date_str: {msg, join, leave}}"""
        start = (datetime.now(JST) - timedelta(days=days)).strftime("%Y-%m-%d")
        docs = (
            self.db.collection("guilds")
            .document(str(guild_id))
            .collection("server")
            .where("date", ">=", start)
            .stream()
        )
        result = {}
        for d in docs:
            data = d.to_dict()
            date = data.get("date")
            if date:
                result[date] = {
                    "msg": data.get("message_count", 0),
                    "join": data.get("member_join", 0),
                    "leave": data.get("member_leave", 0),
                }
        return result

    def _build_day_series(self, daily_data: dict, days: int):
        """日単位：過去 days 日分のラベル・メッセージ・メンバー純増を返す"""
        today = datetime.now(JST).date()
        dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d")
                 for i in range(days - 1, -1, -1)]
        labels   = [(today - timedelta(days=i)).strftime("%m/%d")
                    for i in range(days - 1, -1, -1)]
        msgs     = [daily_data.get(d, {}).get("msg", 0) for d in dates]
        members  = [daily_data.get(d, {}).get("join", 0)
                    - daily_data.get(d, {}).get("leave", 0) for d in dates]
        return labels, msgs, members

    def _build_week_series(self, daily_data: dict, num_weeks: int = 4):
        """週単位：過去 num_weeks 週分に集計したラベル・メッセージ・メンバー純増を返す"""
        today = datetime.now(JST).date()
        labels, msgs, members = [], [], []
        for w in range(num_weeks - 1, -1, -1):
            week_end   = today - timedelta(days=today.weekday() + 1 + w * 7)
            week_start = week_end - timedelta(days=6)
            msg_sum = mem_sum = 0
            cur = week_start
            while cur <= week_end:
                d = cur.strftime("%Y-%m-%d")
                msg_sum += daily_data.get(d, {}).get("msg", 0)
                mem_sum += (daily_data.get(d, {}).get("join", 0)
                            - daily_data.get(d, {}).get("leave", 0))
                cur += timedelta(days=1)
            labels.append(week_start.strftime("%m/%d") + "週")
            msgs.append(msg_sum)
            members.append(mem_sum)
        return labels, msgs, members

    def _build_month_series(self, daily_data: dict, num_months: int = 6):
        """月単位：過去 num_months ヶ月分に集計したラベル・メッセージ・メンバー純増を返す"""
        today = datetime.now(JST).date()
        labels, msgs, members = [], [], []
        for m in range(num_months - 1, -1, -1):
            # 対象月の1日を計算
            year  = today.year  + (today.month - 1 - m) // 12
            month = (today.month - 1 - m) % 12 + 1
            msg_sum = mem_sum = 0
            prefix = f"{year}-{month:02d}-"
            for date_str, v in daily_data.items():
                if date_str.startswith(prefix):
                    msg_sum += v.get("msg", 0)
                    mem_sum += v.get("join", 0) - v.get("leave", 0)
            labels.append(f"{month}月")
            msgs.append(msg_sum)
            members.append(mem_sum)
        return labels, msgs, members

    # ─── グラフ描画（共通） ────────────────────

    def _make_line_chart(
        self,
        labels: list,
        msg_values: list,
        member_values: list,
        title: str,
    ) -> "io.BytesIO | None":
        if not MATPLOTLIB_AVAILABLE:
            return None

        fig, (ax1, ax2) = plt.subplots(
            2, 1, figsize=(8, 5), facecolor="#2b2d31",
            gridspec_kw={"height_ratios": [3, 2]}
        )

        for ax in (ax1, ax2):
            ax.set_facecolor("#2b2d31")
            ax.tick_params(colors="white", labelsize=8)
            for spine in ax.spines.values():
                spine.set_visible(False)
            ax.grid(axis="y", color="#3f4147", linewidth=0.5, linestyle="--")
            ax.set_xticks(range(len(labels)))
            ax.set_xlim(-0.5, len(labels) - 0.5)

        xs = range(len(labels))

        # ── メッセージ数（折れ線）
        ax1.plot(xs, msg_values, color="#5865f2", linewidth=2,
                 marker="o", markersize=4, zorder=3)
        ax1.fill_between(xs, msg_values, alpha=0.15, color="#5865f2")
        ax1.set_ylabel("メッセージ数", color="white", fontsize=9)
        ax1.yaxis.set_major_locator(mticker.MaxNLocator(integer=True, nbins=5))
        ax1.set_xticklabels([])  # 上段はラベル非表示
        ax1.set_title(title, color="white", fontsize=12, pad=10)

        # ── メンバー純増（折れ線）
        ax2.plot(xs, member_values, color="#57f287", linewidth=2,
                 marker="o", markersize=4, zorder=3)
        ax2.fill_between(xs, member_values,
                         where=[v >= 0 for v in member_values],
                         alpha=0.15, color="#57f287")
        ax2.fill_between(xs, member_values,
                         where=[v < 0 for v in member_values],
                         alpha=0.15, color="#ed4245")
        ax2.axhline(0, color="#72767d", linewidth=0.8)
        ax2.set_ylabel("メンバー純増", color="white", fontsize=9)
        ax2.yaxis.set_major_locator(mticker.MaxNLocator(integer=True, nbins=4))
        ax2.set_xticklabels(labels, rotation=30, ha="right", color="white")

        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=120, facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)
        return buf

    # ─── デイリー ─────────────────────────────

    @tasks.loop(time=datetime.now(JST).replace(hour=0, minute=0, second=0, microsecond=0).timetz())
    async def daily_report(self):
        now = datetime.now(JST)
        yesterday = self.yesterday_str()

        for guild in self.bot.guilds:
            doc = self.get_channel_ref(guild.id).get()
            channel_id = doc.to_dict().get("server_channel") if doc.exists else None
            channel = guild.get_channel(int(channel_id)) if channel_id else None
            if not channel:
                continue

            data = self._cache.get(guild.id) or {}
            reactions = data.get("reactions", {})

            if reactions:
                top3 = sorted(reactions.items(), key=lambda x: x[1], reverse=True)[:3]
                top_emoji = "\n".join(f"{e}：{c}回" for e, c in top3)
            else:
                top_emoji = "なし"

            embed = discord.Embed(
                title="📊 デイリーレポート",
                description=f"{yesterday} の統計",
                color=discord.Color.blurple(),
                timestamp=now
            )
            embed.add_field(name="💬 メッセージ数", value=f"{data.get('message_count',0)} 件")
            embed.add_field(
                name="👥 メンバー増減",
                value=f"{data.get('member_join',0)-data.get('member_leave',0)} 人"
            )
            embed.add_field(name="🏆 リアクション Top3", value=top_emoji, inline=False)

            # グラフ：過去7日を日単位で表示
            daily_data = self.fetch_daily_series(guild.id, 7)
            labels, msgs, members = self._build_day_series(daily_data, 7)
            chart_buf = self._make_line_chart(labels, msgs, members, "過去7日間の推移")
            if chart_buf:
                file = discord.File(chart_buf, filename="daily_chart.png")
                embed.set_image(url="attachment://daily_chart.png")
                await channel.send(embed=embed, file=file)
            else:
                await channel.send(embed=embed)

        self._cache.clear()
        self._dirty.clear()

    # ─── 週間 ─────────────────────────────

    @tasks.loop(time=datetime.now(JST).replace(hour=0, minute=0, second=0, microsecond=0).timetz())
    async def weekly_report(self):
        if datetime.now(JST).weekday() != 6:
            return

        for guild in self.bot.guilds:
            doc = self.get_channel_ref(guild.id).get()
            channel_id = doc.to_dict().get("server_channel") if doc.exists else None
            channel = guild.get_channel(int(channel_id)) if channel_id else None
            if not channel:
                continue

            stats = self.aggregate_period(guild.id, 7)

            embed = discord.Embed(
                title="📅 週間サーバーレポート",
                color=discord.Color.green(),
                timestamp=datetime.now(JST)
            )
            embed.add_field(name="💬 総メッセージ数", value=f"{stats['total_msg']} 件")
            embed.add_field(name="📈 1日平均", value=f"{stats['avg_msg']} 件/日")
            embed.add_field(name="🔥 今週一番アクティブだった日", value=stats["active_day"], inline=False)
            embed.add_field(name="🏅 絵文字ランキング Top5", value=stats["emoji_rank"], inline=False)

            # グラフ：過去4週を週単位で表示
            daily_data = self.fetch_daily_series(guild.id, 28)
            labels, msgs, members = self._build_week_series(daily_data, num_weeks=4)
            chart_buf = self._make_line_chart(labels, msgs, members, "過去4週間の推移")
            if chart_buf:
                file = discord.File(chart_buf, filename="weekly_chart.png")
                embed.set_image(url="attachment://weekly_chart.png")
                await channel.send(embed=embed, file=file)
            else:
                await channel.send(embed=embed)

    # ─── 月間 ─────────────────────────────

    @tasks.loop(time=datetime.now(JST).replace(hour=0, minute=0, second=0, microsecond=0).timetz())
    async def monthly_report(self):
        if datetime.now(JST).day != 1:
            return

        for guild in self.bot.guilds:
            doc = self.get_channel_ref(guild.id).get()
            channel_id = doc.to_dict().get("server_channel") if doc.exists else None
            channel = guild.get_channel(int(channel_id)) if channel_id else None
            if not channel:
                continue

            stats = self.aggregate_period(guild.id, 30)

            embed = discord.Embed(
                title="🗓 月間サーバーレポート",
                color=discord.Color.orange(),
                timestamp=datetime.now(JST)
            )
            embed.add_field(name="💬 総メッセージ数", value=f"{stats['total_msg']} 件")
            embed.add_field(name="📈 1日平均", value=f"{stats['avg_msg']} 件/日")
            embed.add_field(name="🔥 今月一番アクティブだった日", value=stats["active_day"], inline=False)
            embed.add_field(name="🏆 絵文字ランキング Top5", value=stats["emoji_rank"], inline=False)

            # グラフ：過去6ヶ月を月単位で表示
            daily_data = self.fetch_daily_series(guild.id, 183)
            labels, msgs, members = self._build_month_series(daily_data, num_months=6)
            chart_buf = self._make_line_chart(labels, msgs, members, "過去6ヶ月の推移")
            if chart_buf:
                file = discord.File(chart_buf, filename="monthly_chart.png")
                embed.set_image(url="attachment://monthly_chart.png")
                await channel.send(embed=embed, file=file)
            else:
                await channel.send(embed=embed)


async def setup(bot, db):
    await bot.add_cog(Server(bot, db))
