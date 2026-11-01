#!/usr/bin/env bash
# LogiBridge demonstrator: safe, repeatable, guided end-to-end pipeline.
# bash demo/demo_runner.sh [prep|1|2|3|4|5|6|7|all|status|stop] [--auto]
# By default pause between sections; --auto removes narration pauses.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONUNBUFFERED=1
AUTO=0
MODE="${1:-help}"
[[ "${2:-}" == "--auto" ]] && AUTO=1
[[ -f .venv/bin/activate ]] && source .venv/bin/activate
WORK="$ROOT/runtime_data/demo"
mkdir -p "$WORK"
ANSIBLE=(ansible-playbook -i 'localhost,' -c local deployment/logibridge_deploy.yml -e ansible_become_exe=/usr/bin/sudo.ws --ask-become-pass)

note() { printf '\n\033[1;36m%s\033[0m\n' "$*"; }
log() { printf '  %s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null || fail "Missing command: $1"; }
ask() { if (( ! AUTO )); then read -r -p '[ENTER for next step] ' _; fi; }
run() { printf '\n$'; printf ' %q' "$@"; printf '\n'; "$@"; }
check_files() {
  for file in inference/Dockerfile inference/model.tflite data_pipeline/training_stats.npy \
       training/models/mlp_pruned_int8.tflite training/models/mlp_int8.tflite \
       monitoring/reference_dist.json; do
    [[ -f "$file" ]] || fail "Missing $file";
  done
}
check_docker() { docker info >/dev/null 2>&1 || fail 'Docker Desktop/WSL integration is not ready'; }
exists() { docker container inspect "$1" >/dev/null 2>&1; }
running() { [[ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null || true)" == true ]]; }
ensure_running() { running "$1" || fail "Container $1 not running (run prep first)"; }
ensure_service() { ensure_running mosquitto; ensure_running logibridge-registry; }
wait_demo() {
  local result
  result="$(docker wait "$1")" || fail "Cannot wait for $1"
  [[ "$result" == 0 ]] || { docker logs --tail 40 "$1" >&2; fail "$1 exited with status $result"; }
}
remove_demo() {
  for name in logibridge-demo-simulator logibridge-demo-drift logibridge-demo-ops logibridge-demo-sync; do
    if exists "$name"; then docker rm -f "$name" >/dev/null; fi
  done
}
# The demo's simulator and monitor run inside temporary containers on the same
# Docker network as Ansible's inference and Mosquitto containers. This avoids
# accidentally sending traffic to the separate WSL system Mosquitto broker.
run_script_container() {
  local name="$1"; shift
  docker run -d --name "$name" --network logibridge-net \
    -v "$ROOT:/workspace:ro" -w /workspace --entrypoint python \
    logibridge-inference:1.0 -u "$@" >/dev/null
}

prep() {
  note 'PREP — non-destructive checks and services'
  need docker; need python; need ansible-playbook; check_files; check_docker
  python -c 'import numpy, scipy, paho.mqtt.client; print("Python preprocessing dependencies OK")'
  if ! cmp -s inference/model.tflite training/models/mlp_int8.tflite; then
    fail 'Current inference/model.tflite is not the M2 INT8 baseline. Do not overwrite it automatically; restore/select M2 before prep.'
  fi
  docker network inspect logibridge-net >/dev/null 2>&1 || run docker network create logibridge-net
  if ! exists logibridge-registry; then
    run docker run -d --name logibridge-registry --restart unless-stopped \
      -p 127.0.0.1:5000:5000 registry:2
  elif ! running logibridge-registry; then run docker start logibridge-registry; fi
  if ! exists mosquitto; then
    [[ -f deployment/mosquitto/mosquitto.conf ]] || fail 'Missing Docker Mosquitto config'
    run docker run -d --name mosquitto --network logibridge-net \
      -v "$ROOT/deployment/mosquitto/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro" \
      eclipse-mosquitto:2
  elif ! running mosquitto; then run docker start mosquitto; fi
  ensure_service
  run docker build -f inference/Dockerfile -t logibridge-inference:1.0 .
  run docker tag logibridge-inference:1.0 localhost:5000/logibridge-inference:1.0
  run docker push localhost:5000/logibridge-inference:1.0
  log 'Nothing in /opt/logibridge, Git, images, or existing runtime data was deleted.'
}
part1() {
  note '1 — Project and architecture'
  run git branch --show-current
  run python --version
  log 'Architecture: simulator -> Mosquitto -> 5-point MA/30s windows -> TFLite -> alerts'
  log 'Separate: PSI subscriber, store-and-forward sync, HTTP operations centre.'
  log 'Open scenario_architecture/system_architecture.png for narration.'
  ask
}
part2() {
  note '2 — Simulator, preprocessing, and MQTT topic routing'
  ensure_running mosquitto
  run python data_pipeline/preprocessing.py check
  log 'This broker is isolated from the WSL system broker; demo sensor traffic stays on logibridge-net.'
  # Short sensor-only demonstration. The full 320-second scenario is in section 6.
  if exists logibridge-demo-simulator; then docker rm -f logibridge-demo-simulator >/dev/null; fi
  run_script_container logibridge-demo-simulator data_pipeline/simulator.py \
    --host mosquitto --truck-id TRUCK_DEMO --anomaly combined \
    --anomaly-after 6 --anomaly-until 15 --duration 20 --speed 4 --seed 42
  wait_demo logibridge-demo-simulator
  run docker logs --tail 12 logibridge-demo-simulator
  docker rm logibridge-demo-simulator >/dev/null
  ask
}
part3() {
  note '3 — Model validation and comparison (read-only)'
  run python demo/show_model_results.py
  log 'Model M2 is the previously verified deployment; M3 is the size-optimized candidate.'
  ask
}
part4() {
  note '4 — Docker image layer caching and model-only OTA build'
  ensure_running logibridge-registry
  mkdir -p "$WORK/m3_reference_model"
  cp training/models/mlp_pruned_int8.tflite "$WORK/m3_reference_model/model.tflite"
  run python monitoring/drift_monitor.py build-reference \
    --model "$WORK/m3_reference_model/model.tflite" --out "$WORK/m3_reference.json"
  # Build v1.1 from a *separate* context, keeping inference/model.tflite and
  # monitoring/reference_dist.json in the Git working tree unchanged.
  local ctx="$WORK/m3_build"
  mkdir -p "$ctx/inference" "$ctx/data_pipeline"
  cp inference/Dockerfile inference/requirements.txt inference/inference_service.py \
    inference/tflite_runner.py "$ctx/inference/"
  cp data_pipeline/preprocessing.py data_pipeline/training_stats.npy "$ctx/data_pipeline/"
  cp training/models/mlp_pruned_int8.tflite "$ctx/inference/model.tflite"
  run docker build --progress=plain -f "$ctx/inference/Dockerfile" -t logibridge-inference:1.1 "$ctx"
  run docker tag logibridge-inference:1.1 localhost:5000/logibridge-inference:1.1
  run docker push localhost:5000/logibridge-inference:1.1
  run python inference/ota_bandwidth.py --old 1.0 --new 1.1
  log 'Compare hashes: image 1.0 contains M2; image 1.1 contains M3.'
  run docker run --rm --entrypoint sha256sum logibridge-inference:1.1 /app/model.tflite
  ask
}
ansible_deploy() {
  # The first 3 tasks use become:true and sudo.ws on Ubuntu sudo-rs.
  "${ANSIBLE[@]}" -e "image_tag=$1" -e "model_source=$2" -e "reference_source=$3"
}
part5() {
  note '5 — Ansible M3 deployment + second-run idempotency'
  ensure_service
  [[ -f "$WORK/m3_reference.json" ]] || fail 'Run section 4 to build M3 reference first'
  log 'Ansible may ask for your Ubuntu sudo password on each invocation.'
  ansible_deploy 1.1 "$ROOT/training/models/mlp_pruned_int8.tflite" "$WORK/m3_reference.json"
  run docker logs --tail 8 logibridge-inference
  log 'Same playbook again; target recap: changed=0.'
  ansible_deploy 1.1 "$ROOT/training/models/mlp_pruned_int8.tflite" "$WORK/m3_reference.json"
  ask
}
start_demo_ops() {
  docker run -d --name logibridge-demo-ops --network logibridge-net \
    -v "$ROOT/operations_centre/server.py:/app/server.py:ro" \
    -v "$WORK:/demo-data" -e OPS_HOST=0.0.0.0 \
    -e OPS_DB=/demo-data/ops.sqlite3 --entrypoint python \
    logibridge-inference:1.0 -u /app/server.py >/dev/null
}
start_demo_sync() {
  docker run -d --name logibridge-demo-sync --network logibridge-net \
    -v logibridge-data:/data \
    -v "$ROOT/inference/alert_sync.py:/app/alert_sync.py:ro" \
    -e OPS_ENDPOINT=http://logibridge-demo-ops:9100/alerts \
    --entrypoint python logibridge-inference:1.0 -u /app/alert_sync.py --interval 2 --timeout 2 >/dev/null
}
part6() {
  note '6 — Live MQTT inference, PSI, offline persistence, reconnect and delivery'
  ensure_running logibridge-inference; ensure_running mosquitto
  [[ -f "$WORK/m3_reference.json" ]] || fail 'Run 4 and 5 first'
  remove_demo
  start_demo_ops
  start_demo_sync
  run_script_container logibridge-demo-drift monitoring/drift_monitor.py monitor \
    --host mosquitto --reference /workspace/runtime_data/demo/m3_reference.json --truck-id TRUCK_001 \
    --score p_normal --window 100 --min-samples 5 --interval 5 --stale-after 90
  log 'Operations centre is now stopped to simulate loss of uplink; local MQTT stays working.'
  run docker stop logibridge-demo-ops
  run_script_container logibridge-demo-simulator data_pipeline/simulator.py \
    --host mosquitto --truck-id TRUCK_001 --anomaly combined --anomaly-after 70 \
    --anomaly-until 195 --duration 320 --speed 5 --seed 42 --quiet
  log 'Simulator running accelerated; waiting for full 320 seconds of simulated readings.'
  wait_demo logibridge-demo-simulator
  run docker logs --tail 6 logibridge-demo-simulator
  log 'Offline sync evidence:'
  run docker logs --tail 12 logibridge-demo-sync
  log 'Restore operations centre and allow retries.'
  run docker start logibridge-demo-ops
  sleep 6
  run docker logs --tail 20 logibridge-demo-sync
  run docker logs --tail 18 logibridge-demo-drift
  run docker logs --tail 18 logibridge-inference
  docker logs logibridge-demo-sync > "$WORK/sync.log" 2>&1
  docker logs logibridge-demo-drift > "$WORK/drift.log" 2>&1
  docker logs logibridge-inference > "$WORK/inference.log" 2>&1
  docker logs logibridge-demo-simulator > "$WORK/simulator.log" 2>&1
  grep -q '\[SYNC OFFLINE\]' "$WORK/sync.log" || fail 'Missing OFFLINE evidence in sync.log'
  grep -q '\[SYNC ACK\]' "$WORK/sync.log" || fail 'Missing ACK evidence in sync.log'
  grep -q '\[LOGIBRIDGE DRIFT ALERT\]' "$WORK/drift.log" || log 'No live drift alert observed; inspect drift.log'
  log 'Check actual recipient records stored in runtime_data/demo/ops.sqlite3.'
  python - "$WORK/ops.sqlite3" <<'PY'
import sqlite3,sys
with sqlite3.connect(sys.argv[1]) as conn:
    n=conn.execute('select count(*) from alerts').fetchone()[0]
    print('Operations-centre received alerts:', n)
    if n < 1: raise SystemExit('No delivered alert found')
PY
  remove_demo
  ask
}
part7() {
  note '7 — Benchmark, OTA strategy economics, summary'
  run python optimisation/benchmark.py --tdp-w 28 --trials 5 --power-seconds 3
  run python deployment/ota_strategy_cost.py
  log 'See optimisation/results/pareto_chart.png and optimisation/deployment_recommendation.md.'
  log 'Scope: WSL CPU, synthetic sensors, TDP-based estimated energy, not physical trucks.'
  log 'The demo leaves the Ansible M3 deployment running. Roll back explicitly if desired:'
  log '  bash demo/demo_runner.sh rollback'
  ask
}
rollback() {
  note 'Rollback to verified M2 (image 1.0 + matched PSI reference)'
  ensure_service
  ansible_deploy 1.0 "$ROOT/inference/model.tflite" "$ROOT/monitoring/reference_dist.json"
  run docker logs --tail 8 logibridge-inference
}
status() { run docker ps; run docker image ls logibridge-inference; }
case "$MODE" in
  prep) prep;;
  1) part1;; 2) part2;; 3) part3;; 4) part4;; 5) part5;; 6) part6;; 7) part7;;
  all) prep; part1; part2; part3; part4; part5; part6; part7;;
  rollback) rollback;;
  stop) remove_demo; log 'Stopped demo-only processes; registry, broker, and Ansible deployment preserved.';;
  status) status;;
  *) cat <<'EOF'
Usage: bash demo/demo_runner.sh {prep|1|2|3|4|5|6|7|all|rollback|status|stop} [--auto]
  all       guided end-to-end run, pauses at narration boundaries
  all --auto  no narration pauses (sudo may still ask for password)
  prep      safe infrastructure check/build/push (no destructive reset)
  1..7      one demonstration segment; 4 before 5; 5 before 6
  rollback  redeploy M2 image 1.0 + M2 reference using Ansible
  status    view Docker containers and images
  stop      stop only demo-owned helper containers
EOF
  exit 2;;
esac
