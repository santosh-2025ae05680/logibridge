#!/usr/bin/env bash
# LogiEdge demo runner. Shows each command, waits for ENTER so you can narrate, then runs it for real.
# Usage (from anywhere):  bash demo/demo_runner.sh {prep|1|2|3|4|5|6|7|all}
#   prep  off camera: reset to a clean "truck" running v1.0 (model M2)
#   1..7  one segment of the video
set -u
cd "$(dirname "$0")/.." || exit 1
[ -f venv/bin/activate ] && . venv/bin/activate

B=$'\e[1m'; C=$'\e[36m'; Y=$'\e[33m'; R=$'\e[0m'
title() { clear; printf '\n%s== %s ==%s\n' "$B$C" "$*" "$R"; }
say()   { printf '%s# %s%s\n' "$Y" "$*" "$R"; }
run()   { printf '\n%s$ %s%s\n' "$B" "$*" "$R"; read -r -p "[ENTER to run] " _; bash -c "$*"; }
pause() { read -r -p "[ENTER to continue] " _; }

prep() {
  echo "Resetting to a clean v1.0 state (off camera). The mosquitto container stays running."
  docker rm -f logibridge-inference logibridge-inference-alt registry 2>/dev/null
  docker builder prune -af
  docker images --format '{{.Repository}}:{{.Tag}}' | grep logibridge | xargs -r docker rmi -f
  rm -rf /opt/logibridge
  docker run -d --name registry -p 127.0.0.1:5000:5000 registry:2
  cp training/models/mlp_int8.tflite inference/model.tflite
  python monitoring/drift_monitor.py build-reference
  docker build -f inference/Dockerfile -t logibridge-inference:1.0 .
  docker tag logibridge-inference:1.0 localhost:5000/logibridge-inference:1.0
  docker push localhost:5000/logibridge-inference:1.0
  ansible-playbook -i localhost, deployment/logibridge_deploy.yml -e image_tag=1.0
  echo "Ready. Check: docker logs logibridge-inference | head -3   (model tag of M2, input=int8)"
}

part1() {
  title "1. Introduction: who, where, what"
  say "State your name and group, and that this is your own machine."
  run 'hostname; date; whoami'
  run 'git log --oneline | head -5'
  run 'find . -maxdepth 2 -type d -not -path "./.git*" -not -path "./venv*" | sort'
  say "Open scenario_architecture/system_architecture.png on screen and walk through it."
  pause
}

part2() {
  title "2. Sensor pipeline: broker, simulator, MQTT topics, preprocessing"
  run "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"
  say "Normal mode, with the MQTT topics visible."
  run 'timeout 14 mosquitto_sub -h localhost -t "logibridge/trucks/+/sensors/#" -v & python data_pipeline/simulator.py --anomaly none --duration 12 --quiet; wait'
  say "Temperature drift: +0.08 C per reading."
  run 'python data_pipeline/simulator.py --anomaly temp_drift --duration 12'
  say "Vibration fault: the RMS steps to about 1.2 g."
  run 'python data_pipeline/simulator.py --anomaly vibration --duration 12'
  say "Combined fault."
  run 'python data_pipeline/simulator.py --anomaly combined --duration 12'
  say "Preprocessing: windows, six features, normalisation statistics."
  run 'python data_pipeline/preprocessing.py check'
  say "Live preprocessing from MQTT; an anomaly starts after 60 simulated seconds (5x speed)."
  run 'python data_pipeline/simulator.py --anomaly combined --anomaly-after 60 --speed 5 --duration 150 --quiet & timeout 40 python data_pipeline/preprocessing.py live; wait'
}

part3() {
  title "3. Model: results, pruning, normalisation experiment"
  say "Read-only evidence: nothing is retrained or rewritten on camera."
  run 'python demo/show_model_results.py'
  run 'grep -E "Layer|Compact|Validation accuracy|Parameters|MACs" training/results/m3_pruning_output.txt'
  run 'python training/stats_shift_experiment.py 2>&1 | grep -v -E "cuda|cuDNN|cuFFT|cuBLAS|TF-TRT|oneDNN|XNNPACK"'
  say "Show training/models/training_curves.png on screen."
  pause
}

