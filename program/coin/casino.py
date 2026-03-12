import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
from firebase_admin import firestore

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  カラー定数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COLOR_WIN    = 0x2ECC71   # 緑
COLOR_LOSE   = 0xE74C3C   # 赤
COLOR_DRAW   = 0x95A5A6   # グレー
COLOR_PLAY   = 0x3498DB   # 青（ゲーム中）
COLOR_INFO   = 0xF39C12   # オレンジ

MAX_BET = 1_000_000_000          # 最大ベット額

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ブラックジャック ロジック
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SUITS  = ["♠", "♥", "♦", "♣"]
RANKS  = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]

def new_deck() -> list[tuple[str, str]]:
    deck = [(rank, suit) for suit in SUITS for rank in RANKS]
    random.shuffle(deck)
    return deck

def card_value(rank: str) -> int:
    if rank in ("J", "Q", "K"):
        return 10
    if rank == "A":
        return 11
    return int(rank)

def hand_total(hand: list[tuple[str, str]]) -> int:
    total = sum(card_value(r) for r, _ in hand)
    aces  = sum(1 for r, _ in hand if r == "A")
    while total > 21 and aces:
        total -= 10
        aces  -= 1
    return total

def format_hand(hand: list[tuple[str, str]], hide_second: bool = False) -> str:
    """カードをテキスト表示。hide_second=Trueでディーラーの2枚目を隠す"""
    cards = []
    for i, (rank, suit) in enumerate(hand):
        if i == 1 and hide_second:
            cards.append("`🂠`")
        else:
            cards.append(f"`{rank}{suit}`")
    return "  ".join(cards)

