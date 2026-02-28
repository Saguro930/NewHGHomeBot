import discord
from discord.ext import commands
from discord import app_commands
from datetime import timedelta

# 🔒 管理者チェック関数（Slash用）
def is_admin(interaction: discord.Interaction):
    return interaction.user.guild_permissions.administrator

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # 🔹 Timeout コマンド（管理者限定）
    @app_commands.command(
        name="timeout",
        description="指定したユーザーをタイムアウトします"
    )
    @app_commands.describe(
        user="タイムアウトするユーザー",
        duration="時間（分単位）"
    )
    @app_commands.check(is_admin)
    async def timeout(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        duration: int
    ):
        if duration <= 0:
            await interaction.response.send_message(
                "❌ 時間は1分以上指定してください。",
                ephemeral=True
            )
            return
        try:
            until = discord.utils.utcnow() + timedelta(minutes=duration)
            await user.timeout(until)
            await interaction.response.send_message(
                f"⏱ {user.mention} を **{duration} 分間** タイムアウトしました。"
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ タイムアウトできませんでした: {e}",
                ephemeral=True
            )

    # 🔹 ロール付与コマンド（管理者限定）
    @app_commands.command(
        name="giverole",
        description="指定したユーザーにロールを付与します"
    )
    @app_commands.describe(
        user="ロールを付与するユーザー",
        role="付与するロール"
    )
    @app_commands.check(is_admin)
    async def giverole(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        role: discord.Role
    ):
        try:
            await user.add_roles(role)
            await interaction.response.send_message(
                f"✅ {user.mention} に **{role.name}** を付与しました。"
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ ロールを付与できませんでした: {e}",
                ephemeral=True
            )

    # 🔹 Kick コマンド（管理者限定）
    @app_commands.command(
        name="kick",
        description="指定したユーザーをキックします"
    )
    @app_commands.describe(
        user="キックするユーザー",
        reason="キックの理由（任意）"
    )
    @app_commands.check(is_admin)
    async def kick(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str = "理由なし"
    ):
        if user == interaction.user:
            await interaction.response.send_message(
                "❌ 自分自身をキックすることはできません。",
                ephemeral=True
            )
            return
        try:
            await user.kick(reason=reason)
            await interaction.response.send_message(
                f"👢 {user.mention} をキックしました。\n📋 理由：{reason}"
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ キックできませんでした: {e}",
                ephemeral=True
            )

    # 🔹 Ban コマンド（管理者限定）
    @app_commands.command(
        name="ban",
        description="指定したユーザーをBANします"
    )
    @app_commands.describe(
        user="BANするユーザー",
        reason="BANの理由（任意）",
        delete_days="過去のメッセージ削除日数・0〜7日（省略時は削除なし）"
    )
    @app_commands.check(is_admin)
    async def ban(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str = "理由なし",
        delete_days: int = 0
    ):
        if user == interaction.user:
            await interaction.response.send_message(
                "❌ 自分自身をBANすることはできません。",
                ephemeral=True
            )
            return
        if not (0 <= delete_days <= 7):
            await interaction.response.send_message(
                "❌ メッセージ削除日数は 0〜7 の範囲で指定してください。",
                ephemeral=True
            )
            return
        try:
            await user.ban(reason=reason, delete_message_days=delete_days)
            await interaction.response.send_message(
                f"🔨 {user.mention} をBANしました。\n"
                f"📋 理由：{reason}\n"
                f"🗑 メッセージ削除：{'なし' if delete_days == 0 else f'過去 {delete_days} 日分'}"
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ BANできませんでした: {e}",
                ephemeral=True
            )

    # 🔹 権限エラー時の共通処理
    @timeout.error
    @giverole.error
    @kick.error
    @ban.error
    async def admin_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.CheckFailure):
            await interaction.response.send_message(
                "❌ このコマンドは管理者のみ使用できます。",
                ephemeral=True
            )

# 🔹 Cog登録
async def setup(bot):
    await bot.add_cog(Admin(bot))
