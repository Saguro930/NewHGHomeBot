import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timezone
import asyncio
import feedparser

# ── Nitter インスタンス（稼働率順）──────────────────────────────
NITTER_INSTANCES = [
    "https://nitter.net",
    "https://xcancel.com",
    "https://lightbrd.com",
    "https://nuku.trabun.org",
    "https://nitter.space",
    "https://nitter.privacyredirect.com",
    "https://nitter.poast.org",
    "https://nitter.uni-sonia.com",
    "https://nitter.catsarch.com",
]

async def fetch_rss(username: str) -> tuple[list, dict]:
    """Nitter RSS から最新ツイートを取得（全インスタンスをフォールバック）"""
    loop = asyncio.get_event_loop()
    for instance in NITTER_INSTANCES:
        url = f"{instance}/{username}/rss"
        try:
            feed = await loop.run_in_executor(None, feedparser.parse, url)
            if feed.entries:
                return feed.entries, feed.feed
        except Exception:
            continue
    return [], {}


class XNotifier(commands.Cog):
    def __init__(self, bot, db):
        self.bot = bot
        self.db  = db
        self.check_x.start()

    def cog_unload(self):
        self.check_x.cancel()

    # ── Firestore 参照 ────────────────────────────────────────────

    def guild_ref(self, guild_id: int):
        return self.db.collection("guilds").document(str(guild_id))

    def x_col(self, guild_id: int):
        return self.guild_ref(guild_id).collection("x")

    # ── 5分ごとにチェック ─────────────────────────────────────────

    @tasks.loop(minutes=5)
    async def check_x(self):
        for guild in self.bot.guilds:
            try:
                await self._check_guild(guild)
            except Exception as e:
                print(f"[X] {guild.name} チェックエラー: {e}")

    @check_x.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    async def _check_guild(self, guild: discord.Guild):
        doc  = self.guild_ref(guild.id).get()
        data = doc.to_dict() if doc.exists else {}

        # 通知チャンネル未設定はスキップ
        channel_id = data.get("x_channel")
        if not channel_id:
            return
        channel = guild.get_channel(int(channel_id))
        if not channel:
            return

        accounts = list(self.x_col(guild.id).stream())
        if not accounts:
            return

        for acc_doc in accounts:
            acc_data = acc_doc.to_dict()
            username = acc_data.get("username")
            last_id  = acc_data.get("last_tweet_id")

            if not username:
                continue

            entries, feed_info = await fetch_rss(username)
            if not entries:
                print(f"[X] @{username} RSS取得失敗（全インスタンス試行済み）")
                continue

            # 初回は最新1件のIDだけ保存してスキップ
            if not last_id:
                self.x_col(guild.id).document(username).update({
                    "last_tweet_id": entries[0].get("id", "")
                })
                continue

            # last_id より新しいエントリだけ抽出
            to_notify = []
            for entry in entries:
                if entry.get("id", "") == last_id:
                    break
                to_notify.append(entry)

            # 古い順に通知
            for entry in reversed(to_notify):
                embed = self._make_embed(entry, username, feed_info)
                await channel.send(embed=embed)
                await asyncio.sleep(1)  # 連投防止

            if to_notify:
                self.x_col(guild.id).document(username).update({
                    "last_tweet_id": to_notify[0].get("id", "")
                })

    def _make_embed(self, entry: dict, username: str, feed_info: dict) -> discord.Embed:
        title     = entry.get("title", "")
        link      = entry.get("link", f"https://x.com/{username}")
        summary   = entry.get("summary", "")
        published = entry.get("published_parsed")

        # nitter URL → x.com URL に変換
        for instance in NITTER_INSTANCES:
            if instance in link:
                link = link.replace(instance, "https://x.com")
                break

        # RT・リプライ判定
        is_rt    = summary.startswith("RT @")
        is_reply = title.startswith("R to @")

        color = 0x1DA1F2
        if is_rt:
            color = 0x17BF63
        elif is_reply:
            color = 0x794BC4

        embed = discord.Embed(
            description=summary[:2000] if summary else title,
            color=color,
            url=link
        )

        icon_url     = feed_info.get("image", {}).get("href") or \
                       "https://abs.twimg.com/favicons/twitter.3.ico"
        display_name = feed_info.get("title", f"@{username}").strip()

        embed.set_author(
            name=f"{display_name} (@{username})",
            url=f"https://x.com/{username}",
            icon_url=icon_url
        )

        if published:
            embed.timestamp = datetime(*published[:6], tzinfo=timezone.utc)

        label = "🔁 リツイート" if is_rt else ("↩️ リプライ" if is_reply else "🐦 新しいポスト")
        embed.set_footer(text=label)

        return embed

    # ── /set-x ───────────────────────────────────────────────────

    @app_commands.command(name="set-x", description="X の通知を送信するチャンネルを設定します")
    @app_commands.describe(channel="通知を送るチャンネル")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_x(self, interaction: discord.Interaction, channel: discord.TextChannel):
        self.guild_ref(interaction.guild.id).set(
            {"x_channel": channel.id}, merge=True
        )
        await interaction.response.send_message(
            f"✅ X通知チャンネルを {channel.mention} に設定しました。",
            ephemeral=True
        )

    # ── /set-xaccount ────────────────────────────────────────────

    @app_commands.command(name="set-xaccount", description="通知するXアカウントを追加・削除します")
    @app_commands.describe(username="XのユーザーID（@なし）")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_xaccount(
        self,
        interaction: discord.Interaction,
        username: str
    ):
        await interaction.response.defer(ephemeral=True)
        username = username.lstrip("@").strip()
        ref = self.x_col(interaction.guild.id).document(username)

        if ref.get().exists:
            # 登録済みなら削除
            ref.delete()
            await interaction.followup.send(
                f"🗑 **@{username}** の通知を解除しました。",
                ephemeral=True
            )
        else:
            # 存在確認
            entries, _ = await fetch_rss(username)
            if not entries:
                await interaction.followup.send(
                    f"❌ **@{username}** のRSSを取得できませんでした。\n"
                    f"ユーザー名が正しいか確認してください。",
                    ephemeral=True
                )
                return

            ref.set({
                "username":      username,
                "last_tweet_id": entries[0].get("id", ""),
            })
            await interaction.followup.send(
                f"✅ **@{username}** の新着ポストを通知するよう設定しました。\n"
                f"📋 次回チェックから通知が始まります（最大5分）",
                ephemeral=True
            )

    # ── /x-list ──────────────────────────────────────────────────

    @app_commands.command(name="x-list", description="通知中のXアカウント一覧を表示します")
    @app_commands.checks.has_permissions(administrator=True)
    async def x_list(self, interaction: discord.Interaction):
        docs = list(self.x_col(interaction.guild.id).stream())
        doc  = self.guild_ref(interaction.guild.id).get()
        data = doc.to_dict() if doc.exists else {}

        channel_id      = data.get("x_channel")
        channel_mention = f"<#{channel_id}>" if channel_id else "未設定"

        if not docs:
            await interaction.response.send_message(
                f"📋 通知チャンネル：{channel_mention}\n"
                f"監視中のアカウントはありません。",
                ephemeral=True
            )
            return

        names = "\n".join(f"・@{d.to_dict().get('username')}" for d in docs)
        await interaction.response.send_message(
            f"📋 通知チャンネル：{channel_mention}\n\n"
            f"**監視中のアカウント**\n{names}",
            ephemeral=True
        )

    # ── エラー処理 ────────────────────────────────────────────────

    @set_x.error
    @set_xaccount.error
    @x_list.error
    async def perm_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ このコマンドは管理者のみ使用できます。", ephemeral=True
            )


# ── Cog登録 ──────────────────────────────────────────────────────

async def setup(bot, db):
    await bot.add_cog(XNotifier(bot, db))
