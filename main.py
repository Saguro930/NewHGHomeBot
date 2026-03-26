print("🔥 main.py start")

import os
import asyncio
import threading
import discord
from discord.ext import commands

from data.firebase_init import init_firebase
db = init_firebase()

TOKEN = os.environ.get("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ------------------------
# イベント
# ------------------------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"🔗 Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"❌ Sync error: {e}")

# ------------------------
# Cog読み込み
# ------------------------
async def setup():
    from program.admin.admin import Admin
    from program.admin.rolebutton import RoleButton
    from program.ticket import Ticket
    from program.other.help import Help
    from program.ai.ai import AIChat
    from program.coin.coin import Coin
    from program.coin.casino import Casino
    from program.coin.bank import Bank
    from program.coin.bonus import Bonus
    from program.coin.trade import Trade
    from program.coin.steal import Steal
    from program.coin.top import Top
    from program.profile import Profile
    from program.server.xp import XP
    from program.game.count import Count
    from program.welcome import Welcome
    from program.server.server import Server
    from program.x import XNotifier
    from program.other.ping import Ping
    from program.setchannel import SetChannel
    from program.coin.battle import Battle
    from program.other.translator import Translator
    from program.other.anka import Anka

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
    await bot.add_cog(XP(bot, db))
    await bot.add_cog(Count(bot, db))
    await bot.add_cog(Welcome(bot, db))
    await bot.add_cog(RoleButton(bot, db))
    await bot.add_cog(Server(bot, db))
    await bot.add_cog(XNotifier(bot, db))
    await bot.add_cog(Ping(bot))
    await bot.add_cog(SetChannel(bot, db))
    await bot.add_cog(Battle(bot, db))
    await bot.add_cog(Translator(bot))
    awair bot.add_cog(Anka(bot,db))

# ------------------------
# Bot起動
# ------------------------
async def main():
    await setup()
    await bot.start(TOKEN)

def start_bot():
    asyncio.run(main())

# ------------------------
# 実行
# ------------------------
if __name__ == "__main__":
    # Botを別スレッドで起動
    bot_thread = threading.Thread(target=start_bot, daemon=True)
    bot_thread.start()

    # Flaskサーバー起動（Render用）
    from keep_alive import app
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
