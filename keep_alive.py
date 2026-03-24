print("🔥 keep_alive.py imported")
from flask import Flask
from data.firebase_init import init_firebase

app = Flask(__name__)
db = init_firebase()

@app.route("/")
def home():
    return "Server is running 🚀"

@app.route("/status")
def status():
    return {"status": "ok"}
