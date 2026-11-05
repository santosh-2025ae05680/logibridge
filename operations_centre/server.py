#!/usr/bin/env python3
"""Local operations-centre simulation with durable, idempotent alert intake.

Uses only Python stdlib. Set OPS_DB (default ./operations_centre/alerts.sqlite3)
and OPS_HOST / OPS_PORT; bind to localhost for development.
"""
import json
import os
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DB = os.environ.get("OPS_DB", "operations_centre/alerts.sqlite3")
LOCK = threading.RLock()


def init_db():
    Path(DB).parent.mkdir(parents=True, exist_ok=True)
    with LOCK, sqlite3.connect(DB) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS alerts (alert_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")


def ingest(alert):
    if not isinstance(alert, dict) or not isinstance(alert.get("alert_id"), str) or not alert["alert_id"]:
        raise ValueError("alert_id is required")
    if not alert.get("truck_id") or "ts" not in alert:
        raise ValueError("truck_id and ts are required")
    with LOCK, sqlite3.connect(DB) as conn:
        conn.execute("INSERT OR IGNORE INTO alerts (alert_id, payload) VALUES (?, ?)",
                     (alert["alert_id"], json.dumps(alert)))
    return {"acknowledged": alert["alert_id"]}


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, obj):
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path != "/alerts":
            return self.reply(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if not 0 < n <= 65536:
                return self.reply(413, {"error": "invalid payload size"})
            obj = json.loads(self.rfile.read(n))
            return self.reply(200, ingest(obj))
        except (ValueError, json.JSONDecodeError) as exc:
            return self.reply(400, {"error": str(exc)})

    def do_GET(self):
        if self.path == "/health":
            return self.reply(200, {"status": "ok"})
        if self.path == "/alerts":
            with LOCK, sqlite3.connect(DB) as conn:
                rows = conn.execute("SELECT payload FROM alerts ORDER BY rowid").fetchall()
            return self.reply(200, {"alerts": [json.loads(r[0]) for r in rows]})
        return self.reply(404, {"error": "not found"})


def main():
    init_db()
    host = os.environ.get("OPS_HOST", "127.0.0.1")
    port = int(os.environ.get("OPS_PORT", "9100"))
    print(f"Operations centre listening at http://{host}:{port}", flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
