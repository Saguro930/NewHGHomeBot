from flask import Flask, send_from_directory
import os
from data.firebase_init import init_firebase
from sns.sns import register_sns_routes

app = Flask(__name__)
db = init_firebase()

@app.route("/")
def home():
    return send_from_directory("site", "index.html")

@app.route("/site/<path:filename>")
def site_files(filename):
    return send_from_directory("site", filename)

register_sns_routes(app, db)

# keep_alive() は main.py から直接 app.run() するので不要
# 互換性のために残す場合:
def keep_alive():
    import threading
    port = int(os.environ.get("PORT", 10000))
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=port), daemon=True).start()
