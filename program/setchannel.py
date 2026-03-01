import discord
from discord import app_commands
from discord.ext import commands
from typing import Literal


class SetChannel(commands.Cog):
    def __init__(self, bot: commands.Bot, db):
        self.bot = bot
        self.db = db

    def guild_ref(self, guild_id: int):
        return self.db.collection("guilds").document(str(guild_id))

    # ── /set-channel ──────────────────────────────────────────────

    @app_commands.command(
        name="set-channel",
        description="各種通知・機能チャンネルを設定します"
    )
    @app_commands.describe(
        type="設定するチャンネルの種類",
        channel="設定先のテキストチャンネル"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def set_channel(
        self,
        interaction: discord.Interaction,
        type: Literal["count", "welcome", "x", "server", "levelup", "xpnews"],
        channel: discord.TextChannel,
    ):
        guild_id = interaction.guild.id
        ref = self.guild_ref(guild_id)

        if type == "count":
            ref.set(
                {
                    "count_channel": channel.id,
                    "count": 1,
                    "recent_authors": [],
                },
                merge=True,
            )
            await interaction.response.send_message(
                f"✅ カウントチャンネルを {channel.mention} に設定しました\n"
                f"🔢 カウントは **1** からスタートです！",
                ephemeral=True,
            )

        elif type == "welcome":
            ref.set(
                {"welcome_channel": channel.id},
                merge=True,
            )
            await interaction.response.send_message(
                f"✅ ようこそ・さようならメッセージを {channel.mention} に設定しました",
                ephemeral=True,
            )

        elif type == "x":
            ref.set(
                {"x_channel": channel.id},
                merge=True,
            )
            await interaction.response.send_message(
                f"✅ X通知チャンネルを {channel.mention} に設定しました",
                ephemeral=True,
            )

        elif type == "server":
            ref.set(
                {"server_channel": channel.id},
                merge=True,
            )
            await interaction.response.send_message(
                f"✅ サーバー統計レポートチャンネルを {channel.mention} に設定しました",
                ephemeral=True,
            )

        elif type == "levelup":
            ref.set(
                {"level_up_channel": str(channel.id)},
                merge=True,
            )
            await interaction.response.send_message(
                f"✅ レベルアップ通知チャンネルを {channel.mention} に設定しました",
                ephemeral=True,
            )

        elif type == "xpnews":
            ref.set(
                {"xpnews_channel": str(channel.id)},
                merge=True,
            )
            await interaction.response.send_message(
                f"✅ XPニュースチャンネルを {channel.mention} に設定しました\n"
                f"📰 毎日0時にTop3を発表します。",
                ephemeral=True,
            )

    # ── エラー処理 ────────────────────────────────────────────────

    @set_channel.error
    async def set_channel_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ このコマンドは管理者のみ使用できます。", ephemeral=True
            )


async def setup(bot: commands.Bot, db):
    await bot.add_cog(SetChannel(bot, db))
