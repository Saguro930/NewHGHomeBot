import discord
from discord.ext import commands
from discord import app_commands
from deep_translator import GoogleTranslator
import asyncio

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  対応言語テーブル（/translate の choices に使用）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LANGUAGES = [
    app_commands.Choice(name="🇯🇵 日本語",   value="ja"),
    app_commands.Choice(name="🇺🇸 英語",     value="en"),
    app_commands.Choice(name="🇰🇷 韓国語",   value="ko"),
    app_commands.Choice(name="🇨🇳 中国語",   value="zh-CN"),
    app_commands.Choice(name="🇫🇷 フランス語", value="fr"),
    app_commands.Choice(name="🇩🇪 ドイツ語",  value="de"),
    app_commands.Choice(name="🇪🇸 スペイン語", value="es"),
    app_commands.Choice(name="🇷🇺 ロシア語",  value="ru"),
    app_commands.Choice(name="🇵🇹 ポルトガル語", value="pt"),
    app_commands.Choice(name="🇮🇹 イタリア語", value="it"),
]

# 言語コード → 表示名のマップ（Embed表示用）
LANG_NAMES = {c.value: c.name for c in LANGUAGES}

# 国旗絵文字 → 翻訳先言語コード
FLAG_TO_LANG: dict[str, str] = {
    "🇯🇵": "ja",
    "🇺🇸": "en",
    "🇰🇷": "ko",
    "🇨🇳": "zh-CN",
    "🇫🇷": "fr",
    "🇩🇪": "de",
    "🇪🇸": "es",
    "🇷🇺": "ru",
    "🇵🇹": "pt",
    "🇮🇹": "it",
}


def _do_translate(text: str, target: str) -> str:
    """同期翻訳処理（to_thread で呼び出す）"""
    return GoogleTranslator(source="auto", target=target).translate(text)


def _detect_lang(text: str) -> str:
    """言語検出（翻訳時に source を auto にすれば内部で検出される）"""
    # deep_translator は source="auto" で自動判定するため別途検出不要
    return "auto"


class Translator(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # 翻訳済みメッセージのキャッシュ（同じメッセージへの多重翻訳を防ぐ）
        # key: (message_id, target_lang), value: True
        self._translated_cache: set[tuple[int, str]] = set()

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  /translate コマンド
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    @app_commands.command(name="translate", description="指定したテキストを好きな言語に翻訳します")
    @app_commands.describe(
        text="翻訳したいテキスト",
        language="翻訳先の言語",
    )
    @app_commands.choices(language=LANGUAGES)
    async def translate(
        self,
        interaction: discord.Interaction,
        text: str,
        language: app_commands.Choice[str],
    ):
        await interaction.response.defer()

        try:
            result = await asyncio.to_thread(_do_translate, text, language.value)
        except Exception as e:
            await interaction.followup.send(
                f"❌ 翻訳に失敗しました: `{e}`", ephemeral=True
            )
            return

        embed = discord.Embed(title="🌐 翻訳結果", color=0x3498DB)
        embed.add_field(name="📝 原文",  value=f"```{text}```",   inline=False)
        embed.add_field(name=f"✅ {language.name}", value=f"```{result}```", inline=False)
        embed.set_footer(text=f"翻訳者: {interaction.user.display_name}　powered by Google Translate")
        await interaction.followup.send(embed=embed)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  国旗リアクションで自動翻訳
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        # Bot 自身のリアクションは無視
        if payload.user_id == self.bot.user.id:
            return

        emoji = str(payload.emoji)
        target_lang = FLAG_TO_LANG.get(emoji)
        if target_lang is None:
            return

        # 同じメッセージ × 同じ言語への多重翻訳を防ぐ
        cache_key = (payload.message_id, target_lang)
        if cache_key in self._translated_cache:
            return
        self._translated_cache.add(cache_key)

        # キャッシュが膨らみすぎないよう上限を設ける
        if len(self._translated_cache) > 500:
            self._translated_cache.clear()

        # メッセージ・チャンネルを取得
        channel = self.bot.get_channel(payload.channel_id)
        if channel is None:
            return

        try:
            message = await channel.fetch_message(payload.message_id)
        except (discord.NotFound, discord.Forbidden):
            return

        # 翻訳するテキストを決定（埋め込みがある場合は本文優先）
        text = message.content.strip()
        if not text:
            # 本文がなければ Embed の description を試みる
            if message.embeds and message.embeds[0].description:
                text = message.embeds[0].description.strip()
            else:
                return   # 翻訳できるテキストなし

        # 翻訳実行
        try:
            result = await asyncio.to_thread(_do_translate, text, target_lang)
        except Exception as e:
            await channel.send(f"❌ 翻訳に失敗しました: `{e}`", delete_after=10)
            return

        lang_name = LANG_NAMES.get(target_lang, target_lang)

        embed = discord.Embed(
            title=f"🌐 {emoji}　{lang_name} に翻訳",
            color=0x2ECC71,
        )
        embed.add_field(
            name="📝 原文",
            value=f"```{text[:900]}```",   # Discord のフィールド上限対策
            inline=False,
        )
        embed.add_field(
            name=f"✅ 翻訳結果",
            value=f"```{result[:900]}```",
            inline=False,
        )
        embed.set_footer(
            text=f"リアクションした人: {payload.member.display_name if payload.member else 'Unknown'}"
                 f"　|　元メッセージ: {message.author.display_name}"
        )

        # 元メッセージへの返信として送る
        try:
            await message.reply(embed=embed, mention_author=False)
        except discord.Forbidden:
            await channel.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Translator(bot))
