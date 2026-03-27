import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import yt_dlp
import os
import tempfile

MAX_FILE_SIZE_MB = 8
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

YOUTUBE_DOMAINS = ("youtube.com", "youtu.be", "www.youtube.com", "m.youtube.com")


def _is_youtube(url: str) -> bool:
    return any(d in url for d in YOUTUBE_DOMAINS)


# ── yt-dlp 同期関数 ────────────────────────────────────────────────

def _yt_search(query: str, max_results: int = 10) -> list[dict]:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "socket_timeout": 10,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)
        return info.get("entries", []) if info else []


def _yt_download(url: str, output_path: str) -> dict:
    ydl_opts = {
        "outtmpl": output_path,
        "format": (
            "bestvideo[ext=mp4][filesize<7M]+bestaudio[ext=m4a]"
            "/best[ext=mp4][filesize<7M]"
            "/best[filesize<7M]"
            "/best"
        ),
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 15,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=True)


def _fmt_duration(duration) -> str:
    if not duration:
        return "不明"
    h, rem = divmod(int(duration), 3600)
    m, s   = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# ── YouTube検索用ページネーション ──────────────────────────────────

class YouTubeView(discord.ui.View):
    def __init__(self, results: list[dict], title: str):
        super().__init__(timeout=120)
        self.results = results
        self.title = title
        self.index = 0
        self._update_buttons()

    def _update_buttons(self):
        self.prev_button.disabled = self.index == 0
        self.next_button.disabled = self.index >= len(self.results) - 1

    def make_embed(self) -> discord.Embed:
        r = self.results[self.index]
        total = len(self.results)

        video_id   = r.get("id", "")
        url        = f"https://www.youtube.com/watch?v={video_id}"
        vtitle     = r.get("title", "タイトルなし")
        channel    = r.get("channel", "不明")
        duration   = r.get("duration")
        view_count = r.get("view_count")

        # サムネイルURLを最高解像度から順に試す
        thumbnail = (
            f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
            if video_id else r.get("thumbnail", "")
        )

        duration_str = _fmt_duration(duration)
        view_str = f"{view_count:,} 回" if view_count else "不明"

        embed = discord.Embed(title=vtitle, url=url, color=0xFF0000)
        embed.add_field(name="📺 チャンネル", value=channel,      inline=True)
        embed.add_field(name="⏱️ 再生時間",  value=duration_str, inline=True)
        embed.add_field(name="👁️ 再生回数",  value=view_str,     inline=True)
        embed.add_field(name="🔗 URL",       value=url,          inline=False)

        # サムネイルを大きく表示
        if thumbnail:
            embed.set_image(url=thumbnail)

        embed.set_footer(text=f"{self.index + 1} / {total}　|　🔍 {self.title}")
        return embed

    @discord.ui.button(emoji="⬅️", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @discord.ui.button(emoji="➡️", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ── Cog ───────────────────────────────────────────────────────────

class YouTube(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        await asyncio.to_thread(self._warmup)

    @staticmethod
    def _warmup():
        try:
            with yt_dlp.YoutubeDL({"quiet": True}):
                pass
        except Exception:
            pass

    # ── /youtube ──────────────────────────────────────────────────

    @app_commands.command(name="youtube", description="YouTubeを検索します")
    @app_commands.describe(title="検索キーワード")
    async def youtube(self, interaction: discord.Interaction, title: str):
        await interaction.response.defer()

        try:
            results = await asyncio.wait_for(
                asyncio.to_thread(_yt_search, title),
                timeout=25.0
            )
        except asyncio.TimeoutError:
            await interaction.followup.send("❌ 検索がタイムアウトしました。再度お試しください。")
            return
        except Exception as e:
            await interaction.followup.send(f"❌ 検索に失敗しました: `{e}`")
            return

        results = [r for r in results if r and r.get("id")]
        if not results:
            await interaction.followup.send(f"🎬 `{title}` の検索結果が見つかりませんでした。")
            return

        view = YouTubeView(results, title)
        await interaction.followup.send(embed=view.make_embed(), view=view)

    # ── /download ─────────────────────────────────────────────────

    @app_commands.command(name="download", description="動画URLをダウンロードしてDiscordに投稿します（YouTube不可）")
    @app_commands.describe(url="ダウンロードしたい動画のURL（X・TikTok・Instagram など）")
    async def download(self, interaction: discord.Interaction, url: str):
        await interaction.response.defer()

        # YouTubeはBot判定で弾かれるため事前に拒否
        if _is_youtube(url):
            embed = discord.Embed(
                title="⚠️ YouTubeはダウンロード不可",
                description=(
                    "YouTubeはBot判定によりダウンロードがブロックされています。\n\n"
                    "**対応しているサイト例：**\n"
                    "・X (Twitter)\n"
                    "・TikTok\n"
                    "・Instagram\n"
                    "・ニコニコ動画\n"
                    "・その他1000以上のサイト"
                ),
                color=0xE74C3C
            )
            await interaction.followup.send(embed=embed)
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "%(title)s.%(ext)s")

            try:
                info = await asyncio.wait_for(
                    asyncio.to_thread(_yt_download, url, output_path),
                    timeout=60.0
                )
            except asyncio.TimeoutError:
                await interaction.followup.send("❌ ダウンロードがタイムアウトしました。")
                return
            except yt_dlp.utils.DownloadError as e:
                err_str = str(e)
                # Bot判定エラーの場合は分かりやすいメッセージを表示
                if "Sign in" in err_str or "bot" in err_str.lower():
                    await interaction.followup.send(
                        "❌ このサイトはBot判定によりダウンロードがブロックされました。"
                    )
                else:
                    await interaction.followup.send(f"❌ ダウンロードに失敗しました。\n```{err_str[:500]}```")
                return
            except Exception as e:
                await interaction.followup.send(f"❌ エラーが発生しました: `{e}`")
                return

            files = [f for f in os.listdir(tmpdir) if os.path.isfile(os.path.join(tmpdir, f))]
            if not files:
                await interaction.followup.send("❌ ファイルが見つかりませんでした。")
                return

            filepath = os.path.join(tmpdir, files[0])
            filesize = os.path.getsize(filepath)

            title    = info.get("title", "動画")
            uploader = info.get("uploader") or info.get("channel", "不明")
            webpage  = info.get("webpage_url", url)

            embed = discord.Embed(title=f"🎬 {title}", url=webpage, color=0xFF0000)
            embed.add_field(name="👤 投稿者",  value=uploader,                            inline=True)
            embed.add_field(name="⏱️ 時間",   value=_fmt_duration(info.get("duration")), inline=True)
            embed.add_field(name="📦 サイズ", value=f"{filesize / 1024 / 1024:.1f} MB",  inline=True)
            embed.set_footer(text=f"要求者: {interaction.user.display_name}")

            if filesize > MAX_FILE_SIZE_BYTES:
                embed.color = 0xE74C3C
                embed.add_field(
                    name="⚠️ サイズ超過",
                    value=(
                        f"ファイルが {filesize / 1024 / 1024:.1f} MB あり、"
                        f"上限（{MAX_FILE_SIZE_MB} MB）を超えています。\n"
                        f"[🔗 元のURLで視聴]({webpage})"
                    ),
                    inline=False
                )
                await interaction.followup.send(embed=embed)
                return

            file = discord.File(filepath, filename=files[0])
            await interaction.followup.send(embed=embed, file=file)

    # ── エラー処理 ────────────────────────────────────────────────

    @youtube.error
    @download.error
    async def cmd_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError
    ):
        if not interaction.response.is_done():
            await interaction.response.send_message(
                f"❌ エラーが発生しました: `{error}`", ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"❌ エラーが発生しました: `{error}`", ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(YouTube(bot))
