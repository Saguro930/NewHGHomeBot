import os
import discord
from discord.ext import commands
from discord import app_commands  # スラッシュコマンド用に必要
import re
from openai import OpenAI
from collections import defaultdict
import asyncio
from duckduckgo_search import DDGS  # DuckDuckGo用に必要

class AIChat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # OpenRouterのクライアント設定
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ.get("OPENROUTER_API_KEY"),
        )

        self.history = defaultdict(list)
        self.MAX_HISTORY = 10
        
        # チャンネルごとのAI設定を保持する辞書 (デフォルトは未設定)
        self.channel_settings = {}

    # --------------------------------------------------
    # スラッシュコマンド: /set-ai type:
    # --------------------------------------------------
    @app_commands.command(name="set-ai", description="このチャンネルで使用するAIの種類を変更します")
    @app_commands.describe(type="使用するAIを選択してください")
    @app_commands.choices(type=[
        app_commands.Choice(name="OpenRouter (デフォルト)", value="openrouter"),
        app_commands.Choice(name="DuckDuckGo (無料/キー不要)", value="duckduckgo")
    ])
    async def set_ai(self, interaction: discord.Interaction, type: str):
        # 実行されたチャンネルIDに設定を保存
        self.channel_settings[interaction.channel_id] = type
        await interaction.response.send_message(f"✅ このチャンネルのAIを **{type}** に変更しました！")

    # --------------------------------------------------
    # DuckDuckGo呼び出し用の非同期関数 (ボットのフリーズ防止)
    # --------------------------------------------------
    def _fetch_duckduckgo(self, prompt_text: str):
        with DDGS() as ddgs:
            return ddgs.chat(prompt_text, model="gpt-4o-mini")

    # --------------------------------------------------
    # メッセージ受信時の処理
    # --------------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        is_mention = self.bot.user in message.mentions
        is_reply = (
            message.reference
            and message.reference.resolved
            and message.reference.resolved.author == self.bot.user
        )

        if not is_mention and not is_reply:
            return

        content = re.sub(f'<@{self.bot.user.id}>', '', message.content).strip()
        if not content:
            return

        async with message.channel.typing():
            try:
                history_key = str(message.channel.id)
                
                # 現在のチャンネルの設定を取得 (デフォルトは openrouter)
                current_ai_type = self.channel_settings.get(message.channel.id, "openrouter")

                # ==========================================
                # パターンA: OpenRouter を使用する場合
                # ==========================================
                if current_ai_type == "openrouter":
                    messages_for_ai = []
                    for h in self.history[history_key][-self.MAX_HISTORY:]:
                        messages_for_ai.append(h)

                    prompt = (
                        "【設定：あなたは親しみやすく優秀なAIです。"
                        "日本語でフレンドリーに回答してください。】\n"
                        f"質問：{content}"
                    )
                    messages_for_ai.append({"role": "user", "content": prompt})

                    response = self.client.chat.completions.create(
                        model="google/gemma-3n-e2b-it:free",
                        messages=messages_for_ai,
                        timeout=30.0
                    )
                    ai_reply = response.choices[0].message.content

                # ==========================================
                # パターンB: DuckDuckGo を使用する場合
                # ==========================================
                elif current_ai_type == "duckduckgo":
                    # DuckDuckGoは履歴の構造が違うため、シンプルなプロンプトにまとめる
                    prompt = f"以下の質問に日本語でフレンドリーに答えてください。\n質問: {content}"
                    
                    # ネットワーク通信でボットが止まらないよう別スレッドで実行
                    ai_reply = await asyncio.to_thread(self._fetch_duckduckgo, prompt)

                # ==========================================
                # 履歴の保存と送信
                # ==========================================
                self.history[history_key].append({"role": "user", "content": content})
                self.history[history_key].append({"role": "assistant", "content": ai_reply})

                # 文字数制限対策
                if len(ai_reply) > 2000:
                    for i in range(0, len(ai_reply), 2000):
                        await message.reply(ai_reply[i:i+2000])
                else:
                    await message.reply(ai_reply)

            except Exception as e:
                print(f"AI Error: {e}")
                await message.reply(
                    "⚠️ AIエラーが発生しました。\n"
                    "しばらく待ってからもう一度試してください。"
                )

async def setup(bot):
    await bot.add_cog(AIChat(bot))
