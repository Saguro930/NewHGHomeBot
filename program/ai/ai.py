import os
import traceback
import asyncio
import re

import discord
from discord.ext import commands
from discord import app_commands
from openai import OpenAI, RateLimitError
from collections import defaultdict
from duckduckgo_search import DDGS

SYSTEM_PROMPT = (
    "あなたは親しみやすく優秀なAIアシスタントです。"
    "常に日本語でフレンドリーに回答してください。"
)

# /set-ai で選べるモデル一覧
# value が channel_settings に保存される（"or:" プレフィックス = OpenRouter経由）
AI_CHOICES = [
    app_commands.Choice(name="🦆 DuckDuckGo (無料/キー不要)",        value="duckduckgo"),
    app_commands.Choice(name="✨ Gemma 3n (Google・無料)",            value="or:google/gemma-3n-e2b-it:free"),
    app_commands.Choice(name="🦙 Llama 3.2 3B (Meta・無料)",         value="or:meta-llama/llama-3.2-3b-instruct:free"),
    app_commands.Choice(name="🐬 Llama 3.3 70B (Meta・無料)",        value="or:meta-llama/llama-3.3-70b-instruct:free"),
    app_commands.Choice(name="🌊 DeepSeek R1 0528 (無料)",           value="or:deepseek/deepseek-r1-0528:free"),
    app_commands.Choice(name="🔮 Qwen3 235B (Alibaba・無料)",        value="or:qwen/qwen3-235b-a22b:free"),
    app_commands.Choice(name="🌸 Mistral Small 3.2 (無料)",          value="or:mistralai/mistral-small-3.2-24b-instruct:free"),
    app_commands.Choice(name="🔵 Gemini 2.0 Flash (Google・無料)",   value="or:google/gemini-2.0-flash-exp:free"),
]

# value → 表示名の逆引きマップ
AI_CHOICE_LABEL: dict[str, str] = {c.value: c.name for c in AI_CHOICES}

# フォールバック順（DuckDuckGoを除いたORモデルのみ、リスト順）
OR_FALLBACK_ORDER: list[str] = [c.value for c in AI_CHOICES if c.value.startswith("or:")]


