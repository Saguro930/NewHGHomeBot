import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone
from data.firebase_init import init_firebase

db = init_firebase()

class Bank(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def get_user_data(self, user_id: int):
        ref = db.collection("users").document(str(user_id))
        doc = ref.get()
        if doc.exists:
            return doc.to_dict()
        data = {"coins": 0, "bank": 0}
        ref.set(data)
        return data

    async def set_user_data(self, user_id: int, new_data: dict):
        db.collection("users").document(str(user_id)).set(new_data, merge=True)

    # ── 利子計算・付与 ─────────────────────────────────────────────
    async def apply_interest(self, user_id: int, data: dict) -> tuple[dict, int]:
        """
        最終利子付与日から経過した日数分（日利1%）を bank に加算して返す。
        戻り値: (更新済みdata, 付与したコイン合計)
        """
        bank = data.get("bank", 0)
        if bank <= 0:
            return data, 0

        now = datetime.now(timezone.utc)
        last_str = data.get("last_interest")

        if last_str:
            last_time = datetime.fromisoformat(last_str)
            # タイムゾーン非対応の場合も考慮
            if last_time.tzinfo is None:
                last_time = last_time.replace(tzinfo=timezone.utc)
            elapsed_days = int((now - last_time).total_seconds() // 86400)
        else:
            elapsed_days = 0

        if elapsed_days <= 0:
            return data, 0

        # 複利で計算（日利 1%）
        earned = int(bank * ((1.01 ** elapsed_days) - 1))
        data["bank"] = bank + earned
        data["last_interest"] = now.isoformat()
        return data, earned

    # ── /bank ─────────────────────────────────────────────────────
    @app_commands.command(name="bank", description="銀行操作（預け入れ・引き出し・残高確認）")
    @app_commands.describe(
        type="操作の種類を選択",
        amount="金額を指定（例: 100 または all）"
    )
    @app_commands.choices(
        type=[
            app_commands.Choice(name="deposit（預け入れ）",  value="deposit"),
            app_commands.Choice(name="withdraw（引き出し）", value="withdraw"),
            app_commands.Choice(name="balance（残高確認）",  value="balance"),
        ]
    )
    async def bank(
        self,
        interaction: discord.Interaction,
        type: app_commands.Choice[str],
        amount: str = None
    ):
        user_id = interaction.user.id
        data = await self.get_user_data(user_id)

        # 利子を先に付与
        data, interest_earned = await self.apply_interest(user_id, data)
        if interest_earned > 0:
            await self.set_user_data(user_id, {
                "bank": data["bank"],
                "last_interest": data["last_interest"]
            })

        coins = data.get("coins", 0)
        bank  = data.get("bank",  0)

        # ── 残高確認 ────────────────────────────────────────────────
        if type.value == "balance" or amount is None:
            embed = discord.Embed(
                title=f"💳 {interaction.user.display_name} の残高情報",
                color=discord.Color.green()
            )
            embed.add_field(name="💰 所持金",   value=f"{coins:,} コイン", inline=True)
            embed.add_field(name="🏦 銀行残高", value=f"{bank:,} コイン",  inline=True)
            embed.add_field(name="💵 合計資産", value=f"{coins + bank:,} コイン", inline=False)
            embed.set_footer(text="銀行利率: 日利 1%（複利）")
            if interest_earned > 0:
                embed.description = f"📈 本日の利子 **+{interest_earned:,} コイン** が付与されました！"
            await interaction.response.send_message(embed=embed)
            return

        # ── 金額パース ────────────────────────────────────────────
        if amount.lower() == "all":
            parsed = coins if type.value == "deposit" else bank
        else:
            try:
                parsed = int(amount)
            except ValueError:
                await interaction.response.send_message(
                    "❌ 金額は数値または `all` を指定してください。", ephemeral=True
                )
                return

        if parsed <= 0:
            await interaction.response.send_message("❌ 金額は1以上を指定してください。", ephemeral=True)
            return

        # ── 預け入れ ──────────────────────────────────────────────
        if type.value == "deposit":
            if coins < parsed:
                await interaction.response.send_message("💸 所持金が足りません。", ephemeral=True)
                return
            coins -= parsed
            bank  += parsed

            # 初回預け入れ時は last_interest を今日に設定
            now = datetime.now(timezone.utc)
            update = {"coins": coins, "bank": bank}
            if not data.get("last_interest"):
                update["last_interest"] = now.isoformat()

            await self.set_user_data(user_id, update)

            embed = discord.Embed(
                title="🏦 預け入れ完了",
                description=f"**{parsed:,} コイン** を銀行に預けました！",
                color=discord.Color.green()
            )
            embed.add_field(name="💰 所持金",   value=f"{coins:,} コイン", inline=True)
            embed.add_field(name="🏦 銀行残高", value=f"{bank:,} コイン",  inline=True)
            embed.set_footer(text="銀行利率: 日利 1%（複利）")
            if interest_earned > 0:
                embed.description += f"\n📈 利子 **+{interest_earned:,} コイン** も付与されました！"
            await interaction.response.send_message(embed=embed)

        # ── 引き出し ──────────────────────────────────────────────
        elif type.value == "withdraw":
            if bank < parsed:
                await interaction.response.send_message(
                    f"🏦 銀行残高が足りません。\n残高: **{bank:,} コイン**", ephemeral=True
                )
                return
            bank  -= parsed
            coins += parsed
            await self.set_user_data(user_id, {"coins": coins, "bank": bank})

            embed = discord.Embed(
                title="💵 引き出し完了",
                description=f"**{parsed:,} コイン** を引き出しました！",
                color=discord.Color.blue()
            )
            embed.add_field(name="💰 所持金",   value=f"{coins:,} コイン", inline=True)
            embed.add_field(name="🏦 銀行残高", value=f"{bank:,} コイン",  inline=True)
            embed.set_footer(text="銀行利率: 日利 1%（複利）")
            if interest_earned > 0:
                embed.description += f"\n📈 利子 **+{interest_earned:,} コイン** も付与されました！"
            await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Bank(bot))
