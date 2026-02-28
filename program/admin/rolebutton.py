import discord
from discord.ext import commands
from discord import app_commands

# 🔹 ロールトグルボタン（永続化対応）
class RoleToggleButton(discord.ui.View):
    def __init__(self, role_id: int):
        super().__init__(timeout=None)
        self.role_id = role_id

    @discord.ui.button(label="ロールを受け取る", style=discord.ButtonStyle.primary, emoji="🎭", custom_id="role_toggle")
    async def toggle_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        role = interaction.guild.get_role(self.role_id)

        if role is None:
            await interaction.response.send_message(
                "❌ ロールが見つかりませんでした。",
                ephemeral=True
            )
            return

        if role in member.roles:
            await member.remove_roles(role)
            await interaction.response.send_message(
                f"🗑 **{role.name}** を削除しました。",
                ephemeral=True
            )
        else:
            await member.add_roles(role)
            await interaction.response.send_message(
                f"✅ **{role.name}** を付与しました。",
                ephemeral=True
            )


class RoleButton(commands.Cog):
    def __init__(self, bot, db):
        self.bot = bot
        self.db = db

    # 🔹 Firestore 参照
    def get_role_ref(self, guild_id: int):
        return self.db.collection("guilds").document(str(guild_id)).collection("role")

    # 🔹 起動時に既存のViewを復元
    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            docs = self.get_role_ref(guild.id).stream()
            for doc in docs:
                data = doc.to_dict()
                role_id = data.get("role_id")
                if role_id:
                    self.bot.add_view(RoleToggleButton(role_id=role_id))
        print("✅ RoleButton views restored.")

    # 🔹 /role-button コマンド
    @app_commands.command(
        name="role-button",
        description="ロール付与ボタン付きのメッセージを送信します"
    )
    @app_commands.describe(
        role="付与・削除するロール",
        message="ボタンと一緒に表示するメッセージ"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def role_button(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        message: str
    ):
        embed = discord.Embed(
            description=message,
            color=role.color if role.color.value != 0 else discord.Color.blurple()
        )
        embed.set_footer(text=f"ボタンを押すと {role.name} を取得・削除できます")

        view = RoleToggleButton(role_id=role.id)

        await interaction.response.send_message("✅ メッセージを送信しました。", ephemeral=True)
        sent = await interaction.channel.send(embed=embed, view=view)

        # 🔹 Firestore に保存
        self.get_role_ref(interaction.guild.id).document(str(sent.id)).set({
            "channel_id": interaction.channel.id,
            "message_id": sent.id,
            "message":    message,
            "role_id":    role.id,
            "role_name":  role.name,
        })

    # 🔹 権限エラー処理
    @role_button.error
    async def role_button_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ このコマンドは管理者のみ使用できます。",
                ephemeral=True
            )

# 🔹 Cog登録
async def setup(bot, db):
    await bot.add_cog(RoleButton(bot, db))
