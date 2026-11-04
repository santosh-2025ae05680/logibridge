# Group 15 — repository review before final submission

We prepared this cleaned copy from the ZIP supplied for review on 5 November 2026. Our measured results are taken from the **4 November full run**, not from older notes or isolated test commands. We did not change the simulator, preprocessing, models, tests, deployment playbook, Dockerfiles, or runner logic.

## Removed because they are not submission material

- `scenario_architecture/system_architecture.pngZone.Identifier`
- `demo/show_model_results.py:Zone.Identifier`
- `demo/demo_runner.sh:Zone.Identifier`
- `operations_centre/alerts.sqlite3`
- `UPDATE_NOTES.txt`
- `BRANCH_INSTRUCTIONS.md`
- `DOCUMENTATION_AUDIT.md`
- `deployment/run4_idempotent_output.txt`

## Kept, even where files look similar

- All three model variants, their training weights, dataset files and `training_stats.npy` are needed to recreate the model comparison.
- `inference/model.tflite` duplicates the M2 training artifact intentionally; the inference Dockerfile uses that location.
- The architecture PNGs show different views and were not removed based on name similarity.
- We kept all three reports in DOCX/PDF; the updated final report includes architecture, MQTT and Pareto figures.
- Prior command outputs and the old benchmark CSV/chart are under `evidence/archive/` without editing their original results.
- `evidence/latest_run_2026-11-04.txt` is the unedited last full-run terminal capture.

## Updated

The final report, both phase reports, README, stage/demo notes, project `NOTES.md`, MQTT/hardware/architecture notes, OTA and model recommendation notes, latest benchmark CSV/chart, and the final run summary all now refer to the new verified measurements. We write from the team perspective: **we tested**, **our group**, **our measured result**. Source logs remain raw machine output.

## Checks before pushing

1. The default tracked `inference/model.tflite` is M2 (`52ee32f1`), but the tracked `monitoring/reference_dist.json` identifies M3 (`84ff2345`). The guided demo builds the proper M3 reference for M3, but a standalone M2 command should use a matching M2 reference. We did not silently replace either binary/reference.
2. The demo video URL is not in this ZIP. Add the real URL in `demo/demo_video_link.txt`, and check that instructor access to the private repository is configured.
3. Our 60-second PSI checks are real-time. The initial clean PSI is based on eight predictions (`n=8`); the recovered value is based on a full 100-prediction window (`n=100`). This is because the monitor permits early checks after five observations.
4. All model scores are on synthetic validation samples; model power is a TDP-derived estimate, and the network outage uses a stopped operations-centre container rather than an actual cellular modem.
5. Read the final report as a team, particularly the design decisions and technical difficulty. The course requires students' own analysis and understanding.

## Empty-directory marker cleanup

We also removed these redundant `.gitkeep` placeholders because their directories already contain tracked project files:

- `data_pipeline/.gitkeep`
- `inference/.gitkeep`
- `scenario_architecture/.gitkeep`
- `demo/.gitkeep`
- `hardware/.gitkeep`
- `monitoring/.gitkeep`
- `deployment/.gitkeep`
- `training/models/.gitkeep`
- `optimisation/results/.gitkeep`

No model, dataset, figure, test, or final report was deleted.
