import discord
from discord import app_commands
from discord.ext import commands
import random

# ── タイル表示設定 ────────────────────────────────────────────────
TILE = {
    0:    " · · · ",
    2:    "   2   ",
    4:    "   4   ",
    8:    "   8   ",
    16:   "  16   ",
    32:   "  32   ",
    64:   "  64   ",
    128:  "  128  ",
    256:  "  256  ",
    512:  "  512  ",
    1024: " 1024  ",
    2048: " 2048  ",
}

TILE_EMOJI = {
    0:    "⬜",
    2:    "🟦",
    4:    "🟩",
    8:    "🟧",
    16:   "🟥",
    32:   "🟪",
    64:   "🔵",
    128:  "🟡",
    256:  "🌕",
    512:  "⭐",
    1024: "🌟",
    2048: "💎",
}

def render_board(board: list[list[int]]) -> str:
    rows = []
    rows.append("```")
    rows.append("┌───────┬───────┬───────┬───────┐")
    for i, row in enumerate(board):
        # 絵文字行
        emoji_line = "  ".join(TILE_EMOJI.get(v, "🔶") for v in row)
        rows.append(f"│  {emoji_line}  │")
        # 数値行
        num_line = "│".join(TILE.get(v, f"{v:^7}") for v in row)
        rows.append(f"│{num_line}│")
        if i < 3:
            rows.append("├───────┼───────┼───────┼───────┤")
        else:
            rows.append("└───────┴───────┴───────┴───────┘")
    rows.append("```")
    return "\n".join(rows)


# ── ゲームロジック ────────────────────────────────────────────────
class GameBoard:
    def __init__(self, best: int = 0):
        self.board = [[0] * 4 for _ in range(4)]
        self.score = 0
        self.best  = best
        self.spawn()
        self.spawn()

    def spawn(self):
        empty = [(r, c) for r in range(4) for c in range(4) if self.board[r][c] == 0]
        if empty:
            r, c = random.choice(empty)
            self.board[r][c] = 2 if random.random() < 0.9 else 4

    def merge(self, row: list[int]) -> list[int]:
        tiles = [x for x in row if x != 0]
        i = 0
        while i < len(tiles) - 1:
            if tiles[i] == tiles[i + 1]:
                tiles[i] *= 2
                self.score += tiles[i]
                tiles.pop(i + 1)
            i += 1
        return tiles + [0] * (4 - len(tiles))

    def move(self, direction: str) -> bool:
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
            self.best = max(self.best, self.score)
            self.spawn()
            return True
        return False

    def is_game_over(self) -> bool:
        for r in range(4):
            for c in range(4):
                if self.board[r][c] == 0:
                    return False
                if c + 1 < 4 and self.board[r][c] == self.board[r][c + 1]:
                    return False
                if r + 1 < 4 and self.board[r][c] == self.board[r + 1][c]:
                    return False
        return True

    def has_won(self) -> bool:
        return any(self.board[r][c] >= 2048 for r in range(4) for c in range(4))

    def highest(self) -> int:
        return max(self.board[r][c] for r in range(4) for c in range(4))


# ── Embed生成 ─────────────────────────────────────────────────────
def make_embed(game: GameBoard, owner: discord.User, state="playing") -> discord.Embed:
    cfg = {
        "playing": ("🎮 2048",              discord.Color.blurple()),
        "won":     ("💎 2048 達成！",        discord.Color.gold()),
        "over":    ("💀 ゲームオーバー",      discord.Color.red()),
    }
    title, color = cfg[state]

    embed = discord.Embed(title=title, description=render_board(game.board), color=color)
    embed.add_field(name="💯 スコア",     value=f"```{game.score:,}```",   inline=True)
    embed.add_field(name="🏅 ベスト",     value=f"```{game.best:,}```",    inline=True)
    embed.add_field(name="🔢 最大タイル", value=f"```{game.highest()}```", inline=True)
    embed.set_author(name=owner.display_name, icon_url=owner.display_avatar.url)
    embed.set_footer(text="↑ ← ↓ → で操作　🔄 リスタート　2分操作なしで終了")
    return embed


# ── View ─────────────────────────────────────────────────────────
class ControlView(discord.ui.View):
    def __init__(self, cog, owner: discord.User, game: GameBoard):
        super().__init__(timeout=120)
        self.cog   = cog
        self.owner = owner
        self.game  = game

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner.id:
            await interaction.response.send_message(
                "❌ 自分のゲームを遊んでね！", ephemeral=True
            )
            return False
        return True

    def _disable_arrows(self):
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.custom_id != "restart":
                child.disabled = True

    async def _move(self, interaction: discord.Interaction, direction: str):
        if not self.game.move(direction):
            await interaction.response.defer()
            return

        if self.game.has_won():
            self._disable_arrows()
            state = "won"
        elif self.game.is_game_over():
            self._disable_arrows()
            state = "over"
        else:
            state = "playing"

        await interaction.response.edit_message(
            embed=make_embed(self.game, self.owner, state), view=self
        )

    # Row 0: [　][↑][　]
    # Row 1: [←][↓][→]
    # Row 2: [　][🔄][　]

    @discord.ui.button(label="　", style=discord.ButtonStyle.secondary, disabled=True, row=0)
    async def _b0(self, i, _): pass

    @discord.ui.button(label="↑", style=discord.ButtonStyle.primary, row=0)
    async def up(self, interaction, _): await self._move(interaction, "up")

    @discord.ui.button(label="　", style=discord.ButtonStyle.secondary, disabled=True, row=0)
    async def _b1(self, i, _): pass

    @discord.ui.button(label="←", style=discord.ButtonStyle.primary, row=1)
    async def left(self, interaction, _): await self._move(interaction, "left")

    @discord.ui.button(label="↓", style=discord.ButtonStyle.primary, row=1)
    async def down(self, interaction, _): await self._move(interaction, "down")

    @discord.ui.button(label="→", style=discord.ButtonStyle.primary, row=1)
    async def right(self, interaction, _): await self._move(interaction, "right")

    @discord.ui.button(label="　", style=discord.ButtonStyle.secondary, disabled=True, row=2)
    async def _b2(self, i, _): pass

    @discord.ui.button(label="🔄", style=discord.ButtonStyle.danger, custom_id="restart", row=2)
    async def restart(self, interaction: discord.Interaction, _):
        self.game = GameBoard(best=self.game.best)
        self.cog.games[self.owner.id] = self.game
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.label != "　":
                child.disabled = False
        await interaction.response.edit_message(
            embed=make_embed(self.game, self.owner), view=self
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
        self.games: dict[int, GameBoard] = {}

    @app_commands.command(name="2048", description="2048ゲームを開始します")
    async def start_2048(self, interaction: discord.Interaction):
        game = GameBoard()
        self.games[interaction.user.id] = game
        view = ControlView(self, interaction.user, game)
        await interaction.response.send_message(
            embed=make_embed(game, interaction.user), view=view
        )


async def setup(bot):
    await bot.add_cog(Game2048(bot))
```

**改善点：**

各セルが絵文字＋数値の2段構造になり、罫線で区切られます：
```
┌───────┬───────┬───────┬───────┐
│  🟦  🟦  ⬜  ⬜  │
│   2   │   2   │ · · · │ · · · │
├───────┼───────┼───────┼───────┤
│  ⬜  🟩  ⬜  ⬜  │
│ · · · │   4   │ · · · │ · · · │
...
└───────┴───────┴───────┴───────┘
