#!/usr/bin/env python3
"""Task D1: generate the labelled training dataset (raw 6-value feature vectors)."""
import argparse
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "data_pipeline"))
import preprocessing as prep  # noqa: E402

# label, name, simulator mode, duration (s), seed
CLASSES = [
    (0, "Normal",   "none",       1200, 101),
    (1, "Warning",  "temp_drift",  900, 102),
    (2, "Critical", "combined",    900, 103),
]
VAL_FRACTION = 0.20
PURGE = 2   # windows dropped between train and validation (30 s windows, 10 s step)


def main():
    p = argparse.ArgumentParser(description="Generate the LogiEdge training dataset")
    p.add_argument("--drift-cap", type=float, default=None)
    p.add_argument("--out", default=os.path.join(ROOT, "training", "dataset.npz"))
    args = p.parse_args()

    X, y, is_val, idx = [], [], [], []
    print(f"{'class':10}{'mode':12}{'windows':>8}{'train':>7}{'val':>6}{'purged':>8}")
    for label, name, mode, duration, seed in CLASSES:
        wins = np.array(prep.simulate_windows(mode, duration, seed=seed,
                                              drift_cap=args.drift_cap))
        n = len(wins)
        n_val = int(round(VAL_FRACTION * n))
        n_train = n - n_val - PURGE
        keep = np.r_[0:n_train, n - n_val:n]
        X.append(wins[keep])
        y.append(np.full(len(keep), label))
        is_val.append(np.r_[np.zeros(n_train, bool), np.ones(n_val, bool)])
        idx.append(keep)
        print(f"{name:10}{mode:12}{n:8d}{n_train:7d}{n_val:6d}{PURGE:8d}")

    X = np.vstack(X)
    y = np.concatenate(y)
    is_val = np.concatenate(is_val)
    idx = np.concatenate(idx)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    np.savez(args.out, X_raw=X, y=y, is_val=is_val, window_idx=idx)
    csv = os.path.splitext(args.out)[0] + ".csv"
    np.savetxt(csv, np.column_stack([X, y, is_val]), delimiter=",",
               header=",".join(prep.FEATURE_NAMES) + ",label,is_val", comments="")
    print(f"\nTotal {len(y)} windows: train {int((~is_val).sum())}, val {int(is_val.sum())}")
    print(f"Saved {args.out} and {csv}")


if __name__ == "__main__":
    main()
