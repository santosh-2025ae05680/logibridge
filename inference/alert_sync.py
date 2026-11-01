#!/usr/bin/env python3
"""Store-and-forward alert sender; safe to restart after an outage.

The source JSONL alert log is append-only. Successfully acknowledged alert IDs are
persisted in a separate durable SQLite journal. Replays are safe because the
server deduplicates by alert_id. Uses Python standard library only.
"""
import argparse
import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
from pathlib import Path


def pending_alerts(log_path, conn):
    if not Path(log_path).is_file():
        return []
    delivered = {r[0] for r in conn.execute("SELECT alert_id FROM delivered")}
    pending = {}
    with open(log_path) as source:
        for line in source:
            try:
                item = json.loads(line)
                key = item["alert_id"]
                if key not in delivered:
                    pending[key] = item
            except (ValueError, KeyError, TypeError):
                continue  # tolerate a partially appended last line
    return list(pending.values())


def send(alert, url, timeout):
    req = urllib.request.Request(url, json.dumps(alert).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        ack = json.load(response)
    if ack.get("acknowledged") != alert["alert_id"]:
        raise ValueError("unexpected alert acknowledgement")


def cycle(conn, log_path, url, timeout):
    sent = 0
    for alert in pending_alerts(log_path, conn):
        try:
            send(alert, url, timeout)
        except (OSError, ValueError, urllib.error.URLError) as exc:
            print(f"[SYNC OFFLINE] {exc}; retaining pending alerts", flush=True)
            break
        with conn:
            conn.execute("INSERT OR IGNORE INTO delivered(alert_id) VALUES (?)", (alert["alert_id"],))
        sent += 1
        print(f"[SYNC ACK] {alert['alert_id']}", flush=True)
    return sent


def main():
    p = argparse.ArgumentParser(description="Store-and-forward operations-centre alert uploader")
    p.add_argument("--alert-log", default=os.getenv("ALERT_LOG", "/data/alerts.jsonl"))
    p.add_argument("--journal", default=os.getenv("SYNC_JOURNAL", "/data/sync_state.sqlite3"))
    p.add_argument("--endpoint", default=os.getenv("OPS_ENDPOINT", "http://127.0.0.1:9100/alerts"))
    p.add_argument("--interval", type=float, default=5)
    p.add_argument("--timeout", type=float, default=3)
    p.add_argument("--once", action="store_true")
    args = p.parse_args()
    Path(args.journal).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(args.journal) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS delivered(alert_id TEXT PRIMARY KEY)")
        while True:
            cycle(conn, args.alert_log, args.endpoint, args.timeout)
            if args.once:
                break
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
