# LogiEdge guided demo (WSL2 + Docker Desktop)

The runner was developed on the `feature/offline-alert-sync` branch. Run it from WSL Ubuntu with Docker Desktop running and Ubuntu WSL integration enabled. The repository uses a `.venv` environment with Python 3.11.

## Before running

1. `cd ~/projects/logibridge && source .venv/bin/activate`
2. Check that `docker info`, `ansible-playbook --version` and the `community.docker` collection work. `bash demo/demo_runner.sh prep` checks the main prerequisites.
3. `inference/model.tflite` must be the M2 INT8 model (the same bytes as `training/models/mlp_int8.tflite`). The runner stops rather than overwrite it if it differs.
4. On our WSL Ubuntu, `sudo-rs` made Ansible privilege escalation time out, so the runner uses `ansible_become_exe=/usr/bin/sudo.ws` and asks for the Ubuntu password during the Ansible steps. It does not store the password.
5. Container and network names: registry `logibridge-registry`, broker `mosquitto`, network `logibridge-net`.
6. The Docker broker is separate from any Mosquitto installed in WSL. The simulator and PSI monitor run in temporary containers on `logibridge-net`, so no host port 1883 is needed.

## Clearing old demo data

```bash
bash demo/demo_cleanup.sh --dry-run
bash demo/demo_cleanup.sh      # type RESET DEMO to confirm
bash demo/demo_runner.sh all
```

The cleanup script removes the `logibridge-data` Docker volume and `runtime_data/demo/` (the operations-centre SQLite database, alert logs and the temporary M3 build), so copy any logs you need first. If the inference container is deployed, it restores M2 through Ansible, then removes the demo helpers and the inference container. Docker images, Git files, the broker, the registry and the tracked models are left alone. It does not retrain anything or clear the Docker build cache.

## Full demo

```bash
bash demo/demo_runner.sh all
bash demo/demo_runner.sh all --auto     # no pauses between stages (sudo prompts remain)
```

The runner prints and runs each stage and pauses between them. It does not delete Docker images, caches, `/opt/logibridge`, SQLite files or existing alerts; use `demo_cleanup.sh` for that. Generated data goes to `runtime_data/demo/`, which is ignored by Git.

### Individual stages

```bash
bash demo/demo_runner.sh prep   # check Docker, registry, broker, baseline image
bash demo/demo_runner.sh 1      # architecture and repository
bash demo/demo_runner.sh 2      # MQTT, simulator and preprocessing check
bash demo/demo_runner.sh 3      # validation results for the three models
bash demo/demo_runner.sh 4      # build M3 image 1.1, push, compare OTA layers
bash demo/demo_runner.sh 5      # Ansible deploy of M3, then a repeat run (changed=0)
bash demo/demo_runner.sh 6      # MQTT -> inference -> PSI -> offline alerts -> ACK
bash demo/demo_runner.sh 7      # benchmark and full/canary/shadow cost comparison
```

Run stage 4 before 5, and 5 before 6. Stage 6 runs in real time for 1,260 seconds so that PSI is computed every 60 seconds and the 100-prediction window can fully recover. It stops the demo operations-centre container to simulate an outage (Mosquitto keeps running), then restarts it and checks that the queued alerts are acknowledged. Logs are written to `runtime_data/demo/` (`simulator.log`, `inference.log`, `drift.log`, `sync.log` and `ops.sqlite3`).

Stage 6 settings: `--anomaly-after 120 --anomaly-until 240 --duration 1260 --speed 1 --seed 42` for the simulator, and `--interval 60 --window 100` for the PSI monitor.

### Status, rollback and stop

```bash
bash demo/demo_runner.sh status
bash demo/demo_runner.sh rollback
bash demo/demo_runner.sh stop
```

`rollback` redeploys the M2 model, the M2 reference and image 1.0 through Ansible. `stop` removes the four demo helper containers only; the registry, broker and inference container keep running. The M3 model and reference are built in `runtime_data/demo/`, so the tracked M2 files are never changed.

## How the pieces connect

- Simulator, then Docker Mosquitto (`mosquitto:1883`), then the Ansible-deployed inference container, which outputs Normal, Warning or Critical.
- The PSI monitor subscribes to the inference topic with a reference built for the same M3 model. Inference messages carry the model's SHA-256 prefix so a mismatch is reported.
- The inference service writes alerts to the `logibridge-data` volume. The sync agent mounts the same volume, retries while the operations centre is down and records acknowledgements in its SQLite journal.
- The operations centre stores received alerts in `runtime_data/demo/ops.sqlite3`.
- Image 1.1 is a second image tag in the local registry; the bandwidth figure comes from comparing registry layers, not from a cellular transfer.
- Ansible deploys to `localhost` only.
- The broker configuration allows anonymous access and should not be used on a public network.

## Models and evidence

The repository tracks M2 as `inference/model.tflite`, while `monitoring/reference_dist.json` is the M3 reference. The runner builds a matching M3 reference before deploying M3 (SHA-256 prefix `84ff2345`), and rollback uses a matching M2 reference. To check a run, use `docker logs logibridge-inference`, `sha256sum /opt/logibridge/model.tflite` and `runtime_data/demo/ops.sqlite3`.

Stage 7 rewrites `optimisation/results/benchmark_results.csv` and `pareto_chart.png`. Stage 4 prints the registry layer comparison for M2 to M3. The run used in our report is in `evidence/latest_run_2026-11-04.txt`; in it PSI went from 0.000 to a peak of 4.604 and back to 0.000 with `n=100`, and two queued Critical alerts were acknowledged after the operations centre restarted.
