import discord
from discord.ext import commands
from discord import app_commands
from deep_translator import GoogleTranslator
import asyncio

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  対応言語テーブル（/translate の choices に使用）
#  ※ Discord の choices 上限は25件のため /translate は25言語まで
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LANGUAGES = [
    app_commands.Choice(name="🇯🇵 日本語",         value="ja"),
    app_commands.Choice(name="🇺🇸 英語",           value="en"),
    app_commands.Choice(name="🇰🇷 韓国語",         value="ko"),
    app_commands.Choice(name="🇨🇳 中国語(簡体)",   value="zh-CN"),
    app_commands.Choice(name="🇹🇼 中国語(繁体)",   value="zh-TW"),
    app_commands.Choice(name="🇫🇷 フランス語",     value="fr"),
    app_commands.Choice(name="🇩🇪 ドイツ語",       value="de"),
    app_commands.Choice(name="🇪🇸 スペイン語",     value="es"),
    app_commands.Choice(name="🇷🇺 ロシア語",       value="ru"),
    app_commands.Choice(name="🇵🇹 ポルトガル語",   value="pt"),
    app_commands.Choice(name="🇮🇹 イタリア語",     value="it"),
    app_commands.Choice(name="🇸🇦 アラビア語",     value="ar"),
    app_commands.Choice(name="🇮🇳 ヒンディー語",   value="hi"),
    app_commands.Choice(name="🇹🇭 タイ語",         value="th"),
    app_commands.Choice(name="🇻🇳 ベトナム語",     value="vi"),
    app_commands.Choice(name="🇮🇩 インドネシア語", value="id"),
    app_commands.Choice(name="🇲🇾 マレー語",       value="ms"),
    app_commands.Choice(name="🇳🇱 オランダ語",     value="nl"),
    app_commands.Choice(name="🇵🇱 ポーランド語",   value="pl"),
    app_commands.Choice(name="🇸🇪 スウェーデン語", value="sv"),
    app_commands.Choice(name="🇳🇴 ノルウェー語",   value="no"),
    app_commands.Choice(name="🇩🇰 デンマーク語",   value="da"),
    app_commands.Choice(name="🇫🇮 フィンランド語", value="fi"),
    app_commands.Choice(name="🇹🇷 トルコ語",       value="tr"),
    app_commands.Choice(name="🇬🇷 ギリシャ語",     value="el"),
]

# 言語コード → 表示名のマップ（Embed表示用）
LANG_NAMES = {c.value: c.name for c in LANGUAGES}

# 国旗絵文字 → 翻訳先言語コード（リアクション翻訳用・25件制限なし）
FLAG_TO_LANG: dict[str, str] = {
    "🇯🇵": "ja",
    "🇺🇸": "en",
    "🇬🇧": "en",
    "🇰🇷": "ko",
    "🇨🇳": "zh-CN",
    "🇹🇼": "zh-TW",
    "🇭🇰": "zh-TW",
    "🇫🇷": "fr",
    "🇩🇪": "de",
    "🇪🇸": "es",
    "🇲🇽": "es",
    "🇦🇷": "es",
    "🇷🇺": "ru",
    "🇵🇹": "pt",
    "🇧🇷": "pt",
    "🇮🇹": "it",
    "🇸🇦": "ar",
    "🇦🇪": "ar",
    "🇪🇬": "ar",
    "🇮🇳": "hi",
    "🇹🇭": "th",
    "🇻🇳": "vi",
    "🇮🇩": "id",
    "🇲🇾": "ms",
    "🇳🇱": "nl",
    "🇵🇱": "pl",
    "🇸🇪": "sv",
    "🇳🇴": "no",
    "🇩🇰": "da",
    "🇫🇮": "fi",
    "🇹🇷": "tr",
    "🇬🇷": "el",
    "🇺🇦": "uk",
    "🇨🇿": "cs",
    "🇸🇰": "sk",
    "🇷🇴": "ro",
    "🇭🇺": "hu",
    "🇧🇬": "bg",
    "🇭🇷": "hr",
    "🇷🇸": "sr",
    "🇮🇱": "he",
    "🇵🇭": "tl",
    "🇧🇩": "bn",
    "🇵🇰": "ur",
    "🇮🇷": "fa",
    "🇰🇿": "kk",
    "🇺🇿": "uz",
    "🇬🇪": "ka",
    "🇦🇲": "hy",
    "🇲🇳": "mn",
    "🇱🇰": "si",
    "🇲🇲": "my",
    "🇰🇭": "km",
    "🇵🇹": "pt",
    "🇳🇵": "ne",
    "🇦🇿": "az",
    "🇱🇻": "lv",
    "🇱🇹": "lt",
    "🇪🇪": "et",
    "🇮🇸": "is",
    "🇲🇹": "mt",
    "🇦🇫": "ps",
    "🇲🇦": "ar",
    "🇿🇦": "af",
    "🇪🇹": "am",
    "🇰🇪": "sw",
    "🇳🇬": "yo",
}

