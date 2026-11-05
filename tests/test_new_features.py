import importlib.util
import json
import sqlite3
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

sync = load('alert_sync', ROOT/'inference/alert_sync.py')
server = load('server', ROOT/'operations_centre/server.py')

class SyncTests(unittest.TestCase):
    def test_offline_retry_ack_and_dedupe(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            log = td/'alerts.jsonl'
            server.DB = str(td/'ops.sqlite3')
            server.init_db()
            a = {'alert_id':'a-1','truck_id':'truck','ts':1,'class':2}
            b = {'alert_id':'a-2','truck_id':'truck','ts':2,'class':1}
            log.write_text(json.dumps(a)+'\n')
            conn = sqlite3.connect(td/'journal.sqlite3')
            conn.execute('CREATE TABLE delivered(alert_id TEXT PRIMARY KEY)')
            # Network is unavailable; sender must retain all pending events.
            self.assertEqual(sync.cycle(conn, log, 'http://127.0.0.1:1/alerts', 0.2), 0)
            self.assertEqual(len(sync.pending_alerts(log, conn)), 1)
            http = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
            thread = threading.Thread(target=http.serve_forever, daemon=True)
            thread.start()
            try:
                url = f'http://127.0.0.1:{http.server_port}/alerts'
                self.assertEqual(sync.cycle(conn, log, url, 2), 1)
                with log.open('a') as f:
                    f.write(json.dumps(b)+'\n')
                self.assertEqual(sync.cycle(conn, log, url, 2), 1)
                self.assertEqual(sync.cycle(conn, log, url, 2), 0)
                # Duplicated deliveries must not duplicate backend records.
                server.ingest(a)
                with sqlite3.connect(server.DB) as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM alerts').fetchone()[0], 2)
            finally:
                http.shutdown()
                http.server_close()
                conn.close()

if __name__ == '__main__':
    unittest.main()
