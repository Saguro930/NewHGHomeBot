import os
import discord
from discord.ext import commands
from discord import app_commands
import re
from openai import OpenAI
from collections import defaultdict
import asyncio
from duckduckgo_search import DDGS

SYSTEM_PROMPT = (
    "あなたは親しみやすく優秀なAIアシスタントです。"
    "常に日本語でフレンドリーに回答してください。"
)

class AIChat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ.get("OPENROUTER_API_KEY"),
        )

        # key: channel_id (int) → list of {"role": ..., "content": ...}
        self.history: defaultdict[int, list] = defaultdict(list)
        self.MAX_HISTORY = 10  # 保持するメッセージのペア数（user+assistant）

        # key: channel_id (int) → AI種別文字列
        self.channel_settings: dict[int, str] = {}

    # --------------------------------------------------
    # スラッシュコマンド: /set-ai type:
    # --------------------------------------------------
    @app_commands.command(name="set-ai", description="このチャンネルで使用するAIの種類を変更します")
    @app_commands.describe(type="使用するAIを選択してください")
    @app_commands.choices(type=[
        app_commands.Choice(name="OpenRouter (デフォルト)", value="openrouter"),
        app_commands.Choice(name="DuckDuckGo (無料/キー不要)", value="duckduckgo"),
    ])
    async def set_ai(self, interaction: discord.Interaction, type: str):
        self.channel_settings[interaction.channel_id] = type
        # 設定変更時に履歴をリセット（AIが変わるので文脈を引き継がない）
        self.history[interaction.channel_id].clear()
        await interaction.response.send_message(
            f"✅ このチャンネルのAIを **{type}** に変更しました！（会話履歴をリセットしました）"
        )

    # --------------------------------------------------
    # DuckDuckGo 呼び出し（別スレッドで実行してボットのフリーズ防止）
    # --------------------------------------------------
    def _fetch_duckduckgo(self, messages: list[dict]) -> str:
        """messages は [{"role": "user"|"assistant", "content": str}, ...] 形式。
        DDGSはシンプルなプロンプト文字列を受け取るため、履歴を1つに結合する。"""
        history_text = ""
        for m in messages[:-1]:  # 最後のユーザーメッセージ以外を履歴として整形
            role_label = "ユーザー" if m["role"] == "user" else "AI"
            history_text += f"{role_label}: {m['content']}\n"

        latest = messages[-1]["content"]
        prompt = (
            f"{SYSTEM_PROMPT}\n\n"
            + (f"これまでの会話:\n{history_text}\n" if history_text else "")
            + f"ユーザー: {latest}"
        )

        with DDGS() as ddgs:
            return ddgs.chat(prompt, model="gpt-4o-mini")

    # --------------------------------------------------
    # 履歴へ追記し、上限を超えた分を先頭から削除
    # --------------------------------------------------
    def _append_history(self, channel_id: int, user_content: str, ai_content: str):
        hist = self.history[channel_id]
        hist.append({"role": "user",      "content": user_content})
        hist.append({"role": "assistant", "content": ai_content})

        # MAX_HISTORY ペア（= MAX_HISTORY * 2 エントリ）を超えたら古いものを削除
        max_entries = self.MAX_HISTORY * 2
        if len(hist) > max_entries:
            del hist[:len(hist) - max_entries]

    # --------------------------------------------------
    # メッセージ受信時の処理
    # --------------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        is_mention = self.bot.user in message.mentions

        # リプライ先が実際にボット自身のメッセージかチェック
        is_reply = (
            message.reference is not None
            and isinstance(message.reference.resolved, discord.Message)
            and message.reference.resolved.author == self.bot.user
        )

        if not is_mention and not is_reply:
            return

        content = re.sub(rf"<@!?{self.bot.user.id}>", "", message.content).strip()
        if not content:
            await message.reply("何か聞いてください！")
            return

        channel_id: int = message.channel.id
        current_ai_type = self.channel_settings.get(channel_id, "openrouter")

        async with message.channel.typing():
            try:
                # 現在の履歴を取得（上限分だけ）
                recent_history = self.history[channel_id][-(self.MAX_HISTORY * 2):]

                # ==========================================
                # パターンA: OpenRouter
                # ==========================================
                if current_ai_type == "openrouter":
                    messages_for_ai = [
                        {"role": "system", "content": SYSTEM_PROMPT},  # ← system ロールで分離
                        *recent_history,
                        {"role": "user", "content": content},
                    ]

                    response = self.client.chat.completions.create(
                        model="google/gemma-3n-e2b-it:free",
                        messages=messages_for_ai,
                        timeout=30.0,
                    )
                    ai_reply = response.choices[0].message.content

                # ==========================================
                # パターンB: DuckDuckGo
                # ==========================================
                elif current_ai_type == "duckduckgo":
                    messages_for_ddg = [*recent_history, {"role": "user", "content": content}]
                    ai_reply = await asyncio.to_thread(self._fetch_duckduckgo, messages_for_ddg)

                else:
                    await message.reply(f"⚠️ 不明なAI種別: `{current_ai_type}`")
                    return

                # 履歴を保存
                self._append_history(channel_id, content, ai_reply)

                # Discord の文字数制限（2000字）に対応して分割送信
                if len(ai_reply) > 2000:
                    for i in range(0, len(ai_reply), 2000):
                        await message.reply(ai_reply[i : i + 2000])
                else:
                    await message.reply(ai_reply)

            except Exception as e:
                print(f"AI Error ({current_ai_type}): {e}")
                await message.reply(
                    "⚠️ AIエラーが発生しました。\n"
                    "しばらく待ってからもう一度試してください。"
                )


async def setup(bot):
    await bot.add_cog(AIChat(bot))
