# Offline store-and-forward and door handling

These components let alerts survive a loss of connection to the operations centre. The full demo that uses them is described in `demo/README.md`.

## Components

- The inference service subscribes to `sensors/door`, tracks the current door state, publishes changes to `status/door` and writes them to `DOOR_LOG` (`/data/door_events.jsonl`). Door events are not a seventh model input, and an OPEN event is logged rather than treated as a cargo fault.
- `operations_centre/server.py` provides `/health`, `POST /alerts` and `GET /alerts`. A unique constraint on `alert_id` in SQLite makes retries safe.
- `inference/alert_sync.py` reads the local alert JSONL file, retries while the server is unreachable, and records acknowledged IDs in its own SQLite journal.
- The PSI monitor reports when inference messages stop arriving and skips the PSI calculation while the stream is stale.

## Testing the sync on its own (no MQTT needed)

```bash
python operations_centre/server.py
# in a second terminal, create a test alert log:
mkdir -p demo/runtime
printf '%s\n' '{"alert_id":"TRUCK_001-demo-1","truck_id":"TRUCK_001","ts":123,"class":2,"label":"Critical"}' > demo/runtime/alerts.jsonl
python inference/alert_sync.py --alert-log demo/runtime/alerts.jsonl --journal demo/runtime/sync_state.sqlite3 --once
curl http://127.0.0.1:9100/alerts
```

Offline test: stop the server, append a second alert and run the sync command (it prints `[SYNC OFFLINE]`). Restart the server and run it again; the second alert arrives. A third run sends no duplicates.

In the Docker demo, the sync agent mounts the same `logibridge-data` volume as the inference service and sends to the operations-centre container. Only the operations centre is stopped during the outage test; the local Mosquitto broker keeps running. Both scripts use only the Python standard library.

## Scope

- This is a CPU-only local setup, not a cellular modem stack.
- The server listens on loopback by default and has no authentication or TLS, so it should not be exposed publicly or used with real pharmaceutical data.
- The sync agent and operations centre are started as demo helper containers. They are not part of the seven-task Ansible playbook, which deploys only the inference service.
- In the 4 November run (`evidence/latest_run_2026-11-04.txt`), two Critical alerts were queued during the outage and acknowledged after the operations centre restarted.