class AIChat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ.get("OPENROUTER_API_KEY"),
        )

        # key: channel_id → list of {"role": ..., "content": ...}
        self.history: defaultdict[int, list] = defaultdict(list)
        self.MAX_HISTORY = 10

        # key: channel_id → AI種別文字列
        self.channel_settings: dict[int, str] = {}

        # AI返答として送ったメッセージIDのセット（ようこそ等への返信を無視するため）
        self.ai_reply_message_ids: set[int] = set()
        self.MAX_TRACKED_IDS = 500

    # --------------------------------------------------
    # /set-ai
    # --------------------------------------------------
    @app_commands.command(name="set-ai", description="このチャンネルで使用するAIを変更します")
    @app_commands.describe(type="使用するAIを選択してください")
    @app_commands.choices(type=AI_CHOICES)
    async def set_ai(self, interaction: discord.Interaction, type: str):
        self.channel_settings[interaction.channel_id] = type
        self.history[interaction.channel_id].clear()
        label = AI_CHOICE_LABEL.get(type, type)
        await interaction.response.send_message(
            f"✅ このチャンネルのAIを **{label}** に変更しました！（会話履歴をリセットしました）"
        )

    # --------------------------------------------------
    # OpenRouter 単発呼び出し（429 → RateLimitError をそのまま上に投げる）
    # --------------------------------------------------
    async def _try_openrouter_once(self, messages_for_ai: list, model: str) -> str:
        response = await asyncio.to_thread(
            self.client.chat.completions.create,
            model=model,
            messages=messages_for_ai,
            timeout=30.0,
        )
        text = response.choices[0].message.content
        if not text:
            raise ValueError(f"空の返答 (finish_reason={response.choices[0].finish_reason})")
        return text

    # --------------------------------------------------
    # DuckDuckGo 呼び出し
    # --------------------------------------------------
    def _fetch_duckduckgo(self, messages: list[dict]) -> str:
        history_text = ""
        for m in messages[:-1]:
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
    # フォールバック付き呼び出し
    #   429が出たらステータスメッセージを送信・編集しながら全モデルを順に試す
    #   戻り値: (返答テキスト, 使用したモデルvalue, ステータスmsg or None)
    # --------------------------------------------------
    async def _call_with_fallback(
        self,
        origin: discord.Message,
        recent_history: list,
        content: str,
        primary: str,
    ) -> tuple[str, str, discord.Message | None]:

        messages_for_ai = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *recent_history,
            {"role": "user", "content": content},
        ]
        messages_for_ddg = [*recent_history, {"role": "user", "content": content}]

        # ── まず指定モデルを試す ──
        try:
            text = await self._try_openrouter_once(messages_for_ai, primary[3:])
            return text, primary, None
        except RateLimitError:
            pass  # フォールバックへ

        # ── 429が出たのでステータスメッセージを送信 ──
        total = len(OR_FALLBACK_ORDER) + 1  # ORモデル数 + DuckDuckGo
        status_msg: discord.Message = await origin.reply(
            "⚠️ **429 レート制限** が発生しました。他のモデルに順番に切り替えます..."
        )

        # 指定モデルを除いた残りのORモデル順にフォールバック
        fallbacks = [v for v in OR_FALLBACK_ORDER if v != primary]
        tried = 1  # 最初の試行をカウント済み

        for value in fallbacks:
            tried += 1
            label = AI_CHOICE_LABEL.get(value, value)
            await status_msg.edit(content=f"🔄 **{label}** を試行中... ({tried}/{total})")
            try:
                text = await self._try_openrouter_once(messages_for_ai, value[3:])
                return text, value, status_msg
            except RateLimitError:
                print(f"[Fallback] 429: {value}")
                continue
            except Exception as e:
                print(f"[Fallback] Error on {value}: {e}")
                continue

        # ── 全ORモデル失敗 → DuckDuckGo ──
        tried += 1
        ddg_label = AI_CHOICE_LABEL.get("duckduckgo", "🦆 DuckDuckGo")
        await status_msg.edit(content=f"🦆 **{ddg_label}** を試行中... ({tried}/{total})")
        text = await asyncio.to_thread(self._fetch_duckduckgo, messages_for_ddg)
        return text, "duckduckgo", status_msg

    # --------------------------------------------------
    # 履歴管理
    # --------------------------------------------------
    def _append_history(self, channel_id: int, user_content: str, ai_content: str):
        hist = self.history[channel_id]
        hist.append({"role": "user",      "content": user_content})
        hist.append({"role": "assistant", "content": ai_content})
        max_entries = self.MAX_HISTORY * 2
        if len(hist) > max_entries:
            del hist[:len(hist) - max_entries]

    def _track_ai_message(self, message_id: int):
        self.ai_reply_message_ids.add(message_id)
        if len(self.ai_reply_message_ids) > self.MAX_TRACKED_IDS:
            overflow = len(self.ai_reply_message_ids) - self.MAX_TRACKED_IDS
            for old_id in sorted(self.ai_reply_message_ids)[:overflow]:
                self.ai_reply_message_ids.discard(old_id)

    # --------------------------------------------------
    # on_message
    # --------------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        is_mention = self.bot.user in message.mentions

        # リプライ判定: AI返答として送ったメッセージへの返信のみ反応
        is_reply = False
        if message.reference is not None:
            ref = message.reference.resolved
            if ref is None:
                try:
                    ref = await message.channel.fetch_message(message.reference.message_id)
                except (discord.NotFound, discord.HTTPException):
                    ref = None
            if (
                ref is not None
                and isinstance(ref, discord.Message)
                and ref.author == self.bot.user
                and ref.id in self.ai_reply_message_ids
            ):
                is_reply = True

        if not is_mention and not is_reply:
            return

        content = re.sub(rf"<@!?{self.bot.user.id}>", "", message.content).strip()
        if not content:
            await message.reply("何か聞いてください！")
            return

        channel_id: int = message.channel.id
        current_ai_type = self.channel_settings.get(channel_id, "or:google/gemma-3n-e2b-it:free")
        recent_history = self.history[channel_id][-(self.MAX_HISTORY * 2):]

        async with message.channel.typing():
            try:
                # ── DuckDuckGo固定の場合 ──
                if current_ai_type == "duckduckgo":
                    messages_for_ddg = [*recent_history, {"role": "user", "content": content}]
                    ai_reply = await asyncio.to_thread(self._fetch_duckduckgo, messages_for_ddg)
                    used_model = "duckduckgo"
                    status_msg = None

                # ── OpenRouterモデル（フォールバック付き）──
                elif current_ai_type.startswith("or:"):
                    ai_reply, used_model, status_msg = await self._call_with_fallback(
                        message, recent_history, content, current_ai_type
                    )

                else:
                    await message.reply(f"⚠️ 不明なAI種別: `{current_ai_type}`")
                    return

                self._append_history(channel_id, content, ai_reply)

                # フォールバックが起きた場合はステータスメッセージを完了表示に更新
                if status_msg is not None:
                    used_label = AI_CHOICE_LABEL.get(used_model, used_model)
                    await status_msg.edit(content=f"✅ **{used_label}** で代替応答しました。")

                # 返答を送信（2000字超はチェーン）
                chunks = [ai_reply[i: i + 2000] for i in range(0, len(ai_reply), 2000)]
                last_sent: discord.Message = await message.reply(chunks[0])
                self._track_ai_message(last_sent.id)

                for chunk in chunks[1:]:
                    last_sent = await last_sent.reply(chunk)
                    self._track_ai_message(last_sent.id)

            except Exception as e:
                print(f"AI Error ({current_ai_type}):\n{traceback.format_exc()}")
                await message.reply(
                    f"⚠️ AIエラーが発生しました。\n"
                    f"```\n{type(e).__name__}: {e}\n```"
                )


async def setup(bot):
    await bot.add_cog(AIChat(bot))
