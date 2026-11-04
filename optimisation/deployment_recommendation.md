# Deployment Recommendation (Task F3)

## Evidence used

The table below is synchronized with the **latest CSV bundled in this repository (4 November 2026)**: `optimisation/results/benchmark_results.csv`. It supersedes older timing tables in previous report drafts. Measurements were made on WSL2 with a 12th Gen Intel Core i7-1260P, 16 logical CPUs, 28 W base-power assumption, 5 interleaved trials × 200 timed inferences (+10 warmups/trial), on 57 synthetic held-out windows.

| Variant | Model KB | Parameters | MACs | Tensor memory (bytes) | Mean latency (ms) | P95 (ms) | Accuracy | Critical recall | Est. energy (mJ) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M1 FP32 | 5.19 | 803 | 752 | 3452 | 0.00093 | 0.00109 | 100% | 100% | 0.001626 |
| M2 PTQ INT8 | 3.38 | 803 | 752 | 1016 | 0.00105 | 0.00112 | 100% | 100% | 0.001835 |
| M3 Pruned+INT8 | 2.94 | 400 | 366 | 545 | 0.00107 | 0.00108 | 100% | 100% | 0.001876 |

### Interpretation

All three met the brief's Critical-recall gate (>95%) **on this synthetic validation set**. Small differences in microsecond-scale latency can change between runs and should not be treated as guaranteed speed advantages. TDP-based energy is derived from the same measured latency; it is an estimate rather than independent electrical measurement.

In this run M1 had the lowest mean latency and energy estimate, while M3 had the smallest model and lowest P95 latency. Both M1 and M3 appear on the Pareto frontier. The timing differences are too small to claim a repeatable hardware advantage. M3 reduces file size from 5.19 KB (M1) to 2.94 KB (approximately 43%), parameters from 803 to 400, MACs from 752 to 366, and working tensor memory from 3452 to 545 bytes. This is a **memory/storage optimization**, not evidence of improved real-world detection performance.

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
- `reports/final_report.pdf` — updated report containing the verified last-run measurements.


## Verified final-run notes (4 November 2026)

We verified the complete pipeline on synthetic data in WSL, using the deployed M3 model. The final Stage 6 ran for 1,260 real seconds at 1× speed, with a combined anomaly from second 120 to 240. The PSI monitor evaluated every 60 seconds over the latest 100 predictions: an initial 0.000 increased to 4.604 and later returned to 0.000 at `n=100`. Two Critical alerts were delivered after the operations-centre service was restored. Ansible's second deployment reported `changed=0`. These are local tests, not measurements on a refrigerated truck or an 85-vehicle fleet. Exact evidence is in `evidence/latest_run_2026-11-04.txt`.


## Measurements from our final run (4 November 2026)

| Model | Mean latency (ms) | P95 latency (ms) | Size (KB) | Accuracy | Critical recall | Estimated energy (mJ) |
|---|---:|---:|---:|---:|---:|---:|
| M1 FP32 | 0.00093 | 0.00109 | 5.19 | 100% | 100% | 0.001626 |
| M2 PTQ INT8 | 0.00105 | 0.00112 | 3.38 | 100% | 100% | 0.001835 |
| M3 Pruned INT8 | 0.00107 | 0.00108 | 2.94 | 100% | 100% | 0.001876 |

All three were tested on the same **57 synthetic validation windows** on our WSL laptop. These tiny timing differences vary between runs, and the energy figures use a TDP estimate, not direct electrical measurement. The latest script reported **M1 and M3** as Pareto-optimal. M1 had the lowest mean latency, while M3 had the smallest model file and tensor memory (545 bytes). We still recommend M3 for a cautious *pilot*, not for deployment to real trucks without physical-device validation. For full evidence see `evidence/latest_run_2026-11-04.txt` and `optimisation/results/benchmark_results.csv`.
