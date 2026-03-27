import discord
from discord import app_commands
from discord.ext import commands
from duckduckgo_search import DDGS
import asyncio
from typing import Literal


def _normalize_text(r: dict) -> dict:
    """v5以前・v6以降どちらのキー名にも対応"""
    return {
        "title": r.get("title") or r.get("t") or "タイトルなし",
        "url":   r.get("href")  or r.get("url") or r.get("link") or "",
        "body":  r.get("body")  or r.get("snippet") or r.get("description") or "説明なし",
    }


def _normalize_image(r: dict) -> dict:
    """画像検索結果のキー名を正規化"""
    return {
        "title":  r.get("title") or "タイトルなし",
        "image":  r.get("image") or r.get("img") or r.get("src") or "",
        "source": r.get("url")   or r.get("source") or r.get("href") or "",
    }


def _text_search(query: str) -> list[dict]:
    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=10):
            n = _normalize_text(r)
            if n["url"]:  # URLが取れたものだけ採用
                results.append(n)
    return results


def _image_search(query: str) -> list[dict]:
    results = []
    with DDGS() as ddgs:
        for r in ddgs.images(query, max_results=10):
            n = _normalize_image(r)
            if n["image"]:  # 画像URLが取れたものだけ採用
                results.append(n)
    return results


class SearchView(discord.ui.View):
    def __init__(self, results: list[dict], is_image: bool, query: str):
        super().__init__(timeout=120)
        self.results = results
        self.is_image = is_image
        self.query = query
        self.index = 0
        self._update_buttons()

    def _update_buttons(self):
        self.prev_button.disabled = self.index == 0
        self.next_button.disabled = self.index >= len(self.results) - 1

    def make_embed(self) -> discord.Embed:
        r = self.results[self.index]
        total = len(self.results)

        if self.is_image:
            embed = discord.Embed(
                title=f"🖼️ 画像検索：{self.query}",
                description=r["title"],
                color=0x34A853
            )
            if r["image"]:
                embed.set_image(url=r["image"])
            if r["source"]:
                embed.add_field(name="🔗 ソース", value=r["source"], inline=False)
        else:
            body = r["body"]
            if len(body) > 300:
                body = body[:300] + "…"
            embed = discord.Embed(
                title=f"🔍 検索：{self.query}",
                color=0x4285F4
            )
            embed.add_field(
                name=r["title"],
                value=f"{body}\n[🔗 リンクを開く]({r['url']})",
                inline=False
            )

        embed.set_footer(text=f"{self.index + 1} / {total}　|　powered by DuckDuckGo")
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


class Search(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="search", description="ウェブ検索・画像検索を行います")
    @app_commands.describe(
        query="検索キーワード",
        image="画像検索にするか（y: 画像検索 / n: ウェブ検索）"
    )
    async def search(
        self,
        interaction: discord.Interaction,
        query: str,
        image: Literal["y", "n"] = "n"
    ):
        await interaction.response.defer()

        is_image = image == "y"

        try:
            if is_image:
                results = await asyncio.wait_for(
                    asyncio.to_thread(_image_search, query),
                    timeout=20.0
                )
            else:
                results = await asyncio.wait_for(
                    asyncio.to_thread(_text_search, query),
                    timeout=20.0
                )
        except asyncio.TimeoutError:
            await interaction.followup.send("❌ 検索がタイムアウトしました。再度お試しください。")
            return
        except Exception as e:
            await interaction.followup.send(f"❌ 検索に失敗しました: `{e}`")
            return

        if not results:
            await interaction.followup.send(
                f"{'🖼️' if is_image else '🔍'} `{query}` の検索結果が見つかりませんでした。"
            )
            return

        view = SearchView(results, is_image, query)
        await interaction.followup.send(embed=view.make_embed(), view=view)

    @search.error
    async def search_error(
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
    await bot.add_cog(Search(bot))