# リアクション翻訳で使う言語名（flag_to_lang の値をカバー）
_EXTRA_LANG_NAMES: dict[str, str] = {
    "uk": "🇺🇦 ウクライナ語",
    "cs": "🇨🇿 チェコ語",
    "sk": "🇸🇰 スロバキア語",
    "ro": "🇷🇴 ルーマニア語",
    "hu": "🇭🇺 ハンガリー語",
    "bg": "🇧🇬 ブルガリア語",
    "hr": "🇭🇷 クロアチア語",
    "sr": "🇷🇸 セルビア語",
    "he": "🇮🇱 ヘブライ語",
    "tl": "🇵🇭 フィリピン語",
    "bn": "🇧🇩 ベンガル語",
    "ur": "🇵🇰 ウルドゥー語",
    "fa": "🇮🇷 ペルシャ語",
    "kk": "🇰🇿 カザフ語",
    "uz": "🇺🇿 ウズベク語",
    "ka": "🇬🇪 ジョージア語",
    "hy": "🇦🇲 アルメニア語",
    "mn": "🇲🇳 モンゴル語",
    "si": "🇱🇰 シンハラ語",
    "my": "🇲🇲 ミャンマー語",
    "km": "🇰🇭 クメール語",
    "ne": "🇳🇵 ネパール語",
    "az": "🇦🇿 アゼルバイジャン語",
    "lv": "🇱🇻 ラトビア語",
    "lt": "🇱🇹 リトアニア語",
    "et": "🇪🇪 エストニア語",
    "is": "🇮🇸 アイスランド語",
    "mt": "🇲🇹 マルタ語",
    "ps": "🇦🇫 パシュトー語",
    "af": "🇿🇦 アフリカーンス語",
    "am": "🇪🇹 アムハラ語",
    "sw": "🇰🇪 スワヒリ語",
    "yo": "🇳🇬 ヨルバ語",
}
# LANG_NAMES にマージ
LANG_NAMES.update(_EXTRA_LANG_NAMES)


def _do_translate(text: str, target: str) -> str:
    """同期翻訳処理（to_thread で呼び出す）"""
    return GoogleTranslator(source="auto", target=target).translate(text)


class Translator(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
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
        if payload.user_id == self.bot.user.id:
            return

        emoji = str(payload.emoji)
        target_lang = FLAG_TO_LANG.get(emoji)
        if target_lang is None:
            return

        cache_key = (payload.message_id, target_lang)
        if cache_key in self._translated_cache:
            return
        self._translated_cache.add(cache_key)

        if len(self._translated_cache) > 500:
            self._translated_cache.clear()

        channel = self.bot.get_channel(payload.channel_id)
        if channel is None:
            return

        try:
            message = await channel.fetch_message(payload.message_id)
        except (discord.NotFound, discord.Forbidden):
            return

        text = message.content.strip()
        if not text:
            if message.embeds and message.embeds[0].description:
                text = message.embeds[0].description.strip()
            else:
                return

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
            value=f"```{text[:900]}```",
            inline=False,
        )
        embed.add_field(
            name="✅ 翻訳結果",
            value=f"```{result[:900]}```",
            inline=False,
        )
        embed.set_footer(
            text=f"リアクションした人: {payload.member.display_name if payload.member else 'Unknown'}"
                 f"　|　元メッセージ: {message.author.display_name}"
        )

        try:
            await message.reply(embed=embed, mention_author=False)
        except discord.Forbidden:
            await channel.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Translator(bot))
