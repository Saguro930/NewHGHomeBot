import discord
from discord import app_commands
from discord.ext import commands
from duckduckgo_search import DDGS
import asyncio


class Search(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="search", description="ウェブ検索を行います")
    @app_commands.describe(query="検索キーワード")
    async def search(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()

        try:
            results = await asyncio.to_thread(self._search, query)
        except Exception as e:
            await interaction.followup.send(f"❌ 検索に失敗しました: `{e}`")
            return

        if not results:
            await interaction.followup.send(f"🔍 `{query}` の検索結果が見つかりませんでした。")
            return

        embed = discord.Embed(
            title=f"🔍 検索結果：{query}",
            color=0x4285F4
        )

        for i, r in enumerate(results, 1):
            title = r.get("title", "タイトルなし")
            url   = r.get("href", "")
            body  = r.get("body", "説明なし")
            # フィールドの文字数上限対策
            if len(body) > 200:
                body = body[:200] + "…"
            embed.add_field(
                name=f"{i}. {title}",
                value=f"{body}\n[🔗 リンクを開く]({url})",
                inline=False
            )

        embed.set_footer(text=f"powered by DuckDuckGo　|　要求者: {interaction.user.display_name}")
        await interaction.followup.send(embed=embed)

    def _search(self, query: str) -> list[dict]:
        """同期処理（to_thread で呼び出す）"""
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=5))

    @search.error
    async def search_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError
    ):
        await interaction.response.send_message(
            f"❌ エラーが発生しました: `{error}`", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Search(bot))
