from flask import request, jsonify
from google.cloud.firestore_v1 import SERVER_TIMESTAMP, Increment

def register_sns_routes(app, db):

    # --------------------
    # 投稿 / リプライ
    # --------------------
    @app.route("/api/sns/post", methods=["POST"])
    def create_post():
        data = request.json
        name = data.get("name")
        text = data.get("text")
        reply_to = data.get("reply_to")  # None or post_id

        if not name or not text:
            return jsonify({"error": "invalid"}), 400

        db.collection("posts").add({
            "user_name": name,
            "text": text,
            "reply_to": reply_to,
            "likes": 0,
            "created": SERVER_TIMESTAMP
        })

        return jsonify({"ok": True})

    # --------------------
    # いいね
    # --------------------
    @app.route("/api/sns/like", methods=["POST"])
    def like_post():
        post_id = request.json.get("post_id")
        if not post_id:
            return jsonify({"error": "no id"}), 400

        db.collection("posts").document(post_id).update({
            "likes": Increment(1)
        })

        return jsonify({"ok": True})

    # --------------------
    # タイムライン
    # --------------------
    @app.route("/api/sns/timeline")
    def timeline():
        docs = (
            db.collection("posts")
            .order_by("created", direction="DESCENDING")
            .limit(100)
            .stream()
        )

        posts = []
        for d in docs:
            v = d.to_dict()
            posts.append({
                "id": d.id,
                "name": v["user_name"],
                "text": v["text"],
                "likes": v.get("likes", 0),
                "reply_to": v.get("reply_to")
            })

        return jsonify(posts)
