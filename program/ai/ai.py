import os
import logging
import traceback
import discord
from discord.ext import commands
from discord import app_commands
import re
from openai import OpenAI
from collections import defaultdict
import asyncio
from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)

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

        # ボットがAI返答として送信したメッセージのIDを記録するセット
        # ようこそメッセージ等の「別機能が送ったボットメッセージ」への返信を無視するため
        self.ai_reply_message_ids: set[int] = set()
        # メモリ肥大化を防ぐ上限（古いIDは自動削除）
        self.MAX_TRACKED_IDS = 500

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
    # AI返答メッセージIDを記録（上限超えで古いIDを削除）
    # --------------------------------------------------
    def _track_ai_message(self, message_id: int):
        self.ai_reply_message_ids.add(message_id)
        # 上限を超えたら古い順に削除（setは順序なしなので一旦変換）
        if len(self.ai_reply_message_ids) > self.MAX_TRACKED_IDS:
            overflow = len(self.ai_reply_message_ids) - self.MAX_TRACKED_IDS
            old_ids = sorted(self.ai_reply_message_ids)[:overflow]
            for old_id in old_ids:
                self.ai_reply_message_ids.discard(old_id)

    # --------------------------------------------------
    # メッセージ受信時の処理
    # --------------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        is_mention = self.bot.user in message.mentions

        # ── リプライ判定 ──────────────────────────────────────
        # 条件: リプライ先が「このCogがAI返答として送ったメッセージ」のみ
        # ようこそメッセージ・通知など他機能のボットメッセージへの返信は無視する
        is_reply = False
        if message.reference is not None:
            ref = message.reference.resolved
            # resolved が None の場合（未キャッシュ）は fetch して確認
            if ref is None:
                try:
                    ref = await message.channel.fetch_message(message.reference.message_id)
                except (discord.NotFound, discord.HTTPException):
                    ref = None

            if (
                ref is not None
                and isinstance(ref, discord.Message)
                and ref.author == self.bot.user
                and ref.id in self.ai_reply_message_ids  # ← AI返答IDのみ反応
            ):
                is_reply = True
        # ────────────────────────────────────────────────────

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
                        {"role": "system", "content": SYSTEM_PROMPT},
                        *recent_history,
                        {"role": "user", "content": content},
                    ]

                    response = self.client.chat.completions.create(
                        model="google/gemma-3n-e2b-it:free",
                        messages=messages_for_ai,
                        timeout=30.0,
                    )

                    # モデルによっては content が None を返すことがある
                    ai_reply = response.choices[0].message.content
                    if not ai_reply:
                        finish_reason = response.choices[0].finish_reason
                        raise ValueError(
                            f"モデルから空の返答が返りました (finish_reason: {finish_reason})\n"
                            f"モデル名が間違っているか、レート制限の可能性があります。"
                        )

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
                # 先頭だけ元メッセージへのリプライ、続きは前のチャンクへのリプライにチェーン
                chunks = [ai_reply[i: i + 2000] for i in range(0, len(ai_reply), 2000)]
                last_sent: discord.Message = await message.reply(chunks[0])
                self._track_ai_message(last_sent.id)

                for chunk in chunks[1:]:
                    last_sent = await last_sent.reply(chunk)
                    self._track_ai_message(last_sent.id)

            except Exception as e:
                # エラー内容をコンソールとDiscord両方に出力（原因特定のため）
                import traceback
                error_detail = traceback.format_exc()
                print(f"AI Error ({current_ai_type}):\n{error_detail}")
                await message.reply(
                    f"⚠️ AIエラーが発生しました。\n"
                    f"```\n{type(e).__name__}: {e}\n```\n"
                    f"このメッセージをbotの管理者に共有してください。"
                )


async def setup(bot):
    await bot.add_cog(AIChat(bot))
