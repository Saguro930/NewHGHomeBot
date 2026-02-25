from flask import Flask, send_from_directory
import os
from data.firebase_init import init_firebase
from site.sns.sns import register_sns_routes

print("🔥 keep_alive.py imported")

app = Flask(__name__)
db = init_firebase()

@app.route("/")
def home():
    return send_from_directory("site", "index.html")

@app.route("/site/<path:filename>")
def site_files(filename):
    return send_from_directory("site", filename)

register_sns_routes(app, db)
