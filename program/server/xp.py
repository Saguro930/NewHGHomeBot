import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))


class XP(commands.Cog):
    def __init__(self, bot, db):
        self.bot = bot
        self.db  = db
        self.daily_xp_report.start()

    def cog_unload(self):
        self.daily_xp_report.cancel()

    # ── Firestore ──────────────────────────────────────────
    def get_user_ref(self, guild_id, user_id):
        return (
            self.db.collection("guilds")
            .document(str(guild_id))
            .collection("members")
            .document(str(user_id))
        )

    def get_guild_ref(self, guild_id):
        return self.db.collection("guilds").document(str(guild_id))

    async def get_user_data(self, guild_id, user_id):
        doc  = self.get_user_ref(guild_id, user_id).get()
        data = doc.to_dict() if doc.exists else {}
        data.setdefault("xp",         0)
        data.setdefault("level",      0)
        data.setdefault("total_xp",   0)
        data.setdefault("daily_xp",   0)
        data.setdefault("daily_date", "")
        return data

    async def set_user_data(self, guild_id, user_id, data):
        self.get_user_ref(guild_id, user_id).set(data, merge=True)

    async def get_guild_data(self, guild_id):
        doc  = self.get_guild_ref(guild_id).get()
        data = doc.to_dict() if doc.exists else {}
        data.setdefault("level_up_channel", None)
        data.setdefault("xpnews_channel",   None)
        return data

    # ── XP計算式（ProBot準拠）────────────────────────────
    def xp_required(self, level: int) -> int:
        return 5 * (level ** 2) + 50 * level + 100

    def calc_level(self, total_xp: int) -> tuple[int, int, int]:
        level = 0
        while total_xp >= self.xp_required(level):
            total_xp -= self.xp_required(level)
            level += 1
        return level, total_xp, self.xp_required(level)

    def calc_gained_xp(self, content: str) -> int:
        length = len(content.strip())
        xp = 3 + int((length / 50) * 27)
        return max(3, min(30, xp))

    # ── 土日判定・倍率 ────────────────────────────────────
    def xp_multiplier(self) -> float:
        return 2.0 if datetime.now(JST).weekday() >= 5 else 1.0

    # ── daily_xp のリセット（日付が変わったら）────────────
    def _reset_daily_xp_if_needed(self, data: dict) -> dict:
        today = datetime.now(JST).strftime("%Y-%m-%d")
        if data.get("daily_date") != today:
            data["daily_xp"]   = 0
            data["daily_date"] = today
        return data

    # ── メッセージ受信でXP付与 ────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        guild_id  = message.guild.id
        user_id   = message.author.id
        multi     = self.xp_multiplier()
        gained_xp = int(self.calc_gained_xp(message.content) * multi)

        data      = await self.get_user_data(guild_id, user_id)
        data      = self._reset_daily_xp_if_needed(data)
        old_level = data["level"]

        data["total_xp"] += gained_xp
        data["daily_xp"] += gained_xp

        new_level, current_xp, _ = self.calc_level(data["total_xp"])
        data["level"] = new_level
        data["xp"]    = current_xp

        await self.set_user_data(guild_id, user_id, data)

        # レベルアップ通知
        if new_level > old_level:
            desc = f"{message.author.mention} が **レベル {new_level}** になりました！"
            if multi == 2.0:
                desc += "\n🎊 週末ボーナスで獲得XPが **2倍** です！"

            embed = discord.Embed(
                title="🎉 レベルアップ！",
                description=desc,
                color=discord.Color.gold()
            )
            embed.set_thumbnail(url=message.author.display_avatar.url)

            guild_data = await self.get_guild_data(guild_id)
            channel_id = guild_data.get("level_up_channel")

            if channel_id:
                channel = message.guild.get_channel(int(channel_id))
                if channel:
                    await channel.send(embed=embed)
                    return

            await message.channel.send(embed=embed)

    # ── 毎日0時にXPニュース送信 ───────────────────────────

    @tasks.loop(time=datetime.now(JST).replace(hour=0, minute=0, second=0, microsecond=0).timetz())
    async def daily_xp_report(self):
        yesterday  = datetime.now(JST) - timedelta(days=1)
        date_label = yesterday.strftime("%m/%d")
        today      = datetime.now(JST).strftime("%Y-%m-%d")
        is_weekend = yesterday.weekday() >= 5

        for guild in self.bot.guilds:
            guild_data = await self.get_guild_data(guild.id)
            channel_id = guild_data.get("xpnews_channel")

            # ── チャンネルが設定されていれば送信 ──
            if channel_id:
                channel = guild.get_channel(int(channel_id))
                if channel:
                    docs = (
                        self.db.collection("guilds")
                        .document(str(guild.id))
                        .collection("members")
                        .order_by("daily_xp", direction="DESCENDING")
                        .limit(3)
                        .stream()
                    )

                    medals  = ["🥇", "🥈", "🥉"]
                    entries = []
                    for i, doc in enumerate(docs):
                        d     = doc.to_dict()
                        daily = d.get("daily_xp", 0)
                        if daily == 0:
                            break
                        member = guild.get_member(int(doc.id))
                        name   = member.display_name if member else "退出済みユーザー"
                        level  = d.get("level", 0)
                        entries.append(f"{medals[i]} **{name}** — **{daily:,} XP** 獲得 (Lv.{level})")

                    if entries:
                        desc = "\n".join(entries)
                        if is_weekend:
                            desc = "🎊 **週末ボーナスデー（2倍XP）**\n\n" + desc

                        embed = discord.Embed(
                            title=f"📰 {date_label} のXPニュース",
                            description=desc,
                            color=discord.Color.blurple(),
                            timestamp=datetime.now(JST)
                        )
                        embed.set_footer(text="毎日0時に集計")
                        await channel.send(embed=embed)

            # ── チャンネル設定に関わらず daily_xp はリセット ──
            all_docs = (
                self.db.collection("guilds")
                .document(str(guild.id))
                .collection("members")
                .stream()
            )
            for doc in all_docs:
                self.get_user_ref(guild.id, doc.id).set(
                    {"daily_xp": 0, "daily_date": today},
                    merge=True
                )

    @daily_xp_report.before_loop
    async def before_daily_xp_report(self):
        await self.bot.wait_until_ready()

    # ── /rank コマンド ────────────────────────────────────
    @app_commands.command(name="rank", description="自分または指定したユーザーのランクを確認する")
    @app_commands.describe(user="確認したいユーザー（省略で自分）")
    async def rank(self, interaction: discord.Interaction, user: discord.Member = None):
        target     = user or interaction.user
        data       = await self.get_user_data(interaction.guild.id, target.id)
        data       = self._reset_daily_xp_if_needed(data)

        level      = data["level"]
        current_xp = data["xp"]
        total_xp   = data["total_xp"]
        daily_xp   = data["daily_xp"]
        xp_needed  = self.xp_required(level)
        multi      = self.xp_multiplier()

        filled = int((current_xp / xp_needed) * 20)
        bar    = "█" * filled + "░" * (20 - filled)

        rank_position = await self.get_rank_position(interaction.guild.id, total_xp)

        embed = discord.Embed(
            title=f"📊 {target.display_name} のランク",
            color=discord.Color.blurple()
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="🏅 サーバーランク", value=f"#{rank_position}", inline=True)
        embed.add_field(name="⭐ レベル",         value=str(level),          inline=True)
        embed.add_field(name="✨ 累計XP",         value=f"{total_xp:,}",     inline=True)
        embed.add_field(name="📅 今日のXP",       value=f"{daily_xp:,}",     inline=True)
        embed.add_field(
            name="🎊 XP倍率",
            value=f"**×{multi:.1f}**{'　🎉週末ボーナス中！' if multi == 2.0 else ''}",
            inline=True
        )
        embed.add_field(
            name=f"XP進捗 ({current_xp} / {xp_needed})",
            value=f"`{bar}` {int(current_xp / xp_needed * 100)}%",
            inline=False
        )
        await interaction.response.send_message(embed=embed)

    # ── /leaderboard コマンド ─────────────────────────────
    @app_commands.command(name="leaderboard", description="サーバーのXPランキングを表示する")
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()

        docs = (
            self.db.collection("guilds")
            .document(str(interaction.guild.id))
            .collection("members")
            .order_by("total_xp", direction="DESCENDING")
            .limit(10)
            .stream()
        )

        embed   = discord.Embed(
            title=f"🏆 {interaction.guild.name} のXPランキング",
            color=discord.Color.gold()
        )
        medals  = ["🥇", "🥈", "🥉"]
        entries = []

        for i, doc in enumerate(docs):
            d        = doc.to_dict()
            member   = interaction.guild.get_member(int(doc.id))
            name     = member.display_name if member else f"退出済みユーザー ({doc.id})"
            medal    = medals[i] if i < 3 else f"`#{i+1}`"
            level    = d.get("level",    0)
            total_xp = d.get("total_xp", 0)
            entries.append(f"{medal} **{name}** — Lv.{level} ({total_xp:,} XP)")

        embed.description = "\n".join(entries) if entries else "まだデータがありません。"
        await interaction.followup.send(embed=embed)

    # ── ランク順位取得（ヘルパー）────────────────────────
    async def get_rank_position(self, guild_id: int, total_xp: int) -> int:
        docs = (
            self.db.collection("guilds")
            .document(str(guild_id))
            .collection("members")
            .where("total_xp", ">", total_xp)
            .stream()
        )
        return sum(1 for _ in docs) + 1


async def setup(bot, db):
    await bot.add_cog(XP(bot, db))