def is_blackjack(hand: list[tuple[str, str]]) -> bool:
    return len(hand) == 2 and hand_total(hand) == 21


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ブラックジャック UI (discord.ui.View)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class BlackjackView(discord.ui.View):
    def __init__(self, cog: "Casino", interaction: discord.Interaction, bet: int):
        super().__init__(timeout=60)
        self.cog        = cog
        self.user       = interaction.user
        self.bet        = bet
        self.deck       = new_deck()
        self.player     = [self.deck.pop(), self.deck.pop()]
        self.dealer     = [self.deck.pop(), self.deck.pop()]
        self.finished   = False

    # ── Embed 生成 ──────────────────────────────────
    def build_embed(
        self,
        *,
        reveal: bool = False,
        title: str   = "🃏 ブラックジャック",
        color: int   = COLOR_PLAY,
        result_text: str | None = None,
    ) -> discord.Embed:
        p_total = hand_total(self.player)
        d_total = hand_total(self.dealer)

        embed = discord.Embed(title=title, color=color)

        # ディーラー欄
        if reveal:
            embed.add_field(
                name=f"🎩 ディーラー　（合計: {d_total}）",
                value=format_hand(self.dealer),
                inline=False,
            )
        else:
            embed.add_field(
                name=f"🎩 ディーラー　（合計: ?）",
                value=format_hand(self.dealer, hide_second=True),
                inline=False,
            )

        # プレイヤー欄
        embed.add_field(
            name=f"😊 あなた　（合計: {p_total}）",
            value=format_hand(self.player),
            inline=False,
        )

        # ベット情報
        embed.add_field(name="💰 ベット", value=f"{self.bet:,} コイン", inline=True)

        if result_text:
            embed.add_field(name="📢 結果", value=result_text, inline=False)

        embed.set_footer(text="Hit: カードを引く  |  Stand: 止める  |  Double: 倍掛け")
        return embed

    # ── ゲーム終了処理 ──────────────────────────────
    async def end_game(self, interaction: discord.Interaction, reason: str = "stand"):
        self.finished = True
        self.hit_btn.disabled    = True
        self.stand_btn.disabled  = True
        self.double_btn.disabled = True

        p_total = hand_total(self.player)
        d_total = hand_total(self.dealer)

        # ディーラーのドロー（17以上になるまで引く）
        if reason != "bust":
            while hand_total(self.dealer) < 17:
                self.dealer.append(self.deck.pop())
            d_total = hand_total(self.dealer)

        # 勝敗判定
        if reason == "bust":
            outcome, color, payout = "💥 バスト！あなたの負けです。", COLOR_LOSE, 0
        elif is_blackjack(self.player) and reason == "natural":
            payout  = int(self.bet * 2.5)   # ブラックジャックは 1.5 倍払い
            outcome, color = f"🎉 ブラックジャック！ **{payout:,}** コイン獲得！", COLOR_WIN
        elif d_total > 21:
            payout  = self.bet * 2
            outcome, color = f"🎉 ディーラーバスト！ **{payout:,}** コイン獲得！", COLOR_WIN
        elif p_total > d_total:
            payout  = self.bet * 2
            outcome, color = f"🎉 あなたの勝ち！ **{payout:,}** コイン獲得！", COLOR_WIN
        elif p_total < d_total:
            payout  = 0
            outcome, color = f"😢 ディーラーの勝ち。 **{self.bet:,}** コイン没収。", COLOR_LOSE
        else:
            payout  = self.bet      # 引き分けはベット返却
            outcome, color = f"🤝 引き分け。 **{self.bet:,}** コイン返却。", COLOR_DRAW

        if payout > 0:
            await self.cog.add_coins(self.user.id, payout)

        embed = self.build_embed(reveal=True, title="🃏 ブラックジャック — 結果", color=color, result_text=outcome)
        await interaction.response.edit_message(embed=embed, view=self)

    # ── Hit ─────────────────────────────────────────
    @discord.ui.button(label="👆 Hit", style=discord.ButtonStyle.primary)
    async def hit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("あなたのゲームではありません。", ephemeral=True)
            return

        self.player.append(self.deck.pop())
        self.double_btn.disabled = True   # 3枚以上になったらダブルは不可

        if hand_total(self.player) > 21:
            await self.end_game(interaction, reason="bust")
        elif total == 21:
            await self.end_game(interaction, reason="stand")
        else:
            embed = self.build_embed()
            await interaction.response.edit_message(embed=embed, view=self)

    # ── Stand ────────────────────────────────────────
    @discord.ui.button(label="✋ Stand", style=discord.ButtonStyle.secondary)
    async def stand_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("あなたのゲームではありません。", ephemeral=True)
            return
        await self.end_game(interaction, reason="stand")

    # ── Double Down ──────────────────────────────────
    @discord.ui.button(label="⚡ Double", style=discord.ButtonStyle.success)
    async def double_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("あなたのゲームではありません。", ephemeral=True)
            return

        # 追加ベット分を引き落とし
        can_double = await self.cog.remove_coins(self.user.id, self.bet)
        if not can_double:
            await interaction.response.send_message("❌ コインが不足しているためダブルできません。", ephemeral=True)
            return

        self.bet *= 2
        self.player.append(self.deck.pop())   # 1枚だけ引く

        if hand_total(self.player) > 21:
            await self.end_game(interaction, reason="bust")
        else:
            await self.end_game(interaction, reason="stand")

    # ── タイムアウト ─────────────────────────────────
    async def on_timeout(self):
        self.hit_btn.disabled    = True
        self.stand_btn.disabled  = True
        self.double_btn.disabled = True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Casino Cog
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class Casino(commands.Cog):
    def __init__(self, bot, db):
        self.bot = bot
        self.db  = db

    # ── Firestore ヘルパー ───────────────────────────
    def get_user_ref(self, user_id):
        return self.db.collection("users").document(str(user_id))

    async def add_coins(self, user_id: int, amount: int) -> int:
        ref = self.get_user_ref(user_id)
        doc = await asyncio.to_thread(ref.get)
        coins = (doc.to_dict().get("coins", 0) if doc.exists else 0) + amount
        await asyncio.to_thread(ref.set, {"coins": coins}, merge=True)  # type: ignore[arg-type]
        return coins

    async def remove_coins(self, user_id: int, amount: int) -> bool:
        ref  = self.get_user_ref(user_id)
        doc  = await asyncio.to_thread(ref.get)
        coins = doc.to_dict().get("coins", 0) if doc.exists else 0
        if coins < amount:
            return False
        await asyncio.to_thread(ref.set, {"coins": coins - amount}, merge=True)  # type: ignore[arg-type]
        return True

    async def get_coins(self, user_id: int) -> int:
        ref = self.get_user_ref(user_id)
        doc = await asyncio.to_thread(ref.get)
        return doc.to_dict().get("coins", 0) if doc.exists else 0

    # ── ベット共通バリデーション ─────────────────────
    async def validate_bet(self, interaction: discord.Interaction, bet: int) -> bool:
        if bet <= 0:
            embed = discord.Embed(title="❌ エラー", description="1以上の値を指定してください。", color=COLOR_LOSE)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return False
        if bet > MAX_BET:
            embed = discord.Embed(title="❌ エラー", description=f"最大ベット額は **{MAX_BET:,}** コインです。", color=COLOR_LOSE)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return False
        can_play = await self.remove_coins(interaction.user.id, bet)
        if not can_play:
            embed = discord.Embed(title="❌ コイン不足", description="所持コインが足りません。", color=COLOR_LOSE)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return False
        return True

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  /balance
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    @app_commands.command(name="balance", description="所持コインを確認する")
    async def balance(self, interaction: discord.Interaction):
        coins = await self.get_coins(interaction.user.id)
        embed = discord.Embed(title="💰 残高確認", color=COLOR_INFO)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.add_field(name=interaction.user.display_name, value=f"**{coins:,}** コイン", inline=False)
        await interaction.response.send_message(embed=embed)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  /cointoss
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    @app_commands.command(name="cointoss", description="コイントスで勝負")
    @app_commands.describe(bet="賭けるコインの量")
    async def cointoss(self, interaction: discord.Interaction, bet: int):
        if not await self.validate_bet(interaction, bet):
            return

        result = random.choice(["表", "裏"])
        win    = result == "表"

        if win:
            payout = bet * 2
            await self.add_coins(interaction.user.id, payout)
            embed = discord.Embed(title="🪙 コイントス — 勝利！", color=COLOR_WIN)
            embed.add_field(name="結果", value="**表** 🎉", inline=True)
            embed.add_field(name="獲得コイン", value=f"+{payout:,}", inline=True)
        else:
            embed = discord.Embed(title="🪙 コイントス — 敗北…", color=COLOR_LOSE)
            embed.add_field(name="結果", value="**裏** 💔", inline=True)
            embed.add_field(name="失ったコイン", value=f"-{bet:,}", inline=True)

        embed.set_footer(text=f"{interaction.user.display_name} のベット: {bet:,} コイン")
        await interaction.response.send_message(embed=embed)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  /slot
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    @app_commands.command(name="slot", description="スロットで遊ぶ（7=35倍、🍒=30倍、他=25倍）")
    @app_commands.describe(bet="賭けるコインの量")
    async def slot(self, interaction: discord.Interaction, bet: int):
        if not await self.validate_bet(interaction, bet):
            return

        icons = ["🍒", "🍋", "🍊", "🍇", "7️⃣"]

        if random.random() < 0.06:
            symbol = random.choice(icons)
            result = [symbol, symbol, symbol]
        else:
            result = [random.choice(icons) for _ in range(3)]

        win = result[0] == result[1] == result[2]

        embed = discord.Embed(title="🎰 スロット", color=COLOR_WIN if win else COLOR_LOSE)
        embed.add_field(name="リール", value=f"**{'  '.join(result)}**", inline=False)

        if win:
            symbol = result[0]
            multiplier = 35 if symbol == "7️⃣" else 30 if symbol == "🍒" else 25
            payout = bet * multiplier
            await self.add_coins(interaction.user.id, payout)
            embed.add_field(name="✨ 大当たり！", value=f"{symbol} 揃い ({multiplier}倍)", inline=True)
            embed.add_field(name="獲得コイン",   value=f"+{payout:,}", inline=True)
        else:
            embed.add_field(name="結果",       value="ハズレ 😢", inline=True)
            embed.add_field(name="失ったコイン", value=f"-{bet:,}", inline=True)

        embed.set_footer(text=f"{interaction.user.display_name} のベット: {bet:,} コイン")
        await interaction.response.send_message(embed=embed)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  /dice
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    @app_commands.command(name="dice", description="1～6 の数字を予想して賭ける")
    @app_commands.describe(bet="賭けるコインの量", guess="予想する数字（1～6）")
    async def dice(self, interaction: discord.Interaction, bet: int, guess: int):
        if not (1 <= guess <= 6):
            embed = discord.Embed(title="❌ エラー", description="1～6 の数字を指定してください。", color=COLOR_LOSE)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        if not await self.validate_bet(interaction, bet):
            return

        result = random.randint(1, 6)
        win    = guess == result
        dice_faces = ["⚀", "⚁", "⚂", "⚃", "⚄", "⚅"]

        if win:
            payout = bet * 6
            await self.add_coins(interaction.user.id, payout)
            embed = discord.Embed(title="🎲 ダイス — 大正解！", color=COLOR_WIN)
            embed.add_field(name="出目",      value=f"{dice_faces[result-1]} **{result}**", inline=True)
            embed.add_field(name="あなたの予想", value=f"{dice_faces[guess-1]} **{guess}**", inline=True)
            embed.add_field(name="獲得コイン", value=f"+{payout:,} (6倍！)", inline=False)
        else:
            embed = discord.Embed(title="🎲 ダイス — 残念…", color=COLOR_LOSE)
            embed.add_field(name="出目",      value=f"{dice_faces[result-1]} **{result}**", inline=True)
            embed.add_field(name="あなたの予想", value=f"{dice_faces[guess-1]} **{guess}**", inline=True)
            embed.add_field(name="失ったコイン", value=f"-{bet:,}", inline=False)

        embed.set_footer(text=f"{interaction.user.display_name} のベット: {bet:,} コイン")
        await interaction.response.send_message(embed=embed)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  /blackjack  ← NEW
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    @app_commands.command(name="blackjack", description="ディーラーと1対1でブラックジャック！")
    @app_commands.describe(bet="賭けるコインの量")
    async def blackjack(self, interaction: discord.Interaction, bet: int):
        if not await self.validate_bet(interaction, bet):
            return

        view  = BlackjackView(self, interaction, bet)
        p_tot = hand_total(view.player)
        d_tot = hand_total(view.dealer)

        # 配った瞬間にブラックジャック判定
        if is_blackjack(view.player):
            # ディーラーも BJ なら引き分け
            if is_blackjack(view.dealer):
                await self.add_coins(interaction.user.id, bet)   # 返却
                embed = view.build_embed(reveal=True, title="🃏 ブラックジャック", color=COLOR_DRAW,
                                         result_text="🤝 両者ブラックジャック！ 引き分けです。")
            else:
                payout = int(bet * 2.5)
                await self.add_coins(interaction.user.id, payout)
                embed = view.build_embed(reveal=True, title="🃏 ブラックジャック！", color=COLOR_WIN,
                                         result_text=f"🎉 ナチュラルブラックジャック！ **{payout:,}** コイン獲得！")
            view.hit_btn.disabled    = True
            view.stand_btn.disabled  = True
            view.double_btn.disabled = True
            await interaction.response.send_message(embed=embed, view=view)
            return

        embed = view.build_embed()
        await interaction.response.send_message(embed=embed, view=view)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Cog 登録
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
async def setup(bot, db):
    await bot.add_cog(Casino(bot, db))
