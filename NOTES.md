# Engineering notes — LogiEdge, Group 15

These notes record our main design choices and the evidence behind them.

- **Edge decision:** Raspberry Pi 5 (8 GB) + AI HAT+ chosen against the 10 W scenario limit. This is a design recommendation; tests ran on a WSL laptop.
- **Sensor data:** temperature 1 Hz, vibration RMS 0.5 Hz, and discrete door events. The brief's 500 Hz raw three-axis vibration stream is used for **bandwidth analysis**, not published by this simulator.
- **Preprocessing:** five-sample moving averages; 30-second windows every 10 seconds; six fused features; saved Normal-class statistics in `training_stats.npy`; z-score clipping to ±10.
- **Models:** M1 FP32, M2 PTQ INT8 and M3 35% structured-pruned INT8. M2 remains the source-tree Docker baseline; M3 (hash `84ff2345`) is deployed in the final live run. All three obtained 100% accuracy and Critical recall only on the 57 synthetic validation windows.
- **Drift reference:** 300 Normal windows, four `p_normal` bins; reference is created for the deployed model. Stage 6 uses 60-second evaluations, up to 100 inference results, a 0.25 alert threshold and 0.10 recovery threshold.
- **Final Stage 6:** 1× time, 1,260 seconds. Anomaly starts at 120 s, stops at 240 s; PSI 0.000 → 2.369 → peak 4.604 → 0.000 at `n=100`. Two queued Critical alerts delivered after the operations-centre container restarted.
- **OTA:** image M2 1.0 to M3 1.1. Estimated transfer 119.649 MB/truck for full image vs 0.00573 MB/truck for cached layers. M3 rollouts in our test are local Ansible deployments. The proposed ten-truck canary is an operational recommendation, not implemented fleet control.
- **Limitations:** synthetic faults are easy to separate; steep temperature drift; no real cellular outage or Pi 5 measurements; TDP-based energy estimate rather than a wattmeter; demo MQTT/HTTP endpoints need production security.
- **Evidence:** `evidence/latest_run_2026-11-04.txt`, `optimisation/results/benchmark_results.csv`, `training/results/stats_shift_results.csv`, `reports/final_report.pdf`. Older raw outputs are retained under `evidence/archive/`.
