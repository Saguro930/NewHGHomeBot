print("🔥 sns.py imported")

import os
from datetime import timedelta
from functools import wraps

from flask import (
    jsonify, redirect, request, send_from_directory, session, url_for
)
from google.cloud.firestore_v1 import SERVER_TIMESTAMP, Increment
from authlib.integrations.flask_client import OAuth

# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

def _login_required(f):
    """セッションにユーザーがいない場合は 401 を返す"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return jsonify({"error": "unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


def _current_user():
    return session.get("user", {})


# ---------------------------------------------------------------------------
# ルート登録
# ---------------------------------------------------------------------------

def register_sns_routes(app, db):

    # ── app.secret_key が未設定なら環境変数から補完 ──────────────────────
    if not app.secret_key:
        app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production")

    # ── Cookie / Session 設定 ─────────────────────────────────────────────
    app.config.setdefault("PERMANENT_SESSION_LIFETIME", timedelta(days=30))

    # ブラウザを閉じても Cookie が残るよう SameSite と有効期限を明示
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)   # JS から読めない
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")  # CSRF 対策

    # 本番 (HTTPS) では True にすること
    is_production = os.environ.get("FLASK_ENV") == "production"
    app.config.setdefault("SESSION_COOKIE_SECURE", is_production)

    # ── Discord OAuth クライアント ────────────────────────────────────────
    oauth = OAuth(app)
    discord = oauth.register(
        name="discord",
        client_id=os.environ.get("DISCORD_CLIENT_ID"),
        client_secret=os.environ.get("DISCORD_CLIENT_SECRET"),
        authorize_url="https://discord.com/api/oauth2/authorize",
        access_token_url="https://discord.com/api/oauth2/token",
        api_base_url="https://discord.com/api/",
        client_kwargs={"scope": "identify email"},
    )

    # =========================================================================
    # 静的ファイル配信
    # =========================================================================

    BASE_DIR = os.path.dirname(__file__)
    @app.route("/sns")
    def index():  
        return send_from_directory(BASE_DIR, "sns.html")
    @app.route("/sns/sns.css")
    def serve_css():
        return send_from_directory(BASE_DIR, "sns.css")

    # =========================================================================
    # 認証 (Discord OAuth)
    # =========================================================================

    @app.route("/auth/login")
    def auth_login():
        """Discord OAuth 認可画面へリダイレクト"""
        redirect_uri = url_for("auth_callback", _external=True)
        return discord.authorize_redirect(redirect_uri)

    @app.route("/auth/callback")
    def auth_callback():
        """Discord からのコールバック ― セッションにユーザー情報を保存"""
        token = discord.authorize_access_token()

        # Discord ユーザー情報を取得
        resp = discord.get("users/@me", token=token)
        info = resp.json()

        # アバター URL を組み立て
        user_id = info["id"]
        avatar  = info.get("avatar")
        if avatar:
            # アニメーション (a_) アバターは gif、それ以外は png
            ext = "gif" if avatar.startswith("a_") else "png"
            picture = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.{ext}?size=128"
        else:
            # デフォルトアバター (数字 0〜5)
            index   = int(user_id) % 6
            picture = f"https://cdn.discordapp.com/embed/avatars/{index}.png"

        # 表示名: global_name → username の順で使う
        name = info.get("global_name") or info.get("username", "Unknown")

        session.permanent  = True
        session["user"] = {
            "id":      user_id,
            "name":    name,
            "email":   info.get("email", ""),
            "picture": picture,
        }
        return redirect("/")

    @app.route("/auth/logout")
    def auth_logout():
        """セッションを破棄してトップへ"""
        session.clear()
        return redirect("/")

    @app.route("/auth/me")
    def auth_me():
        """現在のログインユーザーを返す (未ログインは null)"""
        user = session.get("user")
        return jsonify(user)

    # =========================================================================
    # タイムライン
    # =========================================================================

    @app.route("/api/sns/timeline")
    @_login_required
    def timeline():
        docs = (
            db.collection("posts")
            .order_by("created", direction="DESCENDING")
            .limit(100)
            .stream()
        )
        me_id = _current_user()["id"]
        posts = []
        for d in docs:
            v = d.to_dict()
            posts.append({
                "id":       d.id,
                "name":     v.get("user_name", ""),
                "picture":  v.get("user_picture", ""),
                "text":     v.get("text", ""),
                "likes":    v.get("likes", 0),
                "liked":    me_id in v.get("liked_by", []),
                "reply_to": v.get("reply_to"),
                "user_id":  v.get("user_id"),
                "is_mine":  v.get("user_id") == me_id,
            })
        return jsonify(posts)

    # =========================================================================
    # 投稿 / リプライ
    # =========================================================================

    @app.route("/api/sns/post", methods=["POST"])
    @_login_required
    def create_post():
        data     = request.json or {}
        text     = (data.get("text") or "").strip()
        reply_to = data.get("reply_to")

        if not text or len(text) > 280:
            return jsonify({"error": "invalid"}), 400

        user = _current_user()
        db.collection("posts").add({
            "user_id":      user["id"],
            "user_name":    user["name"],
            "user_picture": user["picture"],
            "text":         text,
            "reply_to":     reply_to,
            "likes":        0,
            "liked_by":     [],
            "created":      SERVER_TIMESTAMP,
        })
        return jsonify({"ok": True})

    # =========================================================================
    # いいね (トグル)
    # =========================================================================

    @app.route("/api/sns/like", methods=["POST"])
    @_login_required
    def like_post():
        post_id = (request.json or {}).get("post_id")
        if not post_id:
            return jsonify({"error": "no id"}), 400

        me_id    = _current_user()["id"]
        post_ref = db.collection("posts").document(post_id)
        snap     = post_ref.get()

        if not snap.exists:
            return jsonify({"error": "not found"}), 404

        liked_by = snap.to_dict().get("liked_by", [])

        if me_id in liked_by:
            # いいね解除
            post_ref.update({
                "likes":    Increment(-1),
                "liked_by": [u for u in liked_by if u != me_id],
            })
            return jsonify({"ok": True, "liked": False})
        else:
            # いいね
            post_ref.update({
                "likes":    Increment(1),
                "liked_by": liked_by + [me_id],
            })
            return jsonify({"ok": True, "liked": True})

    # =========================================================================
    # 投稿削除 (自分の投稿のみ)
    # =========================================================================

    @app.route("/api/sns/delete/<post_id>", methods=["DELETE"])
    @_login_required
    def delete_post(post_id):
        me_id    = _current_user()["id"]
        post_ref = db.collection("posts").document(post_id)
        snap     = post_ref.get()

        if not snap.exists:
            return jsonify({"error": "not found"}), 404
        if snap.to_dict().get("user_id") != me_id:
            return jsonify({"error": "forbidden"}), 403

        # リプライも削除
        replies = db.collection("posts").where("reply_to", "==", post_id).stream()
        for r in replies:
            r.reference.delete()

        post_ref.delete()
        return jsonify({"ok": True})
