import os
import discord
from discord.ext import commands
import re
from openai import OpenAI
from collections import defaultdict

class AIChat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ.get("OPENROUTER_API_KEY"),
        )

        self.history = defaultdict(list)
        self.MAX_HISTORY = 10

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

                messages_for_ai = []

                for h in self.history[history_key][-self.MAX_HISTORY:]:
                    messages_for_ai.append(h)

                prompt = (
                    "【設定：あなたは親しみやすく優秀なAIです。"
                    "日本語でフレンドリーに回答してください。】\n"
                    f"質問：{content}"
                )

                messages_for_ai.append(
                    {"role": "user", "content": prompt}
                )

                response = self.client.chat.completions.create(
                    model="google/gemma-3n-e2b-it:free",
                    messages=messages_for_ai,
                    timeout=30.0
                )

                ai_reply = response.choices[0].message.content

                self.history[history_key].append(
                    {"role": "user", "content": content}
                )
                self.history[history_key].append(
                    {"role": "assistant", "content": ai_reply}
                )

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
