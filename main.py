import os
import discord
from discord.ext import commands
import asyncio

# Firebase
from data.firebase_init import init_firebase
db = init_firebase()

# 諸設定等
TOKEN = os.environ.get("DISCORD_TOKEN")  # Render環境変数

intents = discord.Intents.default()
intents.message_content = True
intents.members = True 
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"🔗 Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"❌ Sync error: {e}")

# Cog登録
async def setup(bot, db):
    from program.admin.admin import Admin
    from program.ticket import Ticket
    from program.help import Help
    from program.ai import AIChat
    from program.currency.coin import Coin
    from program.currency.casino import Casino
    from program.coin.bank import Bank
    from program.coin.bonus import Bonus
    from program.currency.trade import Trade
    from program.currency.steal import Steal
    from program.top import Top
    from program.profile import Profile

    await bot.add_cog(Admin(bot))
    await bot.add_cog(Ticket(bot))
    await bot.add_cog(Help(bot))
    await bot.add_cog(AIChat(bot))
    await bot.add_cog(Coin(bot, db))
    await bot.add_cog(Casino(bot, db))
    await bot.add_cog(Bank(bot))
    await bot.add_cog(Bonus(bot, db))
    await bot.add_cog(Trade(bot, db))
    await bot.add_cog(Steal(bot, db))
    await bot.add_cog(Top(bot, db))
    await bot.add_cog(Profile(bot, db))
  
try:
    from keep_alive import keep_alive
    keep_alive()
except ImportError:
    pass

# Bot起動
async def main():
    await setup(bot, db)
    await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
