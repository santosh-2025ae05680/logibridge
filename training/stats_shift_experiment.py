#!/usr/bin/env python3
"""Mandatory C2 experiment: inference with correct normalisation stats vs stats shifted by 3 sigma.

stats shifted by +3 sigma  ->  z' = z - 3   (features look 3 sigma LOWER than training)
stats shifted by -3 sigma  ->  z' = z + 3   (features look 3 sigma HIGHER than training)
"""
import csv
import os
import sys

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import numpy as np
import tensorflow as tf

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "data_pipeline"))
import preprocessing as prep  # noqa: E402
from tflite_utils import TFLiteClassifier  # noqa: E402

SHIFTS = [("correct stats", 0.0), ("stats +3 sigma", 3.0), ("stats -3 sigma", -3.0)]


def main():
    data = np.load(os.path.join(ROOT, "training", "dataset.npz"))
    val = data["is_val"].astype(bool)
    Xraw, y = data["X_raw"][val], data["y"][val].astype(int)
    mean, std = prep.load_stats()

    keras_model = tf.keras.models.load_model(os.path.join(HERE, "models", "mlp_fp32.keras"))
    int8 = TFLiteClassifier(os.path.join(HERE, "models", "mlp_int8.tflite"))
    models = [
        ("FP32 Keras", lambda X: np.argmax(keras_model.predict(X, verbose=0), axis=1)),
        ("INT8 TFLite", int8.predict),
    ]

    rows = []
    print(f"Validation windows: {len(y)}\n")
    print(f"{'model':12}{'clip':>5}  {'stats':16}{'acc %':>7}{'delta':>8}   recall % (Normal / Warning / Critical)")
    for model_name, predict in models:
        for clip in (prep.CLIP_Z, 0):
            base = None
            for label, k in SHIFTS:
                m2, s2 = prep.shifted_stats(mean, std, k)
                X = prep.normalise(Xraw, m2, s2, clip=clip).astype(np.float32)
                pred = predict(X)
                acc = 100.0 * np.mean(pred == y)
                rec = [100.0 * np.mean(pred[y == c] == c) for c in range(3)]
                base = acc if base is None else base
                clip_txt = f"{clip:g}" if clip else "off"
                print(f"{model_name:12}{clip_txt:>5}  {label:16}{acc:7.1f}{acc - base:+8.1f}"
                      f"   {rec[0]:5.1f} / {rec[1]:5.1f} / {rec[2]:5.1f}")
                rows.append([model_name, clip_txt, label, round(acc, 2), round(acc - base, 2)]
                            + [round(r, 2) for r in rec])

    out_dir = os.path.join(ROOT, "training", "results")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "stats_shift_results.csv")
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["model", "clip", "stats", "accuracy_pct", "delta_vs_correct",
                    "recall_normal", "recall_warning", "recall_critical"])
        w.writerows(rows)
    print(f"\nSaved {out}")
    print("\nRaw size of a 3-sigma shift (one sigma from the Normal training stats):")
    for name, s in zip(prep.FEATURE_NAMES, std):
        print(f"  {name:22} 3 sigma = {3 * s:.4f}")


if __name__ == "__main__":
    main()
