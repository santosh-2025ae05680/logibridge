
## Step 2 assumptions
- float32 = 4 bytes per sample, decimal MB (1e6 bytes)
- 40 door events/day at 50 B each
- 10 alerts/day at 300 B each (edge uplink)
- Vibration at 500 Hz x 3 axes for the bandwidth calc; the simulator (Step 4)
  uses 0.5 Hz RMS values, as specified in task C1
- Detection delay budget: 30 s window + 10 s step = 40 s worst case
- TODO: replace [MEASURED] inference time after benchmarking (Step 9)
- TODO: cite a source for rural 4G RTT

## Step 3 decisions
   - Chosen hardware: Option 1, Raspberry Pi 5 + AI HAT+
   - Dominant vertex: Power
   - Roofline: AI 2.50, ridge 1.33, compute-bound, lower bound 2.81 ms
   - Actual MLP is ~800 params / ~1.5 kFLOPs, far below the 45 MFLOP given in B2

## Step 4 decisions
- Simulator publishes the vibration RMS stream at 0.5 Hz as specified; the raw 500 Hz x 3-axis stream is not simulated (only used in the bandwidth calculation).
- Drift is implemented literally: +0.08 C per reading = 4.8 C/min, ~+72 C after 15 min. Unrealistic vs. the 1 C/min in the scenario; optional --drift-cap flag exists. Handle large feature range by clipping normalised features in preprocessing (Step 5).
- Door events are independent of temperature (the brief doesn't couple them).
- --speed and --anomaly-after added for fast dataset generation and for the E1 drift-injection demo.

## Step 5 decisions (preprocessing, C2/C3)
- Causal 5-sample MA; first window ends at 38 s so no warm-up partial averages are used.
- Window closes on the first sample after its end (+~1 s latency; worst-case detection ~41 s + inference).
- Vibration features come from the 0.5 Hz RMS stream: 15 samples per window, so kurtosis is noisy; MA before peak/kurtosis smooths them (order fixed by the brief).
- Features: temp mean, temp std (ddof=1), temp slope C/min (least squares), vib RMS, vib peak, vib kurtosis (Fisher).
- Normalised features clipped to +/-10 to protect INT8 input resolution (drift gives z-scores in the hundreds).
- training_stats.npy: 10 min Normal, seed 42, shape (2, 6) = [mean; std].
- Door events are logged only; they are not part of the 6-feature vector.
- Fusion (C3): feature-level. Report arguments: data-level fusion is awkward (1 Hz vs 0.5 Hz, different units and noise, bigger model); decision-level fusion cannot see cross-sensor interaction (Warning vs Critical differ by the combination of temperature and vibration) and needs extra models on a 10 W device.
- TODO Step 7: run the 3-sigma shifted-stats experiment (shifted_stats() already implemented).

## Step 6 decisions (dataset + training, D1)
- Dataset generated in virtual time from SensorModel + the live preprocessing code (seeds 101/102/103; normalisation stats used seed 42).
- Windows: Normal 117, Warning 87, Critical 87. Split by time: last 20% per class = validation, 2 windows purged between train and val (windows overlap by 20 s, so a random split would leak).
- Model: 6-32-16-3 MLP, ReLU, softmax; Adam 1e-3, batch 16, 60 epochs; 803 parameters.
- Validation accuracy: 100% (57 windows); Class 2 recall: 100%. Near-100% is expected because the simulated classes are trivially separable once features are clipped; kurtosis carries no class information (Gaussian noise).
- Step 8 TODO: define "confidence" for PSI. Max-softmax stays ~1 for every class; P(Normal) separates clean from drifted data. Document the choice.

## Step 7 decisions (conversion + shifted-stats experiment)
- M1 = FP32 TFLite (training/models/mlp_fp32.tflite); M2 = full INT8 PTQ with int8 I/O, calibrated on the 228 training windows (>= 200 required).
- Real model files are only a few KB; the OTA task (E3) specifies 280 KB, so state clearly which figure is used.
- Experiment: stats +3 sigma gives z' = z - 3; stats -3 sigma gives z' = z + 3. Results in training/results/stats_shift_results.csv (use in the Phase 2 report).
- training_stats.npy must ship with the model (bake into the image or copy in Ansible); never recompute at runtime.

## Step 8 decisions (inference service + Docker, D2)
- Build context = repo root with whitelist .dockerignore; Dockerfile order: pip layer, code, stats, ENV/CMD, model LAST.
- Broker runs as a container (mosquitto on user network logibridge-net, published on 127.0.0.1 only); host mosquitto must stay stopped.
- Per-client retained status topics: status/simulator and status/inference.
- Alerts: on entering/escalating Warning or Critical, repeated every 60 s; QoS 1 + local JSONL log. The uplink agent to the ops centre is NOT implemented (architecture only).
- Service resets windowing on timestamp discontinuities (back > 5 s, or forward gap > 120 s).
- Technical difficulty candidates for the report: tfmot vs Python 3.14 (distutils), tf_keras requirement, tflite-runtime 2.14.0 has no aarch64 / Python 3.11 wheel on PyPI (a Pi 5 target needs another runtime), bind mounts under /root with Docker Desktop.
- OTA demo: v1.0 (INT8) -> v1.1 (FP32 model only): only the model layer is rebuilt and pushed; full image 120.65 MB compressed vs model layer 4.1 KB; 85 trucks: 10,255 MB (Rs 1,025.54) vs 0.35 MB (Rs 0.035); 29,164x less data (99.9966%).

## Step 9 decisions (PSI drift monitor, E1)
- Confidence score = P(Normal), not max-softmax: max-softmax is ~1.0 for every class on this separable data (Normal 0.995, Warning 1.000, Critical 0.999), so PSI on it cannot move. offline-check output is the evidence. TODO: confirm interpretation with the instructor.
- Reference: 300 clean windows (seed 202) through the deployed INT8 model, saved with the model tag; the monitor warns if the running model differs.
- PSI: 4 bins from the brief, eps=1e-4, last 100 inferences, evaluated every 60 s; alert > 0.25, recovered < 0.10.
- Simulator gained --anomaly-until for clean -> anomaly -> clean runs.
- Demo: speed 5 => 60 s wall-clock = 5 simulated minutes, so "within 5 minutes" holds in both frames.
- Drift type for the report: covariate shift (the input distribution changed; the model's P(y|x) did not), detected through the output-score distribution. PSI cannot tell a genuine fault from sensor/calibration drift; in production an alert triggers review, not automatic retraining.
- reference_dist.json is tied to the model file: Ansible (E2) must ship both together.

## Step 10 decisions (Ansible, E2)
- 7 tasks exactly, local connection, gather_facts off. Stop task is conditional on model/reference change so run 2 reports changed=0 (ok=6 changed=0 skipped=1); the wait/verify task uses changed_when: false.
- Image tags are immutable per release (docker_image pulls only if the tag is missing); a new tag makes docker_container recreate the container.
- The service loads /opt/logibridge/model.tflite through a read-only bind mount (MODEL_PATH) so the model and reference_dist.json that Ansible ships together are the ones in use.
- Prerequisites outside the playbook: logibridge-net, mosquitto container, registry with the image pushed.
- Idempotency evidence: deployment/run1_output.txt and run2_output.txt (use in report section 5 and the video).
- Ansible difficulty: docker_container state 'stopped' creates the container when it does not exist, so on a fresh host the stop task failed with "Cannot create container when image is not specified". Fixed with state 'absent' (stop if running, then remove; no-op if absent).
