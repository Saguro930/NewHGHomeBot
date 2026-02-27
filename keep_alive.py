print("🔥 keep_alive.py imported")
from flask import Flask, send_from_directory
from data.firebase_init import init_firebase

app = Flask(__name__)
db = init_firebase()

@app.route("/")
def home():
    return send_from_directory("web", "index.html")

@app.route("/web/<path:filename>")
def site_files(filename):
    return send_from_directory("web", filename)
