from http.server import BaseHTTPRequestHandler
import os, json, traceback
import psycopg
from psycopg.rows import dict_row

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            dsn = os.environ.get("DATABASE_URL")
            if not dsn:
                raise RuntimeError("Missing env DATABASE_URL")

            # 如果你懷疑舊驅動不支援 channel_binding，可臨時用下一行替換測試
            # dsn = dsn.replace("channel_binding=require", "channel_binding=disable")

            with psycopg.connect(dsn, connect_timeout=5, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute("select now() as ts, current_database() as db, version() as pg")
                    row = cur.fetchone()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, **row}, default=str).encode("utf-8"))
        except Exception as e:
            traceback.print_exc()
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode("utf-8"))
