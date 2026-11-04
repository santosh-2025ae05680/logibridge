# Branch feature additions — offline store-and-forward

We implemented and verified these additions in the current Group 15 branch. The earlier starting revision was `b36d49b448b969d5df7008cf2c420d98568a8427`; the supported end-to-end demo is documented in `demo/README.md`.

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
Repeat a third time to see no duplicates. In the verified Docker demo, the sync agent already mounts the same `logibridge-data` named volume used by the inference service. The simulated operations centre
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

The three-terminal commands above are an optional unit-level check, not the final live setup. The supported repeatable demo is now `demo/demo_runner.sh`, with `demo/demo_cleanup.sh` for a clean runtime state. The seven-task Ansible playbook deploys inference only; the operations centre and sync agents are started as **demo helper containers**, not automatically as part of the seven tasks. See `demo/README.md` for the current commands, M2 baseline, M3 deployment and manual rollback.


## Verified final-run notes (4 November 2026)

We verified the complete pipeline on synthetic data in WSL, using the deployed M3 model. The final Stage 6 ran for 1,260 real seconds at 1× speed, with a combined anomaly from second 120 to 240. The PSI monitor evaluated every 60 seconds over the latest 100 predictions: an initial 0.000 increased to 4.604 and later returned to 0.000 at `n=100`. Two Critical alerts were delivered after the operations-centre service was restored. Ansible's second deployment reported `changed=0`. These are local tests, not measurements on a refrigerated truck or an 85-vehicle fleet. Exact evidence is in `evidence/latest_run_2026-11-04.txt`.

## Latest successful run (4 November 2026)

We completed the full run at 1× for 1,260 seconds, using 60-second PSI checks over 100 predictions. The PSI peaked at 4.604 and recovered to 0.000 with `n=100`. Two offline Critical alerts were acknowledged after reconnecting the operations centre. The complete captured output is in `evidence/latest_run_2026-11-04.txt`. Our latest CPU benchmark places both M1 and M3 on the Pareto frontier; the new numbers are in `optimisation/results/benchmark_results.csv`.
