# Apply the LogiBridge feature patch on a new branch from main

Baseline ZIP used: `b36d49b448b969d5df7008cf2c420d98568a8427`.

## Option A — Git checkout with patch ZIP (recommended)

Run from the machine on which you can access GitHub:

```bash
git clone https://github.com/santosh-2025ae05680/logibridge.git
cd logibridge
git fetch origin
git switch main
git pull --ff-only origin main
git switch -c feature/offline-alert-sync
```

Unzip `logibridge-feature-patch.zip` **inside** this repository root, preserving
folders and overwriting its matching files (on Linux/macOS:
`unzip -o /path/to/logibridge-feature-patch.zip`).

The provided patch was created from the uploaded ZIP baseline. If main has moved
since that snapshot, carefully check the diff for conflicts before committing.

```bash
python -m unittest discover -s tests -v
git status
git diff --check
git diff
git add inference/inference_service.py inference/alert_sync.py monitoring/drift_monitor.py operations_centre tests deployment/NEW_FEATURES.md BRANCH_INSTRUCTIONS.md
git commit -m "Add offline alert synchronization and door-state monitoring"
git push -u origin feature/offline-alert-sync
```

Create a pull request: `feature/offline-alert-sync` -> `main`. Do not merge
until Docker/MQTT integration is tested on your workstation.

**PowerShell:** unzip with `Expand-Archive` to a temporary folder; copy its files
into the cloned repository, preserving relative paths, or use Windows Explorer
Extract All. Git Bash supports the commands above.

## Option B — Full project ZIP

The full ZIP includes all files from the uploaded snapshot plus this feature patch.
If your actual GitHub main is newer, **do not replace it wholesale** with that
full ZIP; use Option A and inspect conflicts.

## Local testing

```bash
python -m unittest discover -s tests -v
python operations_centre/server.py
```

See `deployment/NEW_FEATURES.md` for the offline/online demonstration and runtime
integration limitations.
