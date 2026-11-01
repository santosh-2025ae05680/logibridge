#!/usr/bin/env python3
"""Read-only, reproducible M1/M2/M3 validation and confusion matrices.

Uses the repository's held-out split and saved training statistics. Does not
retrain, rewrite models, or mutate training data.
"""
import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "data_pipeline"), str(ROOT / "training")]
import preprocessing as prep
from tflite_utils import TFLiteClassifier

MODELS = [("M1 FP32", "mlp_fp32.tflite"),
          ("M2 PTQ INT8", "mlp_int8.tflite"),
          ("M3 Pruned INT8", "mlp_pruned_int8.tflite")]
CLASSES = ("Normal", "Warning", "Critical")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", type=Path, default=ROOT / "training/dataset.npz")
    p.add_argument("--models-dir", type=Path, default=ROOT / "training/models")
    args = p.parse_args()
    for path in (args.dataset, *(args.models_dir / name for _, name in MODELS)):
        if not path.is_file():
            p.error(f"Missing required file: {path}")
    with np.load(args.dataset) as data:
        features = np.asarray(data["X_raw"])
        labels = np.asarray(data["y"], dtype=int)
        is_val = np.asarray(data["is_val"], dtype=bool)
    mean, std = prep.load_stats()
    x = prep.normalise(features[is_val], mean, std).astype(np.float32)
    y = labels[is_val]
    if len(y) == 0:
        p.error("Validation split is empty")

    print("Held-out synthetic validation dataset (same windows for every model)")
    print(f"{'Class':12} {'Training':>9} {'Validation':>11}")
    for c, label in enumerate(CLASSES):
        print(f"{label:12} {np.sum((labels == c) & ~is_val):9d} {np.sum(y == c):11d}")
    print(f"{'TOTAL':12} {np.sum(~is_val):9d} {len(y):11d}\n")
    print("Confusion matrices: rows=actual, columns=predicted [Normal, Warning, Critical]")
    for label, file in MODELS:
        path = args.models_dir / file
        pred = TFLiteClassifier(str(path)).predict(x)
        cm = np.zeros((3, 3), dtype=int)
        for actual, predicted in zip(y, pred):
            cm[actual, predicted] += 1
        mask = y == 2
        recall = 100.0 * np.mean(pred[mask] == 2) if mask.any() else float("nan")
        print(f"{label}: size={path.stat().st_size/1024:.2f} KB "
              f"accuracy={100*np.mean(pred == y):.2f}% "
              f"Critical recall={recall:.2f}%" if mask.any() else
              f"{label}: size={path.stat().st_size/1024:.2f} KB "
              f"accuracy={100*np.mean(pred == y):.2f}% Critical recall=N/A (no Critical windows)")
        for row in cm:
            print("   ", row.tolist())
    print("\nNote: synthetic held-out results, not real-truck validation.")


if __name__ == "__main__":
    main()
