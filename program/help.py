import discord
from discord.ext import commands
from discord import app_commands


# ── ページ定義 ────────────────────────────────────────────────────
PAGES = [
    {
        "title": "⚙️ 管理コマンド",
        "color": discord.Color.red(),
        "fields": [
            ("/timeout user: duration:",            "ユーザーを指定分数タイムアウト"),
            ("/kick user: [reason:]",               "ユーザーをキック"),
            ("/ban user: [reason:] [delete_days:]", "ユーザーをBAN"),
            ("/role type: user: role:",             "ロールの付与（give）・削除（remove）"),
            ("/role-button role: message:",         "ロール付与ボタン付きメッセージを投稿"),
            ("/set-server channel:",                "デイリーレポートの送信先を設定"),
            ("/set-x channel: type:",               "X通知チャンネル・通知タイプを設定"),
            ("/set-xaccount username:",             "X監視アカウントを追加・削除"),
            ("/x-list",                             "X通知設定・監視アカウント一覧"),
            ("/set_xp_channel channel:",            "レベルアップ通知チャンネルを設定"),
            ("/set-xpnews channel:",                "XPニュース送信チャンネルを設定"),
        ]
    },
    {
        "title": "🪙 コインコマンド",
        "color": discord.Color.gold(),
        "fields": [
            ("/profile",        "所持コイン・銀行残高を確認"),
            ("/work",           "働いてコインを獲得"),
            ("/steal user:",    "他ユーザーからコインを盗む"),
            ("/top",            "資産ランキングを表示"),
            ("/bonus type:",    "daily / weekly / monthly ボーナスを受け取る"),
            ("/bank type:",     "銀行にコインを預ける•引き出す"),
        ]
    },
    {
        "title": "✨ その他コマンド",
        "color": discord.Color.blurple(),
        "fields": [
            ("/rank [user:]",  "自分または指定ユーザーのXPランクを確認"),
            ("/leaderboard",   "サーバーのXPランキングを表示"),
            ("@HGHomeBot+",    "AIに質問する"),
        ]
    },
]


def make_embed(page_index: int) -> discord.Embed:
    page  = PAGES[page_index]
    embed = discord.Embed(title=page["title"], color=page["color"])
    for name, value in page["fields"]:
        embed.add_field(name=f"`{name}`", value=value, inline=False)
    embed.set_footer(text=f"ページ {page_index + 1} / {len(PAGES)}　|　HGHomeBot+")
    return embed


# ── View ─────────────────────────────────────────────────────────
class HelpView(discord.ui.View):
    def __init__(self, page: int = 0):
        super().__init__(timeout=120)
        self.page = page
        self._update_buttons()

    def _update_buttons(self):
        self.prev_button.disabled = self.page == 0
        self.next_button.disabled = self.page == len(PAGES) - 1

        labels = ["⚙️ 管理", "🪙 コイン", "✨ その他"]
        for i, child in enumerate(self.page_buttons):
            child.style = (
                discord.ButtonStyle.primary
                if i == self.page
                else discord.ButtonStyle.secondary
            )

    @property
    def page_buttons(self):
        return [c for c in self.children if isinstance(c, discord.ui.Button) and c.custom_id and c.custom_id.startswith("page_")]

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, custom_id="prev", row=1)
    async def prev_button(self, interaction: discord.Interaction, _):
        self.page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=make_embed(self.page), view=self)

    @discord.ui.button(label="⚙️ 管理", style=discord.ButtonStyle.primary, custom_id="page_0", row=0)
    async def page0(self, interaction: discord.Interaction, _):
        self.page = 0
        self._update_buttons()
        await interaction.response.edit_message(embed=make_embed(self.page), view=self)

    @discord.ui.button(label="🪙 コイン", style=discord.ButtonStyle.secondary, custom_id="page_1", row=0)
    async def page1(self, interaction: discord.Interaction, _):
        self.page = 1
        self._update_buttons()
        await interaction.response.edit_message(embed=make_embed(self.page), view=self)

    @discord.ui.button(label="✨ その他", style=discord.ButtonStyle.secondary, custom_id="page_2", row=0)
    async def page2(self, interaction: discord.Interaction, _):
        self.page = 2
        self._update_buttons()
        await interaction.response.edit_message(embed=make_embed(self.page), view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, custom_id="next", row=1)
    async def next_button(self, interaction: discord.Interaction, _):
        self.page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=make_embed(self.page), view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


# ── Cog ──────────────────────────────────────────────────────────
class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="コマンド一覧を表示します")
    async def help(self, interaction: discord.Interaction):
        view = HelpView(page=0)
        await interaction.response.send_message(embed=make_embed(0), view=view, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Help(bot))
