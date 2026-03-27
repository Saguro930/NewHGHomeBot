import discord
from discord import app_commands
from discord.ext import commands
import os
import requests
from dotenv import load_dotenv

load_dotenv()
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")


class SummaryCog(commands.Cog):
    """直近メッセージを要約するCog"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="summary", 
        description="直近のメッセージを要約します"
    )
    @app_commands.describe(count="何件のメッセージを要約するか（1〜200）")
    async def summary(self, interaction: discord.Interaction, count: int):
        # 件数チェック
        if count < 1 or count > 200:
            await interaction.response.send_message(
                "❌ 1〜200件の範囲で指定してください。", ephemeral=True
            )
            return

        await interaction.response.defer()  # 処理中メッセージ

        # メッセージ履歴取得（async generator対応）
        messages = [m async for m in interaction.channel.history(limit=count + 1)]
        # コマンド自体とボットメッセージを除外して逆順に
        messages = [m for m in reversed(messages) if not m.author.bot]

        # テキスト化
        text = "\n".join(f"{m.author.display_name}: {m.content}" for m in messages)

        # OpenRouter APIリクエスト
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "user", "content": f"以下の会話を簡潔に要約してください:\n{text}"}
            ]
        }
        headers = {
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": "application/json"
        }

        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=15
            )
            response.raise_for_status()
            data = response.json()
            summary = data["choices"][0]["message"]["content"]

            # 要約をフォローアップで送信
            await interaction.followup.send(f"📝 要約:\n{summary}")

        except Exception as e:
            await interaction.followup.send(f"❌ 要約に失敗しました: {e}")


# Cogをロードするための関数
async def setup(bot: commands.Bot):
    await bot.add_cog(SummaryCog(bot))
