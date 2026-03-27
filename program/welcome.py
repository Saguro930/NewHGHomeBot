import discord
from discord.ext import commands
import io
import asyncio
import aiohttp
from PIL import Image, ImageDraw, ImageFilter, ImageFont


# ── フォント設定 ───────────────────────────────────────────────────
# サーバー環境に合わせて適宜パスを変更してください
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    "/usr/local/share/fonts/NotoSansCJKjp-Regular.otf",
]

def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


# ── アバター取得 ───────────────────────────────────────────────────

async def _fetch_avatar(member: discord.Member) -> Image.Image:
    url = member.display_avatar.replace(size=256, format="png").url
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.read()
    return Image.open(io.BytesIO(data)).convert("RGBA")


# ── 円形マスク ─────────────────────────────────────────────────────

def _circle_crop(img: Image.Image, size: int) -> Image.Image:
    img = img.resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    result.paste(img, (0, 0), mask)
    return result


# ── ウェルカムカード生成（同期） ───────────────────────────────────

def _build_card(
    avatar_img: Image.Image,
    username: str,
    guild_name: str,
    member_count: int,
) -> io.BytesIO:
    W, H = 800, 250
    AVATAR_SIZE = 160
    PADDING = 30

    # ── 背景：ダークグラデーション ──
    card = Image.new("RGBA", (W, H), (30, 31, 34, 255))
    draw = ImageDraw.Draw(card)

    # 左側のカラーアクセントバー
    draw.rectangle([(0, 0), (6, H)], fill=(88, 101, 242, 255))

    # ── アバター（円形、左中央） ──
    avatar = _circle_crop(avatar_img, AVATAR_SIZE)

    # アバターの白縁取り
    border_size = AVATAR_SIZE + 8
    border_img = Image.new("RGBA", (border_size, border_size), (0, 0, 0, 0))
    border_draw = ImageDraw.Draw(border_img)
    border_draw.ellipse((0, 0, border_size, border_size), fill=(255, 255, 255, 255))
    border_x = PADDING + 4
    border_y = (H - border_size) // 2
    card.paste(border_img, (border_x, border_y), border_img)

    avatar_x = PADDING + 8
    avatar_y = (H - AVATAR_SIZE) // 2
    card.paste(avatar, (avatar_x, avatar_y), avatar)

    # ── テキスト ──
    text_x = PADDING + AVATAR_SIZE + 40

    font_name  = _load_font(36)
    font_sub   = _load_font(22)
    font_small = _load_font(18)

    # ようこそ！
    draw.text((text_x, 50), "ようこそ！", font=font_sub, fill=(180, 185, 200, 255))

    # ユーザー名（長すぎる場合は切り詰め）
    display_name = username if len(username) <= 20 else username[:19] + "…"
    draw.text((text_x, 80), display_name, font=font_name, fill=(255, 255, 255, 255))

    # サーバー名
    guild_text = f"{guild_name} へ！"
    draw.text((text_x, 128), guild_text, font=font_sub, fill=(150, 155, 170, 255))

    # メンバー数
    draw.text(
        (text_x, 175),
        f"✨ あなたは {member_count} 人目のメンバーです",
        font=font_small,
        fill=(88, 101, 242, 255)
    )

    buf = io.BytesIO()
    card.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


# ── Cog ───────────────────────────────────────────────────────────

class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot, db):
        self.bot = bot
        self.db = db

    def _get_data(self, guild_id: int) -> dict:
        doc = self.db.collection("guilds").document(str(guild_id)).get()
        return doc.to_dict() if doc.exists else {}

    # ── 参加 ──────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        data = self._get_data(member.guild.id)
        channel_id = data.get("welcome_channel")
        if not channel_id:
            return
        channel = member.guild.get_channel(int(channel_id))
        if channel is None:
            return

        member_count = member.guild.member_count

        try:
            avatar_img = await _fetch_avatar(member)
            card_buf = await asyncio.to_thread(
                _build_card,
                avatar_img,
                member.display_name,
                member.guild.name,
                member_count,
            )
            file = discord.File(card_buf, filename="welcome.png")
            embed = discord.Embed(
                description=(
                    f"🎉 **ようこそ！** {member.mention} さん、**{member.guild.name}** へ！\n"
                    f"✨ あなたは **{member_count} 人目** のメンバーです！"
                ),
                color=0x5865F2
            )
            embed.set_image(url="attachment://welcome.png")
            await channel.send(embed=embed, file=file)

        except Exception as e:
            # 画像生成失敗時はテキストのみにフォールバック
            print(f"[Welcome] 画像生成エラー: {e}")
            await channel.send(
                f"🎉 **ようこそ！** {member.mention} さん、**{member.guild.name}** へ！\n"
                f"✨ あなたは **{member_count} 人目** のメンバーです！"
            )

    # ── 退出 ──────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        data = self._get_data(member.guild.id)
        channel_id = data.get("welcome_channel")
        if not channel_id:
            return
        channel = member.guild.get_channel(int(channel_id))
        if channel is None:
            return

        await channel.send(
            f"👋 **さようなら** {member.name} さん…\n"
            f"サーバーを退出しました。"
        )


async def setup(bot: commands.Bot, db):
    await bot.add_cog(Welcome(bot, db))
