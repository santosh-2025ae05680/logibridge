# Branch feature additions — offline store-and-forward

This patch is based on the user-provided `main` ZIP snapshot at commit
`b36d49b448b969d5df7008cf2c420d98568a8427`.

## New functions

- Inference subscribes to `sensors/door`, keeps current door state, publishes
  `status/door`, and stores transitions in `DOOR_LOG` (`/data/door_events.jsonl`).
  Door events are intentionally *not* a seventh ML input. OPEN is logged, not
  automatically treated as a critical cargo fault.
- `operations_centre/server.py` supplies `/health`, `POST /alerts`, `GET /alerts`.
  It uses SQLite uniqueness on `alert_id` for idempotent retries.
- `inference/alert_sync.py` reads local alert JSONL, retries when disconnected,
  and records acknowledged IDs in a separate SQLite journal.
- PSI monitor reports stale streams and suppresses stale PSI calculations.

## Local demonstration (three terminals, no MQTT required to test syncing)

```bash
python operations_centre/server.py
# in a separate terminal, create a test alert log:
mkdir -p demo/runtime
printf '%s\n' '{"alert_id":"TRUCK_001-demo-1","truck_id":"TRUCK_001","ts":123,"class":2,"label":"Critical"}' > demo/runtime/alerts.jsonl
python inference/alert_sync.py --alert-log demo/runtime/alerts.jsonl --journal demo/runtime/sync_state.sqlite3 --once
curl http://127.0.0.1:9100/alerts
```

**Offline test:** stop the server, append a second alert, run the sync command
(prints `[SYNC OFFLINE]`), restart server and rerun; the second alert arrives.
Repeat a third time to see no duplicates. For a real inference integration,
mount the inference container's `/data` volume into the sync agent and set
`--alert-log` to the shared `alerts.jsonl` file. The simulated operations centre
must be on a separate network endpoint during the outage test; don't stop the
local Mosquitto broker.

For example, if using a volume called `logibridge-data`, run the sync agent in
an auxiliary Python container with that volume mounted to `/data`, pointing
`OPS_ENDPOINT` at the host/backend address. The scripts need no pip libraries.

## Scope and limitations

This is a CPU-only local demonstration, not a production cellular modem stack.
The backend binds to loopback by default and has **no authentication/TLS**.
Do not expose it publicly or use it for actual pharmaceutical data.
The sync process is an independent service; it is not yet added to the seven-task
Ansible playbook, preserving its exact assignment task count. End-to-end runtime integration **has since been verified** in the local guided Stage 6 demonstration using Docker MQTT, TFLite inference, PSI, offline HTTP retry and two acknowledgments in an operations-centre SQLite database. This still is not a real cellular outage or a remotely managed fleet.

## Current implementation (post-patch)

The original instructions above document the initial patch and a manual 3-terminal exercise. The supported repeatable demo is now `demo/demo_runner.sh`, with `demo/demo_cleanup.sh` for a clean runtime state. The seven-task Ansible playbook deploys inference only; the operations centre and sync agents are started as **demo helper containers**, not automatically as part of the seven tasks. See `demo/README.md` for the current commands, M2 baseline, M3 deployment and manual rollback.
