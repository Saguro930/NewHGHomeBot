import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import yt_dlp
import os
import tempfile

MAX_FILE_SIZE_MB = 8
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024


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
        thumbnail  = r.get("thumbnail", "")

        if duration:
            h, rem = divmod(int(duration), 3600)
            m, s   = divmod(rem, 60)
            duration_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
        else:
            duration_str = "不明"

        view_str = f"{view_count:,} 回" if view_count else "不明"

        embed = discord.Embed(title=vtitle, url=url, color=0xFF0000)
        embed.add_field(name="📺 チャンネル", value=channel,      inline=True)
        embed.add_field(name="⏱️ 再生時間",  value=duration_str, inline=True)
        embed.add_field(name="👁️ 再生回数",  value=view_str,     inline=True)
        embed.add_field(name="🔗 URL",       value=url,          inline=False)
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
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


# ── yt-dlp 同期関数 ────────────────────────────────────────────────

def _yt_search(query: str, max_results: int = 10) -> list[dict]:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)
        return info.get("entries", [])


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
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=True)


def _fmt_duration(duration) -> str:
    if not duration:
        return "不明"
    h, rem = divmod(int(duration), 3600)
    m, s   = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# ── Cog ───────────────────────────────────────────────────────────

class YouTube(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /youtube ──────────────────────────────────────────────────

    @app_commands.command(name="youtube", description="YouTubeを検索します")
    @app_commands.describe(title="検索キーワード")
    async def youtube(self, interaction: discord.Interaction, title: str):
        await interaction.response.defer()

        try:
            results = await asyncio.to_thread(_yt_search, title)
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

    @app_commands.command(name="download", description="動画URLをダウンロードしてDiscordに投稿します")
    @app_commands.describe(url="ダウンロードしたい動画のURL（YouTube・X など）")
    async def download(self, interaction: discord.Interaction, url: str):
        await interaction.response.defer()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "%(title)s.%(ext)s")

            try:
                info = await asyncio.to_thread(_yt_download, url, output_path)
            except yt_dlp.utils.DownloadError as e:
                await interaction.followup.send(f"❌ ダウンロードに失敗しました。\n```{e}```")
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
        await interaction.response.send_message(
            f"❌ エラーが発生しました: `{error}`", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(YouTube(bot))
