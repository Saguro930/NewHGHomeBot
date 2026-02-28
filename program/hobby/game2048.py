import discord
from discord import app_commands
from discord.ext import commands
import random
import io
from PIL import Image, ImageDraw, ImageFont

# ── タイル色定義（完全版）────────────────────────────────────────
TILE_BG = {
    0:    (205, 193, 180),
    2:    (238, 228, 218),
    4:    (237, 224, 200),
    8:    (242, 177, 121),
    16:   (245, 149,  99),
    32:   (246, 124,  95),
    64:   (246,  94,  59),
    128:  (237, 207, 114),
    256:  (237, 204,  97),
    512:  (237, 200,  80),
    1024: (237, 197,  63),
    2048: (237, 194,  46),
}

TILE_FG = {
    2:   (119, 110, 101),
    4:   (119, 110, 101),
}  # 2・4は暗い文字、それ以外は白

FONT_PATHS = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]

def get_font(size):
    for path in FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


class GameBoard:
    def __init__(self):
        self.board = [[0] * 4 for _ in range(4)]
        self.score = 0
        self.best  = 0
        self.spawn()
        self.spawn()

    def spawn(self):
        empty = [(r, c) for r in range(4) for c in range(4) if self.board[r][c] == 0]
        if empty:
            r, c = random.choice(empty)
            self.board[r][c] = 2 if random.random() < 0.9 else 4

    def merge(self, row):
        tiles = [x for x in row if x != 0]
        i = 0
        while i < len(tiles) - 1:
            if tiles[i] == tiles[i + 1]:
                tiles[i] *= 2
                self.score += tiles[i]
                tiles.pop(i + 1)
            i += 1
        return tiles + [0] * (4 - len(tiles))

    def move(self, direction):
        old = [r[:] for r in self.board]

        if direction == "left":
            self.board = [self.merge(row) for row in self.board]

        elif direction == "right":
            self.board = [self.merge(row[::-1])[::-1] for row in self.board]

        elif direction == "up":
            for c in range(4):
                col = self.merge([self.board[r][c] for r in range(4)])
                for r in range(4):
                    self.board[r][c] = col[r]

        elif direction == "down":
            for c in range(4):
                col = self.merge([self.board[r][c] for r in range(4)][::-1])[::-1]
                for r in range(4):
                    self.board[r][c] = col[r]

        if self.board != old:
            if self.score > self.best:
                self.best = self.score
            self.spawn()
            return True
        return False

    def is_game_over(self):
        for r in range(4):
            for c in range(4):
                if self.board[r][c] == 0:
                    return False
                if c + 1 < 4 and self.board[r][c] == self.board[r][c + 1]:
                    return False
                if r + 1 < 4 and self.board[r][c] == self.board[r + 1][c]:
                    return False
        return True

    def has_won(self):
        return any(self.board[r][c] >= 2048 for r in range(4) for c in range(4))


# ── 画像描画 ──────────────────────────────────────────────────────

CELL  = 100
PAD   = 12
SIZE  = CELL * 4 + PAD * 5   # 452px