part4() {
  title "4. Docker, MODEL_PATH switch and the OTA layer-cache demo"
  run 'cat inference/Dockerfile'
  say "Dependencies first; ENV and CMD before the model; the model is the last layer."
  run 'docker ps --filter name=logibridge-inference --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"'
  run 'docker logs logibridge-inference | head -3'
  say "Switch the model without a rebuild: a second container (separate truck ID) with MODEL_PATH on the FP32 model."
  run 'docker create --name logibridge-inference-alt --network logibridge-net -e MQTT_HOST=mosquitto -e TRUCK_ID=TRUCK_ALT -e MODEL_PATH=/app/mlp_fp32.tflite localhost:5000/logibridge-inference:1.0 && docker cp training/models/mlp_fp32.tflite logibridge-inference-alt:/app/mlp_fp32.tflite && docker start logibridge-inference-alt && sleep 4 && docker logs logibridge-inference-alt | head -2; docker rm -f logibridge-inference-alt'
  say "Release M3: only the model file changes. Build a new reference for it."
  run 'cp training/models/mlp_pruned_int8.tflite inference/model.tflite && python monitoring/drift_monitor.py build-reference 2>&1 | grep -E "Reference|model|bin counts|Saved"'
  run 'docker build --progress=plain -f inference/Dockerfile -t logibridge-inference:1.1 . 2>&1 | grep -E "\[[0-9]+/[0-9]+\]|CACHED|DONE"'
  say "Only the final COPY of the model was rebuilt. Now push: only that layer is new."
  run 'docker tag logibridge-inference:1.1 localhost:5000/logibridge-inference:1.1 && docker push localhost:5000/logibridge-inference:1.1'
  say "Bandwidth for 85 trucks: say the numbers aloud."
  run 'python inference/ota_bandwidth.py --old 1.0 --new 1.1'
  say "Simulate a truck that does not have 1.1 yet, so the Ansible pull is a real change."
  run 'docker rmi localhost:5000/logibridge-inference:1.1 logibridge-inference:1.1'
}

part5() {
  title "5. Ansible: the update run, then the idempotent re-run"
  run 'ansible-playbook -i localhost, deployment/logibridge_deploy.yml -e image_tag=1.1'
  say "Run 1 changed the model, the reference, the container and pulled the image. Now run it again, touching nothing."
  run 'ansible-playbook -i localhost, deployment/logibridge_deploy.yml -e image_tag=1.1'
  run 'docker ps --filter name=logibridge-inference --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"'
  run 'docker logs logibridge-inference | head -3'
}

part6() {
  title "6. Drift monitoring: baseline, injection, alert, recovery"
  say "10x time acceleration: 60 s of real time is 10 simulated minutes. The monitor uses its default 60 s interval."
  say "Expect: baseline ok, then ALERT above 0.25, then back below 0.10 after about 4 to 5 minutes."
  run 'cat monitoring/reference_dist.json'
  run 'python data_pipeline/simulator.py --anomaly combined --anomaly-after 600 --anomaly-until 1200 --duration 2700 --speed 10 --quiet > /tmp/sim_demo.log 2>&1 & timeout 330 python monitoring/drift_monitor.py monitor; wait'
}

part7() {
  title "7. Optimisation: benchmark, Pareto chart, recommendation"
  run "cut -d, -f1-6 optimisation/results/benchmark_results.csv | sed 's/,/  |  /g'"
  say "Open optimisation/results/pareto_chart.png on screen: latency ties; size separates the variants."
  pause
  run "sed -n '/## 4. Recommendation/,\$p' optimisation/deployment_recommendation.md"
  say "Close with the limitations, then show the GitHub repository page in the browser."
  pause
}

case "${1:-}" in
  prep) prep ;;
  1) part1 ;; 2) part2 ;; 3) part3 ;; 4) part4 ;; 5) part5 ;; 6) part6 ;; 7) part7 ;;
  all) part1; part2; part3; part4; part5; part6; part7 ;;
  *) echo "usage: bash demo/demo_runner.sh {prep|1|2|3|4|5|6|7|all}"; exit 1 ;;
esac
