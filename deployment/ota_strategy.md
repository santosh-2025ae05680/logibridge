# OTA Strategy Selection (Task E3)

## Assumptions
Model 280 KB (0.28 MB), Rs 0.10/MB, 85 trucks, canary group of 10, one update per
6 weeks (about 8.7 cycles a year). Canary health telemetry: 4 reports a day of 1 KB
for 3 days from each canary truck. Shadow mode runs 7 days; the new model's outputs are
either compared on the truck (1 KB daily summary) or all uploaded (100 B per 10 s
inference). Figures come from deployment/ota_strategy_cost.py.

## Bandwidth cost per update cycle
| Strategy | MB/cycle | Rs/cycle | Rs/year | Trucks that act on an unvalidated model |
|---|---|---|---|---|
| Full replacement | 23.80 | 2.38 | 20.7 | 85 |
| Canary (10, then 75) | 23.92 | 2.39 | 20.8 | 10 |
| Shadow, on-device comparison | 24.39 | 2.44 | 21.2 | 0 |
| Shadow, upload all outputs | 537.88 | 53.79 | 467.4 | 0 |

If the new model is bad: full replacement exposes all 85 trucks and a re-download
rollback brings the cost to Rs 4.76; a canary exposes 10 trucks and costs Rs 0.29
to roll back (Rs 0.57 if the previous model must be downloaded again).

## Recommendation: canary
The bandwidth cost differs by only a few paise per cycle, so cost is not the deciding
factor. Risk is: a missed Critical alert is the Rs 28 lakh failure mode, so the question
is how many trucks a faulty model can reach before it is caught.

- **Canary** limits the exposure to 10 of 85 trucks (12%) for about 0.5% extra
  bytes. Rollback is a switch back to the previous model, which stays stored on the
  truck, so it costs no bytes and works during a 35-90 minute coverage gap. Promotion
  to the other 75 trucks happens only if the gate passes: Class 2 recall above 95% on
  the replay set, PSI below 0.25 over 48-72 hours, and no unexplained change in alert
  rate. Canary trucks should be on short routes with good coverage so that telemetry
  returns quickly.
- **Against full replacement:** all 85 trucks run an unproven model at once. Coverage
  gaps delay the first sign of trouble, so a model that misses faults could do so
  across the whole fleet before anyone notices. Full replacement is cheaper than a canary by only
  Rs 0.01 per cycle.
- **Against shadow mode:** it has zero exposure, but (i) uploading shadow outputs
  costs about 22 times as much and is unreliable over a link with frequent outages,
  while comparing on the truck needs extra logic and storage on a 10 W device;
  (ii) agreement with the current model is not correctness, and rare faults may not
  occur during the shadow week, so Critical recall cannot be measured; (iii) it uses
  one to two weeks of a six-week cycle; (iv) it never exercises the real alert and
  uplink path. A sensible refinement is to run the canary trucks in shadow mode first.

## Note
The baseline INT8 model is 3.38 KB; the M3 candidate is 2.94 KB. The final Docker registry layer-cache experiment measured 0.00573 MB per truck of new compressed layers, so a **model-file-only** transfer of 3.38 KB across 85 trucks would cost about ₹0.029 under the assumed ₹0.10/MB price. This is **not** the full Docker-image download cost. The guided M2→M3 demo measures compressed registry layers separately using `inference/ota_bandwidth.py`; its results depend on the current registry and device cache. The 280 KB figure is the brief's
assumption for a larger production model.

## Implementation versus proposal

The local guided demonstration (`demo/demo_runner.sh`) actually performs an M2→M3 Ansible upgrade and manual rollback command. **It does not implement** automatic canary group selection, shadow inference, a 48–72-hour promotion gate, or rollback decisions triggered by production telemetry. These are risk-management recommendations for an eventual 85-truck system.


## Verified final-run notes (4 November 2026)

We verified the complete pipeline on synthetic data in WSL, using the deployed M3 model. The final Stage 6 ran for 1,260 real seconds at 1× speed, with a combined anomaly from second 120 to 240. The PSI monitor evaluated every 60 seconds over the latest 100 predictions: an initial 0.000 increased to 4.604 and later returned to 0.000 at `n=100`. Two Critical alerts were delivered after the operations-centre service was restored. Ansible's second deployment reported `changed=0`. These are local tests, not measurements on a refrigerated truck or an 85-vehicle fleet. Exact evidence is in `evidence/latest_run_2026-11-04.txt`.

## Latest successful run (4 November 2026)

We completed the full run at 1× for 1,260 seconds, using 60-second PSI checks over 100 predictions. The PSI peaked at 4.604 and recovered to 0.000 with `n=100`. Two offline Critical alerts were acknowledged after reconnecting the operations centre. The complete captured output is in `evidence/latest_run_2026-11-04.txt`. Our latest CPU benchmark places both M1 and M3 on the Pareto frontier; the new numbers are in `optimisation/results/benchmark_results.csv`.