def draw_board(board: list, score: int, best: int) -> discord.File:
    img  = Image.new("RGB", (SIZE, SIZE + 70), (187, 173, 160))
    draw = ImageDraw.Draw(img)

    # スコア帯
    draw.rectangle([0, 0, SIZE, 66], fill=(143, 122, 102))
    sf = get_font(22)
    draw.text((16, 10), f"SCORE",  fill=(238, 228, 218), font=sf)
    draw.text((16, 36), f"{score:,}", fill=(255, 255, 255), font=get_font(26))
    draw.text((SIZE - 120, 10), "BEST",       fill=(238, 228, 218), font=sf)
    draw.text((SIZE - 120, 36), f"{best:,}",  fill=(255, 255, 255), font=get_font(26))

    # タイル
    for r in range(4):
        for c in range(4):
            val = board[r][c]
            x = PAD + c * (CELL + PAD)
            y = 70 + PAD + r * (CELL + PAD)
            bg = TILE_BG.get(val, (60, 58, 50))
            draw.rounded_rectangle([x, y, x + CELL, y + CELL], radius=8, fill=bg)

            if val != 0:
                text = str(val)
                fg   = TILE_FG.get(val, (255, 255, 255))
                # 桁数に応じてフォントサイズ調整
                fs   = 44 if len(text) <= 2 else (36 if len(text) == 3 else 28)
                font = get_font(fs)
                bbox = draw.textbbox((0, 0), text, font=font)
                tw   = bbox[2] - bbox[0]
                th   = bbox[3] - bbox[1]
                draw.text(
                    (x + (CELL - tw) // 2, y + (CELL - th) // 2),
                    text, fill=fg, font=font
                )

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return discord.File(buf, filename="2048.png")


# ── View ─────────────────────────────────────────────────────────

class ControlView(discord.ui.View):
    def __init__(self, cog, user_id: int, game: GameBoard):
        super().__init__(timeout=300)
        self.cog     = cog
        self.user_id = user_id
        self.game    = game

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ 自分のゲームを遊んでね！", ephemeral=True
            )
            return False
        return True

    def make_embed(self, state="playing") -> discord.Embed:
        titles = {
            "playing": "🎮 2048",
            "won":     "🏆 2048 達成！",
            "over":    "💀 ゲームオーバー",
        }
        colors = {
            "playing": discord.Color.blurple(),
            "won":     discord.Color.gold(),
            "over":    discord.Color.red(),
        }
        embed = discord.Embed(title=titles[state], color=colors[state])
        embed.set_image(url="attachment://2048.png")
        return embed

    async def _move(self, interaction: discord.Interaction, direction: str):
        changed = self.game.move(direction)
        if not changed:
            await interaction.response.defer()
            return

        file = draw_board(self.game.board, self.game.score, self.game.best)

        if self.game.has_won():
            self._disable_arrows()
            await interaction.response.edit_message(
                embed=self.make_embed("won"), attachments=[file], view=self
            )
        elif self.game.is_game_over():
            self._disable_arrows()
            await interaction.response.edit_message(
                embed=self.make_embed("over"), attachments=[file], view=self
            )
        else:
            await interaction.response.edit_message(
                embed=self.make_embed(), attachments=[file], view=self
            )

    def _disable_arrows(self):
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.custom_id != "restart":
                child.disabled = True

    # ── レイアウト ──
    # Row 0: [　] [↑] [　]
    # Row 1: [←] [↓] [→]
    # Row 2: [　] [🔄] [　]

    @discord.ui.button(label="　", style=discord.ButtonStyle.secondary, disabled=True, row=0)
    async def _b0(self, i, _): pass

    @discord.ui.button(label="↑", style=discord.ButtonStyle.primary, row=0)
    async def up(self, interaction, _):
        await self._move(interaction, "up")

    @discord.ui.button(label="　", style=discord.ButtonStyle.secondary, disabled=True, row=0)
    async def _b1(self, i, _): pass

    @discord.ui.button(label="←", style=discord.ButtonStyle.primary, row=1)
    async def left(self, interaction, _):
        await self._move(interaction, "left")

    @discord.ui.button(label="↓", style=discord.ButtonStyle.primary, row=1)
    async def down(self, interaction, _):
        await self._move(interaction, "down")

    @discord.ui.button(label="→", style=discord.ButtonStyle.primary, row=1)
    async def right(self, interaction, _):
        await self._move(interaction, "right")

    @discord.ui.button(label="　", style=discord.ButtonStyle.secondary, disabled=True, row=2)
    async def _b2(self, i, _): pass

    @discord.ui.button(label="🔄", style=discord.ButtonStyle.danger, custom_id="restart", row=2)
    async def restart(self, interaction: discord.Interaction, _):
        best = self.game.best
        self.game = GameBoard()
        self.game.best = best
        self.cog.games[self.user_id] = self.game
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.label not in ("　", ""):
                child.disabled = False
        file = draw_board(self.game.board, self.game.score, self.game.best)
        await interaction.response.edit_message(
            embed=self.make_embed(), attachments=[file], view=self
        )

    @discord.ui.button(label="　", style=discord.ButtonStyle.secondary, disabled=True, row=2)
    async def _b3(self, i, _): pass

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


# ── Cog ──────────────────────────────────────────────────────────

class Game2048(commands.Cog):
    def __init__(self, bot):
        self.bot   = bot
        self.games = {}

    @app_commands.command(name="2048", description="2048ゲームを開始します")
    async def start_2048(self, interaction: discord.Interaction):
        game = GameBoard()
        self.games[interaction.user.id] = game
        view = ControlView(self, interaction.user.id, game)
        file = draw_board(game.board, game.score, game.best)
        await interaction.response.send_message(
            embed=view.make_embed(), file=file, view=view
        )


async def setup(bot):
    await bot.add_cog(Game2048(bot))
