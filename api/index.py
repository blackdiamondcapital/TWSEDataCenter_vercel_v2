# api/index.py
# 作用：把既有的 Flask app 暴露為 WSGI 應用給 Vercel Python Runtime

try:
    # 假設你原本的 Flask 主程式在 server.py，且有 app = Flask(__name__)
    from server import app  # noqa: F401
except Exception as e:  # 後備路徑：避免 import 失敗時完全掛掉，方便你排錯
    from flask import Flask, jsonify
    app = Flask(__name__)  # type: ignore

    @app.get("/api/ping")
    def _fallback_ping():
        return jsonify({"ok": True, "warning": "fallback app is running", "import_error": str(e)}), 200
