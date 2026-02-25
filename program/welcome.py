import discord
from discord.ext import commands

class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot, db):
        self.bot = bot
        self.db = db

    # -----------------------------
    # /set_welcome（管理者のみ）
    # -----------------------------
    @commands.hybrid_command(name="set_welcome")
    @commands.has_permissions(administrator=True)
    async def set_welcome(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        channel_id = ctx.channel.id

        doc_ref = self.db.collection("guilds").document(guild_id)
        doc_ref.set({
            "welcome_channel": channel_id
        }, merge=True)

        await ctx.reply(
            f"✅ ようこそ・さようならメッセージを\n"
            f"{ctx.channel.mention} に設定しました"
        )

    # -----------------------------
    # メンバー参加
    # -----------------------------
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild_id = str(member.guild.id)
        doc_ref = self.db.collection("guilds").document(guild_id)
        doc = doc_ref.get()

        # 🔴 未設定なら何もしない
        if not doc.exists:
            return

        data = doc.to_dict()
        channel_id = data.get("welcome_channel")
        if not channel_id:
            return

        channel = member.guild.get_channel(channel_id)
        if channel is None:
            return

        member_count = member.guild.member_count

        await channel.send(
            f"🎉 **ようこそ！** {member.mention} さん、"
            f"**{member.guild.name}** へ！\n"
            f"✨ あなたは **{member_count} 人目** のメンバーです！"
        )

    # -----------------------------
    # メンバー退出
    # -----------------------------
    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild_id = str(member.guild.id)
        doc_ref = self.db.collection("guilds").document(guild_id)
        doc = doc_ref.get()

        # 🔴 未設定なら何もしない
        if not doc.exists:
            return

        data = doc.to_dict()
        channel_id = data.get("welcome_channel")
        if not channel_id:
            return

        channel = member.guild.get_channel(channel_id)
        if channel is None:
            return

        await channel.send(
            f"👋 **さようなら** {member.name} さん…\n"
            f"彼はこのサーバーを脱退しました"
        )


async def setup(bot: commands.Bot, db):
    await bot.add_cog(Welcome(bot, db))
