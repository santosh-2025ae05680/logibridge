# Deployment Recommendation (Task F3)

## 1. Results (optimisation/results/benchmark_results.csv)
| Variant | Size KB | Params | MACs | Tensor memory B | Mean ms | p95 ms | Accuracy % | Critical recall % | Energy uJ |
|---|---|---|---|---|---|---|---|---|---|
| M1 FP32 | 5.19 | 803 | 752 | 3452 | 0.00230 | 0.00250 | 100 | 100 | 4.03 |
| M2 PTQ INT8 | 3.38 | 803 | 752 | 1016 | 0.00242 | 0.00268 | 100 | 100 | 4.24 |
| M3 Pruned+INT8 | 2.94 | 400 | 366 | 545 | 0.00241 | 0.00248 | 100 | 100 | 4.23 |

All three variants clear the hard gate (Class 2 recall above 95%). At this model size
the latency differences between them are within trial-to-trial noise (the medians differ by at most 5%), so
latency does not separate the variants. Energy is derived as E = P x t, so it adds no
information beyond latency. The real differences are size (M3 is 43% smaller than M1
and 13% smaller than M2) and working memory (545 bytes against 1016 and 3452).

## 2. Latency budget from the 90 s SLA
- SLA: 90 s from fault signature to alert.
- Worst-case windowing: a fault that starts just after a window closes needs a full 30 s
  window, and windows close every 10 s, so about 40 s (50 s if two consecutive windows
  must agree).
- Publishing the alert and writing the local log take under 1 s.
- This leaves about 49 s for inference (39 s with two-window confirmation).
- Inference runs once per 10 s step, so it must finish well inside 10 s to avoid a
  backlog. The binding per-inference budget is therefore 10 s.
- Measured: 0.0024 ms (2.4 microseconds) on this laptop. Allowing a conservative 50x for a Raspberry Pi 5 core
  (an assumption to be confirmed on the device) gives about 0.12 ms, which is about 83,000 times inside
  the 10 s budget. The brief's hypothetical 45 MFLOP model has a Roofline lower bound of
  2.81 ms, still about 32,000 times inside the 90 s SLA.

## 3. Memory constraints of the chosen device (Raspberry Pi 5)
| Resource | Pi 5 | Model use |
|---|---|---|
| Storage (the equivalent of Flash) | microSD or NVMe, 16 GB or more | model 2.94-5.19 KB; image 364 MB uncompressed (120.65 MB compressed) |
| RAM | 8 GB LPDDR4X | container uses 61.5 MiB (docker stats, idle service) |
| Cache (the closest equivalent of SRAM) | per core 64 KB L1 data, 512 KB L2; 2 MB shared L3 | working tensors 545-3452 bytes fit inside the L1 data cache |

For reference, the rejected STM32H7 option has about 2 MB Flash and about 1 MB SRAM. Even that device could hold these models (2.94 KB is
0.15% of Flash), and the brief's 280 KB production model would still fit. The reason
for rejecting it was the software stack (Docker, Mosquitto, Ansible), not memory.

## 4. Recommendation
**Deploy M3 (pruned + INT8).** Its measured latency is within 5% of M2 (a tie), so the
choice rests on size and memory.

1. It clears the safety gate: Critical recall is 100% on the held-out windows, the same as
   M1 and M2.
2. It meets the latency budget by several orders of magnitude, like the others.
3. It is the smallest on every resource: 2.94 KB file, 400 parameters, 366 MACs and 545
   bytes of working tensors. That leaves the most headroom if the production model grows.

Risks and mitigations:
- Pruning removes capacity (21 and 10 hidden neurons). The simulated classes are separated
  by more than 10 sigma, so 100% accuracy is not evidence of robustness on real,
  overlapping fault data. Mitigation: the canary rollout and promotion gate from E3
  (Class 2 recall above 95% on a replay set, PSI below 0.25), with M2 kept on the truck as
  the instant rollback model.
- The INT8 input range was calibrated on simulated data and saturates outside it.
- The latency benefit of pruning was not demonstrated, so the case for M3 over M2 rests on
  size and memory margin, not speed.
- Releasing M3 needs its own reference_dist.json (built for the deployed model) and a new
  image tag.
