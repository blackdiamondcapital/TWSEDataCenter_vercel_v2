from http.server import BaseHTTPRequestHandler
import os, json, traceback
import psycopg

SQL = """
create table if not exists quotes (
  id bigserial primary key,
  symbol text not null,
  price numeric(18,6) not null,
  ts timestamptz not null default now()
);
create index if not exists idx_quotes_symbol_ts on quotes(symbol, ts desc);
"""

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            dsn = os.environ.get("DATABASE_URL")
            if not dsn:
                raise RuntimeError("Missing env DATABASE_URL")

            with psycopg.connect(dsn, connect_timeout=5, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(SQL)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "message": "tables ensured"}).encode("utf-8"))
        except Exception as e:
            traceback.print_exc()
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
