import discord
from discord.ext import commands
from discord import app_commands
import aiohttp

RANKING_TYPES = [
    {"value": "total",        "name": "💵 合計資産ランキング"},
    {"value": "coin",         "name": "💰 所持金ランキング"},
    {"value": "coin_reverse", "name": "💸 逆所持金ランキング（ワースト）"},
    {"value": "bank",         "name": "🏦 銀行残高ランキング"},
    {"value": "dollar_rank",  "name": "💲 所持ドルランキング"},
    {"value": "work_level",   "name": "💼 職業レベルランキング"},
]

COIN_TO_YEN = 10  # 1コイン = 10円

async def fetch_usd_to_jpy() -> float:
    """Alpha Vantage から USD→JPY レートを取得。失敗時は150円で代替"""
    url = (
        "https://www.alphavantage.co/query"
        "?function=CURRENCY_EXCHANGE_RATE"
        "&from_currency=USD&to_currency=JPY"
        "&apikey=demo"
    )
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                data = await resp.json()
                rate_str = (
                    data
                    .get("Realtime Currency Exchange Rate", {})
                    .get("5. Exchange Rate", None)
                )
                if rate_str:
                    return float(rate_str)
    except Exception:
        pass
    return 150.0  # フォールバック


async def build_embed(bot, db, index: int) -> discord.Embed:
    ranking_type = RANKING_TYPES[index]["value"]
    ranking_name = RANKING_TYPES[index]["name"]

    # 合計資産のときだけレート取得
    usd_to_jpy = None
    if ranking_type == "total":
        usd_to_jpy = await fetch_usd_to_jpy()

    users_ref = db.collection("users")
    docs = users_ref.stream()
    ranking = []

    for doc in docs:
        data = doc.to_dict()

        if ranking_type == "coin":
            value = data.get("coins", 0)

        elif ranking_type == "coin_reverse":
            value = data.get("coins", 0)

        elif ranking_type == "bank":
            value = data.get("bank", 0)

        elif ranking_type == "work_level":
            value = data.get("work_level", 0)

        elif ranking_type == "dollar_rank":
            value = data.get("dollar", 0.0)

        elif ranking_type == "total":
            coins     = data.get("coins", 0)
            bank      = data.get("bank",  0)
            dollar    = data.get("dollar", 0.0)
            # コイン→円 + ドル→円 を合算して「円」で比較
            value = (coins + bank) * COIN_TO_YEN + dollar * usd_to_jpy

        ranking.append((doc.id, value))

    # 逆ランキングだけ昇順
    reverse = (ranking_type == "coin_reverse")
    ranking.sort(key=lambda x: x[1], reverse=not reverse)
    top_10 = ranking[:10]

    embed = discord.Embed(
        title=f"🏆 {ranking_name}",
        color=discord.Color.gold()
    )

    footer = f"{index + 1} / {len(RANKING_TYPES)}"
    if ranking_type == "total" and usd_to_jpy:
        footer += f"  |  1USD = {usd_to_jpy:.2f}円  /  1コイン = {COIN_TO_YEN}円"
    embed.set_footer(text=footer)

    if not top_10:
        embed.description = "データがありません。"
    else:
        for i, (user_id, value) in enumerate(top_10, start=1):
            try:
                user = await bot.fetch_user(int(user_id))
                name = user.display_name
            except Exception:
                name = "不明なユーザー"

            if ranking_type == "dollar_rank":
                display_value = f"${value:,.2f}"
            elif ranking_type == "work_level":
                display_value = f"Lv.{value:,}"
            elif ranking_type == "total":
                display_value = f"¥{value:,.0f}"
            else:
                display_value = f"{value:,} コイン"

            if reverse:
                # ワーストは💀で統一
                medal = "💀"
            else:
                medal = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else f"#{i}"

            embed.add_field(name=f"{medal} {name}", value=display_value, inline=False)

    return embed


class RankingView(discord.ui.View):
    def __init__(self, bot, db, index: int = 0):
        super().__init__(timeout=20)
        self.bot = bot
        self.db = db
        self.index = index
        self._update_buttons()

    def _update_buttons(self):
        self.left_button.disabled  = (self.index == 0)
        self.right_button.disabled = (self.index == len(RANKING_TYPES) - 1)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except Exception:
            pass

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def left_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.index -= 1
        self._update_buttons()
        embed = await build_embed(self.bot, self.db, self.index)
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def right_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.index += 1
        self._update_buttons()
        embed = await build_embed(self.bot, self.db, self.index)
        await interaction.edit_original_response(embed=embed, view=self)


class Top(commands.Cog):
    def __init__(self, bot, db):
        self.bot = bot
        self.db = db

    @app_commands.command(name="top", description="ランキングを表示します")
    async def top(self, interaction: discord.Interaction):
        await interaction.response.defer()
        view  = RankingView(self.bot, self.db, index=0)
        embed = await build_embed(self.bot, self.db, 0)
        await interaction.followup.send(embed=embed, view=view)
        view.message = await interaction.original_response()


async def setup(bot, db):
    await bot.add_cog(Top(bot, db))
