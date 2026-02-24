from flask import Flask, send_from_directory
import threading
import os

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!"

@app.route("/site/<path:filename>")
def site_files(filename):
    return send_from_directory("site", filename)

def run():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = threading.Thread(target=run, daemon=True)
    t.start()
