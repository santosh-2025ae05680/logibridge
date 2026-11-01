# LogiBridge end-to-end guided demo (WSL2 + Docker Desktop)

This runner is adapted to the tested feature branch: `feature/offline-alert-sync`.
Run from WSL Ubuntu **with Docker Desktop running and Ubuntu WSL integration enabled**.
The local repository uses `.venv` (Python 3.11), not `venv`.

## Before running

1. `cd ~/projects/logibridge && source .venv/bin/activate`
2. Confirm `docker info`, `ansible-playbook --version`, and the Docker collection `community.docker` work. `demo_runner.sh prep` checks the main prerequisites.
3. The existing `inference/model.tflite` must contain **M2 INT8** (same bytes as `training/models/mlp_int8.tflite`). The script refuses to overwrite it if it differs.
4. In WSL Ubuntu, `sudo-rs` caused Ansible privilege escalation to time out; the runner uses `ansible_become_exe=/usr/bin/sudo.ws` and will ask for your **Ubuntu sudo password** during Ansible operations. It does not store credentials.
5. Registry container name: `logibridge-registry`, broker container name: `mosquitto`, Docker network: `logibridge-net`.
6. The Docker broker is **not** the WSL system Mosquitto. The simulator and PSI monitor run in temporary containers connected to `logibridge-net` to avoid the two-broker mismatch. No host port 1883 is needed.

## Clear prior demo data before a new recording

```bash
bash demo/demo_cleanup.sh --dry-run
bash demo/demo_cleanup.sh      # type RESET DEMO to confirm
bash demo/demo_runner.sh all
```

The cleanup script **removes** the demo-owned Docker alert volume `logibridge-data` and `runtime_data/demo/` (including the SQLite operations-centre database, alert logs and temporary M3 build). **Export evidence before using it**. It restores M2 via Ansible when the deployed inference container exists, removes demo helpers and inference container, and leaves Docker images, Git, broker, registry, tracked models and other `runtime_data/` intact. The cleanup is a runtime reset, **not** full retraining or a Docker cache purge. If a prerequisite fails, do not force-delete anything; investigate the error.

## Easiest full demo

```bash
bash demo/demo_runner.sh all
```

The script prints and executes each stage and pauses for narration. For execution without narration pauses (sudo prompts remain):

```bash
bash demo/demo_runner.sh all --auto
```

The **runner** does not wipe Docker images, prune caches, delete `/opt/logibridge`, clear existing SQLite files, reset Git files, or remove existing alerts. Use `demo_cleanup.sh` first when old runtime results must be cleared. It creates generated demo data under **`runtime_data/demo/`**, which should stay out of Git. This demo is repeatable but existing stored alerts are not automatically erased.

### Manual segments for recording

```bash
bash demo/demo_runner.sh prep   # verify Docker, registry, broker, baseline image
bash demo/demo_runner.sh 1      # architecture and repo
bash demo/demo_runner.sh 2      # MQTT, simulator and preprocessing check
bash demo/demo_runner.sh 3      # read-only 3-model validation comparison
bash demo/demo_runner.sh 4      # build M3 image 1.1, push, compare OTA layers
bash demo/demo_runner.sh 5      # Ansible deploy M3, repeat for changed=0
bash demo/demo_runner.sh 6      # Docker MQTT -> inference -> PSI -> offline/ACK demo
bash demo/demo_runner.sh 7      # benchmark + full/canary/shadow economics
```

**Run section 4 before 5, and 5 before 6** (or use `all`). Section 6 runs simulated time at 5x speed, so the wall-clock run is shorter than the simulated duration. It stops the *demo* operations-centre container to simulate an outage, but **never stops Mosquitto**; it restarts the centre and checks for HTTP acknowledgement. Results/logs: `runtime_data/demo/simulator.log`, `inference.log`, `drift.log`, `sync.log`, and `ops.sqlite3`.

### Verify state and restore proven M2 deployment

```bash
bash demo/demo_runner.sh status
bash demo/demo_runner.sh rollback
bash demo/demo_runner.sh stop
```

`rollback` redeploys **M2 model + M2 reference + image 1.0** through Ansible. `stop` only removes the four demo helper containers; it **does not** stop the registry, broker or Ansible inference container. The M3 model and reference are built in `runtime_data/demo/`, so the tracked M2 files remain unchanged.

## Architecture and constraints

- Source samples -> Docker Mosquitto (`mosquitto:1883`) -> Ansible inference container -> Normal/Warning/Critical predictions.
- PSI monitor subscribes to inference messages using a reference generated for the matching M3 model; model tags include the model SHA-256 prefix.
- Inference writes alerts into the `logibridge-data` Docker named volume. Store-and-forward sync reads the **same named volume**, retries while the operations centre is down, and records acknowledgments in its SQLite journal.
- Ops centre records received alerts in `runtime_data/demo/ops.sqlite3`.
- All benchmarking is **WSL CPU / synthetic data**; the energy figure uses 28 W TDP assumption, not a power meter.
- The demo creates a second *candidate* image tag `1.1` (M3), not an actual over-the-air cellular transfer to trucks. Docker registry manifest calculations estimate layer reuse.
- Deployment is local Ansible (`localhost`) and requires Docker Desktop, not remote truck infrastructure.
- Do not publish `deployment/mosquitto/mosquitto.conf` with anonymous access on public networks. The demo broker has no externally published MQTT port.

## Results and model identity

This repository ZIP tracks M2 as `inference/model.tflite` and its baseline PSI reference. Guided Stage 4 prepares M3 separately, Stage 5 deploys M3 (SHA-256 prefix `84ff2345`) with its own PSI reference and image `1.1`, and Stage 6 tests live inference plus offline HTTP retry. Check `docker logs logibridge-inference`, `sha256sum /opt/logibridge/model.tflite`, and `runtime_data/demo/ops.sqlite3` to verify the run. The latest measured benchmark numbers live in `optimisation/results/benchmark_results.csv` and are regenerated by Stage 7; historic report values may differ.

**Stage 6** uses accelerated simulated sensor time, but PSI runs on real wall-clock intervals; a drift alert may be observed without a complete live recovery below 0.10. The offline PSI experiment separately demonstrates recovery. The simulated operations-centre outage is not a cellular-modem test.

## Updating evidence after each new full run

Stage 7 overwrites `optimisation/results/benchmark_results.csv` and `optimisation/results/pareto_chart.png`. These are the authoritative per-run timing/energy results. Update any manually maintained benchmark tables in `README.md`, `optimisation/deployment_recommendation.md`, and the final report **after selecting a final run**, not after every practice run.

Stage 4 prints a fresh registry-based M2→M3 OTA layer comparison. Save its terminal output separately if needed; historical `deployment/ota_bandwidth_m3.txt` is not rewritten by the demo. Stage 6 recreates `runtime_data/demo/` evidence (alert IDs, PSI values and SQLite records can differ); capture evidence before running `demo_cleanup.sh`. OTA strategy calculations remain unchanged as long as their assumed input parameters remain unchanged.
