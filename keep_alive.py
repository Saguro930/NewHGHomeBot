from flask import Flask, send_from_directory
import threading
import os

# Firebase
from data.firebase_init import init_firebase

# SNS API
from sns.sns import register_sns_routes

app = Flask(__name__)

# Firebase 初期化
db = init_firebase()

# --------------------
# 静的ファイル
# --------------------
@app.route("/")
def home():
    return send_from_directory("site", "index.html")

@app.route("/site/<path:filename>")
def site_files(filename):
    return send_from_directory("site", filename)

# --------------------
# SNS API 登録
# --------------------
register_sns_routes(app, db)

# --------------------
# Flask 起動
# --------------------
def run():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    threading.Thread(target=run, daemon=True).start()
