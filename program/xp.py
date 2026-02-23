import discord
from discord.ext import commands
from discord import app_commands
import math

class XP(commands.Cog):
    def __init__(self, bot, db):
        self.bot = bot
        self.db = db

    # ── Firestore ──────────────────────────────────────────
    def get_user_ref(self, guild_id, user_id):
        return (
            self.db.collection("guilds")
            .document(str(guild_id))
            .collection("members")
            .document(str(user_id))
        )

    def get_guild_ref(self, guild_id):
        return self.db.collection("guilds").document(str(guild_id))

    async def get_user_data(self, guild_id, user_id):
        doc = self.get_user_ref(guild_id, user_id).get()
        data = doc.to_dict() if doc.exists else {}
        data.setdefault("xp", 0)
        data.setdefault("level", 0)
        data.setdefault("total_xp", 0)
        return data

    async def set_user_data(self, guild_id, user_id, data):
        self.get_user_ref(guild_id, user_id).set(data, merge=True)

    async def get_guild_data(self, guild_id):
        doc = self.get_guild_ref(guild_id).get()
        data = doc.to_dict() if doc.exists else {}
        data.setdefault("level_up_channel", None)
        return data

    # ── XP計算式（ProBot準拠） ────────────────────────────
    def xp_required(self, level: int) -> int:
        return 5 * (level ** 2) + 50 * level + 100

    def calc_level(self, total_xp: int) -> tuple[int, int, int]:
        """(level, current_xp, xp_needed) を返す"""
        level = 0
        while total_xp >= self.xp_required(level):
            total_xp -= self.xp_required(level)
            level += 1
        return level, total_xp, self.xp_required(level)

    # ── 文字数に応じたXP計算（3~30） ────────────────────
    # 1文字で5XP、100文字以上で30XP に線形補間してクランプ
    def calc_gained_xp(self, content: str) -> int:
        length = len(content.strip())
        xp = 3 + int((length / 50) * 27)
        return max(3, min(30, xp))

    # ── メッセージ受信でXP付与 ────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not message.guild:
            return

        guild_id = message.guild.id
        user_id = message.author.id

        gained_xp = self.calc_gained_xp(message.content)
        data = await self.get_user_data(guild_id, user_id)

        old_level = data["level"]
        data["total_xp"] += gained_xp

        new_level, current_xp, xp_needed = self.calc_level(data["total_xp"])
        data["level"] = new_level
        data["xp"] = current_xp

        await self.set_user_data(guild_id, user_id, data)

        # レベルアップ通知
        if new_level > old_level:
            embed = discord.Embed(
                title="🎉 レベルアップ！",
                description=f"{message.author.mention} が **レベル {new_level}** になりました！",
                color=discord.Color.gold()
            )
            embed.set_thumbnail(url=message.author.display_avatar.url)

            guild_data = await self.get_guild_data(guild_id)
            channel_id = guild_data.get("level_up_channel")

            if channel_id:
                channel = message.guild.get_channel(int(channel_id))
                if channel:
                    await channel.send(embed=embed)
                    return

            # チャンネル未設定 → メッセージを送ったチャンネルに通知
            await message.channel.send(embed=embed)

    # ── /rank コマンド ────────────────────────────────────
    @app_commands.command(name="rank", description="自分または指定したユーザーのランクを確認する")
    @app_commands.describe(user="確認したいユーザー（省略で自分）")
    async def rank(self, interaction: discord.Interaction, user: discord.Member = None):
        target = user or interaction.user
        data = await self.get_user_data(interaction.guild.id, target.id)

        level = data["level"]
        current_xp = data["xp"]
        total_xp = data["total_xp"]
        xp_needed = self.xp_required(level)

        # プログレスバー（20マス）
        filled = int((current_xp / xp_needed) * 20)
        bar = "█" * filled + "░" * (20 - filled)

        rank_position = await self.get_rank_position(interaction.guild.id, total_xp)

        embed = discord.Embed(
            title=f"📊 {target.display_name} のランク",
            color=discord.Color.blurple()
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="🏅 サーバーランク", value=f"#{rank_position}", inline=True)
        embed.add_field(name="⭐ レベル", value=str(level), inline=True)
        embed.add_field(name="✨ 累計XP", value=f"{total_xp:,}", inline=True)
        embed.add_field(
            name=f"XP進捗 ({current_xp} / {xp_needed})",
            value=f"`{bar}` {int(current_xp / xp_needed * 100)}%",
            inline=False
        )
        await interaction.response.send_message(embed=embed)

    # ── /leaderboard コマンド ─────────────────────────────
    @app_commands.command(name="leaderboard", description="サーバーのXPランキングを表示する")
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()

        docs = (
            self.db.collection("guilds")
            .document(str(interaction.guild.id))
            .collection("members")
            .order_by("total_xp", direction="DESCENDING")
            .limit(10)
            .stream()
        )

        embed = discord.Embed(
            title=f"🏆 {interaction.guild.name} のXPランキング",
            color=discord.Color.gold()
        )

        medals = ["🥇", "🥈", "🥉"]
        entries = []

        for i, doc in enumerate(docs):
            d = doc.to_dict()
            member = interaction.guild.get_member(int(doc.id))
            name = member.display_name if member else f"退出済みユーザー ({doc.id})"
            medal = medals[i] if i < 3 else f"`#{i+1}`"
            level = d.get("level", 0)
            total_xp = d.get("total_xp", 0)
            entries.append(f"{medal} **{name}** — Lv.{level} ({total_xp:,} XP)")

        embed.description = "\n".join(entries) if entries else "まだデータがありません。"
        await interaction.followup.send(embed=embed)

    # ── /set_xp_channel コマンド（管理者用） ──────────────
    @app_commands.command(name="set_xp_channel", description="【管理者】レベルアップ通知を送るチャンネルを設定する")
    @app_commands.describe(channel="通知先のチャンネル")
    @app_commands.default_permissions(administrator=True)
    async def set_xp_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        self.get_guild_ref(interaction.guild.id).set(
            {"level_up_channel": str(channel.id)},
            merge=True
        )
        await interaction.response.send_message(
            f"✅ レベルアップ通知チャンネルを {channel.mention} に設定しました。",
            ephemeral=True
        )

    # ── ランク順位取得（ヘルパー） ────────────────────────
    async def get_rank_position(self, guild_id: int, total_xp: int) -> int:
        docs = (
            self.db.collection("guilds")
            .document(str(guild_id))
            .collection("members")
            .where("total_xp", ">", total_xp)
            .stream()
        )
        return sum(1 for _ in docs) + 1


async def setup(bot, db):
    await bot.add_cog(XP(bot, db))
