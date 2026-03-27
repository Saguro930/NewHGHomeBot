import discord
from discord import app_commands
from discord.ext import commands
import os
import requests
from datetime import datetime, timedelta, timezone

OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")

JST = timezone(timedelta(hours=9))

SUMMARY_SYSTEM_PROMPT = """\
あなたはDiscordサーバーの会話を要約するアシスタントです。
以下のフォーマットで必ず日本語で出力してください。

**【会話の要約】**

> 全体的な流れを1〜2文で簡潔に説明する。

**主なトピック：**
1. **トピック名**: 内容の説明
2. **トピック名**: 内容の説明
3. **トピック名**: 内容の説明
（トピックは実際の会話に合わせて増減してください）

**全体の雰囲気：** カジュアル／真剣／雑談など一言で。
"""


def call_openrouter(text: str) -> str:
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {"role": "user",   "content": f"以下の会話を要約してください:\n\n{text}"}
        ]
    }
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json"
    }
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=30
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


class SummaryCog(commands.Cog):
    """直近メッセージを要約するCog"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /summary ──────────────────────────────────────────────────

    @app_commands.command(
        name="summary",
        description="直近のメッセージを要約します"
    )
    @app_commands.describe(count="何件のメッセージを要約するか（1〜400）")
    async def summary(self, interaction: discord.Interaction, count: int):
        if count < 1 or count > 400:
            await interaction.response.send_message(
                "❌ 1〜200件の範囲で指定してください。", ephemeral=True
            )
            return

        await interaction.response.defer()

        messages = [m async for m in interaction.channel.history(limit=count + 1)]
        messages = [m for m in reversed(messages) if not m.author.bot and m.content]

        if not messages:
            await interaction.followup.send("❌ 要約できるメッセージがありませんでした。")
            return

        text = "\n".join(f"{m.author.display_name}: {m.content}" for m in messages)

        try:
            result = call_openrouter(text)
            embed = discord.Embed(
                title="📝 要約",
                description=result,
                color=0x5865F2,
                timestamp=datetime.now(JST)
            )
            embed.set_footer(text=f"対象: {len(messages)} 件のメッセージ　|　要求者: {interaction.user.display_name}")
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"❌ 要約に失敗しました: {e}")

    # ── /summary-today（管理者のみ）────────────────────────────────

    @app_commands.command(
        name="summary-today",
        description="【管理者専用】今日送信された全メッセージを要約します"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def summary_today(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)

        today_start = datetime.now(JST).replace(hour=0, minute=0, second=0, microsecond=0)

        all_messages = []
        for channel in interaction.guild.text_channels:
            try:
                async for m in channel.history(limit=None, after=today_start):
                    if not m.author.bot and m.content:
                        all_messages.append((m.created_at, channel.name, m.author.display_name, m.content))
            except (discord.Forbidden, discord.HTTPException):
                continue

        if not all_messages:
            await interaction.followup.send("❌ 本日のメッセージが見つかりませんでした。")
            return

        # 時系列順にソート
        all_messages.sort(key=lambda x: x[0])

        # テキスト化（長すぎる場合は先頭から最大12000文字に切り詰め）
        lines = [f"[#{ch}] {name}: {content}" for _, ch, name, content in all_messages]
        text = "\n".join(lines)
        if len(text) > 12000:
            text = text[:12000] + "\n…（以下省略）"

        try:
            result = call_openrouter(text)
            embed = discord.Embed(
                title=f"📅 本日の要約（{datetime.now(JST).strftime('%Y-%m-%d')}）",
                description=result,
                color=0xE67E22,
                timestamp=datetime.now(JST)
            )
            embed.set_footer(
                text=f"対象: {len(all_messages)} 件のメッセージ　|　要求者: {interaction.user.display_name}"
            )
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"❌ 要約に失敗しました: {e}")

    # ── エラー処理 ─────────────────────────────────────────────────

    @summary_today.error
    async def summary_today_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ このコマンドは管理者のみ使用できます。", ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(SummaryCog(bot))
