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
    from program.youtube import YouTube
    from program.ai import AIChat

    await bot.add_cog(Admin(bot))
    await bot.add_cog(Ticket(bot))
    await bot.add_cog(Help(bot))
    await bot.add_cog(YouTube(bot))
    await bot.add_cog(AIChat(bot))
  
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
