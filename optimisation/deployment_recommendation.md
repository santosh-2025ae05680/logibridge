# Deployment Recommendation (Task F3)

## Evidence used

The table below is synchronized with the **latest CSV bundled in this repository (1 November 2026)**: `optimisation/results/benchmark_results.csv`. It supersedes older timing tables in previous report drafts. Measurements were made on WSL2 with a 12th Gen Intel Core i7-1260P, 16 logical CPUs, 28 W base-power assumption, 5 interleaved trials × 200 timed inferences (+10 warmups/trial), on 57 synthetic held-out windows.

| Variant | Model KB | Parameters | MACs | Tensor memory (bytes) | Mean latency (ms) | P95 (ms) | Accuracy | Critical recall | Est. energy (mJ) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M1 FP32 | 5.19 | 803 | 752 | 3452 | 0.000971 | 0.001022 | 100% | 100% | 0.0016987 |
| M2 PTQ INT8 | 3.38 | 803 | 752 | 1016 | 0.000923 | 0.000977 | 100% | 100% | 0.0016144 |
| M3 Pruned+INT8 | 2.94 | 400 | 366 | 545 | 0.000922 | 0.000970 | 100% | 100% | 0.0016131 |

### Interpretation

All three met the brief's Critical-recall gate (>95%) **on this synthetic validation set**. Small differences in microsecond-scale latency can change between runs and should not be treated as guaranteed speed advantages. TDP-based energy is derived from the same measured latency; it is an estimate rather than independent electrical measurement.

In this run M3 has the lowest reported mean latency and energy estimate, but the differences versus M2 are tiny and not evidence of repeatable hardware-level advantage. M3 reduces file size from 5.19 KB (M1) to 2.94 KB (approximately 43%), parameters from 803 to 400, MACs from 752 to 366, and working tensor memory from 3452 to 545 bytes. This is a **memory/storage optimization**, not evidence of improved real-world detection performance.

## SLA relevance

The requirement is to issue an alert within 90 seconds after a qualifying fault. The pipeline uses overlapping 30-second windows with a 10-second step; its inference latencies are negligible relative to window collection and message scheduling on this laptop. **The benchmark does not measure end-to-end fault-to-alert SLA** and no Raspberry Pi latency was measured. Avoid claiming a 50× Raspberry Pi extrapolation as a tested result.

## Deployment decision: M3 candidate and verified local demo

- **Baseline (M2)** — `training/models/mlp_int8.tflite` (`52ee32f1` SHA-256 prefix) is the reproducible source baseline and the rollback target. The checked-in `inference/model.tflite` matches it.
- **Optimized candidate (M3)** — `training/models/mlp_pruned_int8.tflite` (`84ff2345` prefix) is the recommended model when file size, tensor memory and MAC budget matter most.
- **Verified local deployment** — Stages 4–6 of `demo/demo_runner.sh` built image tag **1.1**, deployed the M3 file plus an M3-specific PSI reference to `/opt/logibridge/` through the seven-task Ansible playbook, and demonstrated live MQTT inference, Critical alerts, local persistence and HTTP synchronization. The second Ansible run reported `changed=0`.
- **Rollback** — `bash demo/demo_runner.sh rollback` redeploys the M2 artifact, baseline reference and image 1.0 via Ansible. This is **manual redeployment**, not automatic rollback on telemetry failure and not proof that every remote truck retains the old model locally.

## Deployment risk and acceptance gates

1. Confirm Critical-class recall >95% on a **representative replay set** before promotion; the current 100% reflects 17 synthetic Critical validation windows only.
2. Generate a new PSI reference for the *exact* promoted model; do not reuse the M2 baseline JSON with M3 unless explicitly revalidated.
3. Canary-test a subset of trucks before wider promotion, with alert-rate and latency monitoring, rollback readiness, and adequate communications coverage. This is a recommendation, not an automated function of the current Ansible playbook.
4. Recheck cross-platform dependencies before deploying to Raspberry Pi 5 or other ARM hardware. The tested Docker runtime is x86_64-oriented.
5. Production feasibility requires authentication, TLS, durable logging, hardware power measurement and cellular-failure experiments.

## Associated evidence

- `optimisation/results/benchmark_results.csv` and `pareto_chart.png` — latest benchmarking artifact; rerunning Stage 7 updates these.
- `demo/README.md` — tested seven-stage walkthrough and cleanup.
- `deployment/ota_strategy.md` — fleet rollout and economics, distinguishing recommended policy from implemented behavior.
- `reports/final_report.pdf` — older PDF that needs checking for values inconsistent with the latest artifacts.
