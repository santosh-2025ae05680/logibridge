#!/usr/bin/env bash
# Reset only LogiBridge demo runtime state. Preserve Git, models, Docker images,
# Docker registry, MQTT broker, and manually generated runtime_data/ outside demo/.
# Run from anywhere: bash demo/demo_cleanup.sh [--dry-run | --yes]
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
MODE="${1:-interactive}"
case "$MODE" in interactive|--dry-run|--yes) ;; *) echo "Usage: bash demo/demo_cleanup.sh [--dry-run|--yes]" >&2; exit 2;; esac
[[ -f demo/demo_runner.sh && -f deployment/logibridge_deploy.yml ]] || { echo 'ERROR: Not a LogiBridge repository' >&2; exit 1; }
command -v docker >/dev/null && docker info >/dev/null 2>&1 || { echo 'ERROR: Docker Engine unavailable' >&2; exit 1; }
if [[ -f .venv/bin/activate ]]; then source .venv/bin/activate; fi
DEMO_DIR="$ROOT/runtime_data/demo"
DEMO_CONTAINERS=(logibridge-demo-simulator logibridge-demo-drift logibridge-demo-ops logibridge-demo-sync)
INFERENCE=logibridge-inference
VOLUME=logibridge-data
printf '\nLogiBridge demo reset plan:\n'
printf '  Restore baseline M2 via Ansible (only if its service infrastructure is ready)\n'
printf '  Remove demo-owned helper containers and %s\n' "$INFERENCE"
printf '  Remove named volume %s (old alerts and sync state)\n' "$VOLUME"
printf '  Clear %s (demo records and temporary builds)\n' "$DEMO_DIR"
printf '  KEEP: Git files, trained models, images/cache, registry, Mosquitto, runtime_data outside demo/\n\n'
if [[ "$MODE" == --dry-run ]]; then
  printf 'DRY RUN: no changes made.\n'
  exit 0
fi
if [[ "$MODE" != --yes ]]; then
  read -r -p 'Type RESET DEMO to proceed: ' answer
  [[ "$answer" == 'RESET DEMO' ]] || { echo 'Cancelled; nothing changed.'; exit 0; }
fi
# Before removing alert data, confirm M2 baseline is actually available.
[[ -f inference/model.tflite && -f training/models/mlp_int8.tflite ]] || { echo 'ERROR: baseline model files missing' >&2; exit 1; }
cmp -s inference/model.tflite training/models/mlp_int8.tflite || { echo 'ERROR: inference/model.tflite does not match M2. Restore M2 baseline before reset.' >&2; exit 1; }
[[ -f monitoring/reference_dist.json ]] || { echo 'ERROR: M2 reference JSON missing' >&2; exit 1; }
# Don't delete any runtime data if rollback cannot run when inference is present.
if docker container inspect "$INFERENCE" >/dev/null 2>&1; then
  if ! docker container inspect logibridge-registry >/dev/null 2>&1 || ! docker container inspect mosquitto >/dev/null 2>&1; then
    echo 'ERROR: Registry or MQTT broker missing; cannot safely run rollback.' >&2
    exit 1
  fi
  command -v ansible-playbook >/dev/null || { echo 'ERROR: ansible-playbook missing' >&2; exit 1; }
  echo 'Restoring M2 via existing demo runner (sudo password may be requested)...'
  bash demo/demo_runner.sh rollback
fi
# Stop and remove only exact named demo containers. This also releases the volume.
for c in "${DEMO_CONTAINERS[@]}" "$INFERENCE"; do
  if docker container inspect "$c" >/dev/null 2>&1; then
    echo "Removing container: $c"
    docker rm -f "$c" >/dev/null
  fi
done
if docker volume inspect "$VOLUME" >/dev/null 2>&1; then
  echo "Removing demo alert volume: $VOLUME"
  docker volume rm "$VOLUME" >/dev/null || {
    echo "ERROR: Volume $VOLUME still in use. Other containers may reference it; no forced prune." >&2
    exit 1
  }
fi
# This directory is solely owned by demo orchestration, never other runtime data.
case "$DEMO_DIR" in "$ROOT/runtime_data/demo") ;; *) echo 'ERROR: invalid demo path' >&2; exit 1;; esac
if [[ -L "$DEMO_DIR" ]]; then echo 'ERROR: demo path is a symlink; refusing to delete' >&2; exit 1; fi
if [[ -e "$DEMO_DIR" ]]; then
  echo "Clearing demo output: $DEMO_DIR"
  rm -rf -- "$DEMO_DIR"
fi
mkdir -p -- "$DEMO_DIR"
echo
echo 'Demo state cleared. Registry, MQTT broker, Docker images, and Git are preserved.'
echo 'Next: bash demo/demo_runner.sh all'
docker ps --format 'table {{.Names}}\t{{.Status}}'
