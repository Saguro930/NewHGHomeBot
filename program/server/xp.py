import asyncio
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta, timezone, time as dt_time

JST = timezone(timedelta(hours=9))

VOICE_XP_PER_MINUTE    = 10
VOICE_XP_MAX_PER_SESSION = 600   # 最大60分相当

PAGE_SIZE = 10


# ── ページネーション用 View ────────────────────────────────────────
class LeaderboardView(discord.ui.View):
    def __init__(self, cog: "XP", guild: discord.Guild, page: int = 0):
        super().__init__(timeout=120)
        self.cog   = cog
        self.guild = guild
        self.page  = page

    async def _build_embed(self) -> tuple[discord.Embed, bool]:
        offset = self.page * PAGE_SIZE

        docs = await asyncio.to_thread(
            lambda: list(
                self.cog.db.collection("guilds")
                .document(str(self.guild.id))
                .collection("members")
                .order_by("total_xp", direction="DESCENDING")
                .limit(offset + PAGE_SIZE + 1)
                .stream()
            )
        )
        has_next  = len(docs) > offset + PAGE_SIZE
        page_docs = docs[offset : offset + PAGE_SIZE]

        embed  = discord.Embed(
            title=f"🏆 {self.guild.name} のXPランキング",
            color=discord.Color.gold()
        )
        medals  = ["🥇", "🥈", "🥉"]
        entries = []

        for i, doc in enumerate(page_docs):
            rank     = offset + i + 1
            d        = doc.to_dict()
            member   = self.guild.get_member(int(doc.id))
            name     = member.display_name if member else f"退出済みユーザー ({doc.id})"
            medal    = medals[rank - 1] if rank <= 3 else f"`#{rank}`"
            level    = d.get("level",    0)
            total_xp = d.get("total_xp", 0)
            entries.append(f"{medal} **{name}** — Lv.{level} ({total_xp:,} XP)")

        embed.description = "\n".join(entries) if entries else "データがありません。"
        embed.set_footer(
            text=f"ページ {self.page + 1}　({offset + 1}〜{offset + len(page_docs)} 位)"
        )
        return embed, has_next

    def _update_buttons(self, has_next: bool):
        self.prev_button.disabled = self.page == 0
        self.next_button.disabled = not has_next

    async def send(self, interaction: discord.Interaction):
        embed, has_next = await self._build_embed()
        self._update_buttons(has_next)
        await interaction.followup.send(embed=embed, view=self)

    async def _refresh(self, interaction: discord.Interaction):
        embed, has_next = await self._build_embed()
        self._update_buttons(has_next)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="◀ 前へ", style=discord.ButtonStyle.secondary, disabled=True)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        await self._refresh(interaction)

    @discord.ui.button(label="次へ ▶", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        await self._refresh(interaction)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class XP(commands.Cog):
    def __init__(self, bot, db):
        self.bot = bot
        self.db  = db
        self._voice_join_times: dict[tuple[int, int], datetime] = {}
        self.daily_xp_report.start()

    def cog_unload(self):
        self.daily_xp_report.cancel()

    # ── Firestore（ブロッキング呼び出しを別スレッドで実行）────────
    def get_user_ref(self, guild_id, user_id):
        return (
            self.db.collection("guilds")
            .document(str(guild_id))
            .collection("members")
            .document(str(user_id))
        )

    def get_guild_ref(self, guild_id):
        return self.db.collection("guilds").document(str(guild_id))

    async def get_user_data(self, guild_id, user_id) -> dict:
        doc  = await asyncio.to_thread(self.get_user_ref(guild_id, user_id).get)
        data = doc.to_dict() if doc.exists else {}
        data.setdefault("xp",             0)
        data.setdefault("level",          0)
        data.setdefault("total_xp",       0)
        data.setdefault("daily_xp",       0)
        data.setdefault("daily_date",     "")
        data.setdefault("voice_xp",       0)
        data.setdefault("voice_level",    0)
        data.setdefault("voice_total_xp", 0)
        return data

    async def set_user_data(self, guild_id, user_id, data: dict):
        await asyncio.to_thread(
            self.get_user_ref(guild_id, user_id).set, data, {"merge": True}
        )

    async def get_guild_data(self, guild_id) -> dict:
        doc  = await asyncio.to_thread(self.get_guild_ref(guild_id).get)
        data = doc.to_dict() if doc.exists else {}
        data.setdefault("level_up_channel", None)
        data.setdefault("xpnews_channel",   None)
        return data

    # ── XP計算式（ProBot準拠）────────────────────────────────────
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

    def xp_multiplier(self) -> float:
        return 2.0 if datetime.now(JST).weekday() >= 5 else 1.0

    def _reset_daily_xp_if_needed(self, data: dict) -> dict:
        today = datetime.now(JST).strftime("%Y-%m-%d")
        if data.get("daily_date") != today:
            data["daily_xp"]   = 0
            data["daily_date"] = today
        return data

    # ── XP付与（メッセージ・ボイス共通、レベルアップ通知つき）──────
    async def _grant_xp(
        self,
        guild:          discord.Guild,
        member:         discord.Member,
        gained_xp:      int,
        add_to_daily:   bool,
        notify_channel: discord.TextChannel | None = None,
        multi:          float = 1.0,
        voice_xp_gain:  int = 0,
    ):
        data      = await self.get_user_data(guild.id, member.id)
        data      = self._reset_daily_xp_if_needed(data)
        old_level = data["level"]

        # ── メインXP更新 ──
        data["total_xp"] += gained_xp
        if add_to_daily:
            data["daily_xp"] += gained_xp
        new_level, current_xp, _ = self.calc_level(data["total_xp"])
        data["level"] = new_level
        data["xp"]    = current_xp

        old_voice_level = data["voice_level"]
        if voice_xp_gain > 0:
            data["voice_total_xp"] += voice_xp_gain
            new_vlevel, new_vxp, _ = self.calc_level(data["voice_total_xp"])
            data["voice_level"] = new_vlevel
            data["voice_xp"]    = new_vxp
        else:
            new_vlevel      = data["voice_level"]
            old_voice_level = new_vlevel  # 変化なし扱い

        await self.set_user_data(guild.id, member.id, data)

        guild_data = await self.get_guild_data(guild.id)
        channel_id = guild_data.get("level_up_channel")
        dest = guild.get_channel(int(channel_id)) if channel_id else notify_channel

        # メインレベルアップ通知
        if new_level > old_level and dest:
            desc = f"{member.mention} が **レベル {new_level}** になりました！"
            if multi == 2.0:
                desc += "\n🎊 週末ボーナスで獲得XPが **2倍** です！"
            embed = discord.Embed(title="🎉 レベルアップ！", description=desc, color=discord.Color.gold())
            embed.set_thumbnail(url=member.display_avatar.url)
            await dest.send(embed=embed)

        # ボイスレベルアップ通知
        if voice_xp_gain > 0 and new_vlevel > old_voice_level and dest:
            desc = f"{member.mention} のボイスレベルが **レベル {new_vlevel}** になりました！"
            if multi == 2.0:
                desc += "\n🎊 週末ボーナスで獲得XPが **2倍** です！"
            embed = discord.Embed(title="🎙️ ボイスレベルアップ！", description=desc, color=discord.Color.teal())
            embed.set_thumbnail(url=member.display_avatar.url)
            await dest.send(embed=embed)

    # ── AFK チャンネル判定 ────────────────────────────────────────
    def _is_afk(self, channel: discord.VoiceChannel | None, guild: discord.Guild) -> bool:
        if channel is None:
            return False
        return guild.afk_channel is not None and channel.id == guild.afk_channel.id

    # ── メッセージXP付与（通常チャンネル＋フォーラム返信）──────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        multi     = self.xp_multiplier()
        gained_xp = int(self.calc_gained_xp(message.content) * multi)

        await self._grant_xp(
            guild=message.guild,
            member=message.author,
            gained_xp=gained_xp,
            add_to_daily=True,
            notify_channel=message.channel,
            multi=multi,
        )

    # ── フォーラム新規投稿XP（スレッド作成時の最初のメッセージ）──────
    # on_message はフォーラムの最初の投稿（スターターメッセージ）を
    # 拾わないため、on_thread_create で別途処理する。
    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        # フォーラムチャンネルのスレッドのみ対象
        if not isinstance(thread.parent, discord.ForumChannel):
            return
        if thread.guild is None:
            return

        # スターターメッセージを取得（キャッシュになければ fetch）
        starter = thread.starter_message
        if starter is None:
            try:
                starter = await thread.fetch_message(thread.id)
            except discord.NotFound:
                return

        if starter is None or starter.author.bot:
            return

        multi     = self.xp_multiplier()
        gained_xp = int(self.calc_gained_xp(starter.content) * multi)

        await self._grant_xp(
            guild=thread.guild,
            member=starter.author,
            gained_xp=gained_xp,
            add_to_daily=True,
            notify_channel=thread,
            multi=multi,
        )

    # ── ボイスチャンネルXP ────────────────────────────────────────
    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after:  discord.VoiceState,
    ):
        if member.bot:
            return

        guild = member.guild
        key   = (guild.id, member.id)

        before_valid = before.channel is not None and not self._is_afk(before.channel, guild)
        after_valid  = after.channel  is not None and not self._is_afk(after.channel,  guild)

        joined = after_valid  and not before_valid
        left   = before_valid and not after_valid

        if joined:
            self._voice_join_times[key] = datetime.now(JST)
            return

        if not left:
            return

        join_time = self._voice_join_times.pop(key, None)
        if join_time is None:
            return

        minutes = (datetime.now(JST) - join_time).total_seconds() / 60
        if minutes < 1:
            return

        try:
            multi        = self.xp_multiplier()
            capped_min   = min(minutes, VOICE_XP_MAX_PER_SESSION / VOICE_XP_PER_MINUTE)
            voice_gained = int(capped_min * VOICE_XP_PER_MINUTE * multi)

            await self._grant_xp(
                guild=guild,
                member=member,
                gained_xp=voice_gained,
                add_to_daily=True,
                multi=multi,
                voice_xp_gain=voice_gained,
            )
        except Exception as e:
            print(f"[XP] ボイスXP付与エラー ({member} in {guild}): {e}")

    # ── 毎日0時にXPニュース送信 ───────────────────────────────────
    @tasks.loop(time=dt_time(hour=0, minute=0, second=0, tzinfo=JST))
    async def daily_xp_report(self):
        yesterday  = datetime.now(JST) - timedelta(days=1)
        date_label = yesterday.strftime("%m/%d")
        today      = datetime.now(JST).strftime("%Y-%m-%d")
        is_weekend = yesterday.weekday() >= 5

        for guild in self.bot.guilds:
            try:
                guild_data = await self.get_guild_data(guild.id)
                channel_id = guild_data.get("xpnews_channel")

                if channel_id:
                    channel = guild.get_channel(int(channel_id))
                    if channel:
                        docs = await asyncio.to_thread(
                            lambda: list(
                                self.db.collection("guilds")
                                .document(str(guild.id))
                                .collection("members")
                                .order_by("daily_xp", direction="DESCENDING")
                                .limit(3)
                                .stream()
                            )
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
                                timestamp=datetime.now(JST),
                            )
                            embed.set_footer(text="毎日0時に集計")
                            await channel.send(embed=embed)

                # daily_xp をリセット
                all_docs = await asyncio.to_thread(
                    lambda: list(
                        self.db.collection("guilds")
                        .document(str(guild.id))
                        .collection("members")
                        .stream()
                    )
                )
                for doc in all_docs:
                    await asyncio.to_thread(
                        self.get_user_ref(guild.id, doc.id).set,
                        {"daily_xp": 0, "daily_date": today},
                        {"merge": True},
                    )

            except Exception as e:
                print(f"[XP] daily_xp_report エラー ({guild}): {e}")

    @daily_xp_report.before_loop
    async def before_daily_xp_report(self):
        await self.bot.wait_until_ready()

    # ── /rank コマンド ─────────────────────────────────────────────
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

        v_level  = data["voice_level"]
        v_xp     = data["voice_xp"]
        v_needed = self.xp_required(v_level)
        v_filled = int((v_xp / v_needed) * 20) if v_needed > 0 else 0
        v_bar    = "█" * v_filled + "░" * (20 - v_filled)

        rank_position = await self.get_rank_position(interaction.guild.id, total_xp)

        key          = (interaction.guild.id, target.id)
        voice_status = ""
        if key in self._voice_join_times:
            elapsed_min  = int((datetime.now(JST) - self._voice_join_times[key]).total_seconds() / 60)
            voice_status = f"🎙️ VC参加中（{elapsed_min}分経過）"

        embed = discord.Embed(
            title=f"📊 {target.display_name} のランク",
            color=discord.Color.blurple()
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="🏅 サーバーランク", value=f"#{rank_position}",           inline=True)
        embed.add_field(name="⭐ レベル",         value=str(level),                    inline=True)
        embed.add_field(name="🎙️ ボイスLv",       value=str(v_level),                  inline=True)
        embed.add_field(name="✨ 累計XP",         value=f"{total_xp:,}",               inline=True)
        embed.add_field(name="🔊 ボイス累計XP",   value=f"{data['voice_total_xp']:,}", inline=True)
        embed.add_field(name="📅 今日のXP",       value=f"{daily_xp:,}",               inline=True)
        embed.add_field(
            name="🎊 XP倍率",
            value=f"**×{multi:.1f}**{'　🎉週末ボーナス中！' if multi == 2.0 else ''}",
            inline=True,
        )
        if voice_status:
            embed.add_field(name="VC状態", value=voice_status, inline=True)
        embed.add_field(
            name=f"💬 XP進捗 ({current_xp} / {xp_needed})",
            value=f"`{bar}` {int(current_xp / xp_needed * 100)}%",
            inline=False,
        )
        embed.add_field(
            name=f"🎙️ ボイスXP進捗 ({v_xp} / {v_needed})",
            value=f"`{v_bar}` {int(v_xp / v_needed * 100) if v_needed > 0 else 0}%",
            inline=False,
        )
        await interaction.response.send_message(embed=embed)

    # ── /leaderboard コマンド ──────────────────────────────────────
    @app_commands.command(name="leaderboard", description="サーバーのXPランキングを表示する")
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()
        view = LeaderboardView(cog=self, guild=interaction.guild, page=0)
        await view.send(interaction)

    # ── ランク順位取得 ─────────────────────────────────────────────
    async def get_rank_position(self, guild_id: int, total_xp: int) -> int:
        docs = await asyncio.to_thread(
            lambda: list(
                self.db.collection("guilds")
                .document(str(guild_id))
                .collection("members")
                .where("total_xp", ">", total_xp)
                .stream()
            )
        )
        return len(docs) + 1


async def setup(bot, db):
    await bot.add_cog(XP(bot, db))
