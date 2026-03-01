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

        for d in docs:
            data = d.to_dict()
            msg = data.get("message_count", 0)

            total_msg += msg
            total_join += data.get("member_join", 0)
            total_leave += data.get("member_leave", 0)

            if msg > max_msg:
                max_msg = msg
                max_day = data.get("date")

            for e, c in data.get("reactions", {}).items():
                emoji_counter[e] = emoji_counter.get(e, 0) + c

            day_count += 1

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
            "active_day": active_day
        }

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

            await channel.send(embed=embed)


async def setup(bot, db):
    await bot.add_cog(Server(bot, db))
