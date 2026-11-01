#!/usr/bin/env python3
"""Read-only summary of the three TFLite models on the held-out validation windows.

Nothing is retrained or rewritten, so it is safe to run on camera.
"""
import os
import sys

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "data_pipeline"))
sys.path.insert(0, os.path.join(ROOT, "training"))
import preprocessing as prep  # noqa: E402
from tflite_utils import TFLiteClassifier  # noqa: E402

MODELS = [("M1 FP32", "mlp_fp32.tflite"),
          ("M2 PTQ INT8", "mlp_int8.tflite"),
          ("M3 Pruned+INT8", "mlp_pruned_int8.tflite")]
NAMES = ["Normal", "Warning", "Critical"]

data = np.load(os.path.join(ROOT, "training", "dataset.npz"))
mean, std = prep.load_stats()
X = prep.normalise(data["X_raw"], mean, std).astype(np.float32)
y = data["y"].astype(int)
val = data["is_val"].astype(bool)

print("Dataset windows kept after the 2-window purge (time-ordered 80/20 split):")
print(f"{'class':10}{'train':>7}{'validation':>12}")
for c, n in enumerate(NAMES):
    print(f"{n:10}{int(np.sum((y == c) & ~val)):7d}{int(np.sum((y == c) & val)):12d}")
print(f"{'total':10}{int(np.sum(~val)):7d}{int(np.sum(val)):12d}\n")

Xv, yv = X[val], y[val]
for name, fname in MODELS:
    path = os.path.join(ROOT, "training", "models", fname)
    pred = TFLiteClassifier(path).predict(Xv)
    cm = np.zeros((3, 3), int)
    for t, p in zip(yv, pred):
        cm[t, p] += 1
    print(f"{name:16} size {os.path.getsize(path) / 1024:5.2f} KB   accuracy {100 * np.mean(pred == yv):6.2f}%"
          f"   Critical recall {100 * np.mean(pred[yv == 2] == 2):6.2f}%")
    print(f"  confusion matrix (rows true, columns predicted): {cm.tolist()}")
