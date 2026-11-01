#!/usr/bin/env python3
"""Task D1: train the 6-32-16-3 MLP and enforce the 88% validation gate."""
import os
import sys

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import numpy as np
import tensorflow as tf
from sklearn.metrics import confusion_matrix, recall_score
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "data_pipeline"))
import preprocessing as prep  # noqa: E402

GATE = 0.88
EPOCHS = 60
BATCH = 16
SEED = 0
CLASS_NAMES = ["Normal", "Warning", "Critical"]


def main():
    np.random.seed(SEED)
    tf.random.set_seed(SEED)

    data = np.load(os.path.join(ROOT, "training", "dataset.npz"))
    mean, std = prep.load_stats()                       # from training_stats.npy only
    X = prep.normalise(data["X_raw"], mean, std).astype("float32")
    y = data["y"].astype("int32")
    val = data["is_val"].astype(bool)
    Xtr, ytr, Xva, yva = X[~val], y[~val], X[val], y[val]
    print(f"train {len(ytr)} windows, validation {len(yva)} windows")

    model = tf.keras.Sequential([
        tf.keras.Input(shape=(6,)),
        tf.keras.layers.Dense(32, activation="relu"),
        tf.keras.layers.Dense(16, activation="relu"),
        tf.keras.layers.Dense(3, activation="softmax"),
    ])
    model.compile(optimizer=tf.keras.optimizers.Adam(1e-3),
                  loss="sparse_categorical_crossentropy", metrics=["accuracy"])
    model.summary()
    hist = model.fit(Xtr, ytr, validation_data=(Xva, yva), epochs=EPOCHS,
                     batch_size=BATCH, shuffle=True, verbose=2)

    probs = model.predict(Xva, verbose=0)
    pred = np.argmax(probs, axis=1)
    acc = float(np.mean(pred == yva))
    cm = confusion_matrix(yva, pred, labels=[0, 1, 2])
    rec = recall_score(yva, pred, labels=[0, 1, 2], average=None, zero_division=0)

    print(f"\nValidation accuracy: {acc:.4f}   (gate: > {GATE})")
    print("Confusion matrix (rows = true, cols = predicted):")
    print(cm)
    for name, r in zip(CLASS_NAMES, rec):
        print(f"  recall {name:9}: {r:.3f}")
    print("\nConfidence by true class (evidence for the Step 8 PSI definition):")
    for c, name in enumerate(CLASS_NAMES):
        m = yva == c
        print(f"  {name:9} mean max-softmax = {probs[m].max(axis=1).mean():.3f}   "
              f"mean P(Normal) = {probs[m, 0].mean():.3f}")

    if acc <= GATE:
        sys.exit(f"\nFAIL: {acc:.3f} is not above {GATE}. Revisit features or "
                 f"architecture before proceeding.")

    out_dir = os.path.join(ROOT, "training", "models")
    os.makedirs(out_dir, exist_ok=True)
    model.save(os.path.join(out_dir, "mlp_fp32.keras"))

    fig, ax = plt.subplots(1, 2, figsize=(9, 3.2))
    ax[0].plot(hist.history["loss"], label="train")
    ax[0].plot(hist.history["val_loss"], label="validation")
    ax[0].set_title("Loss")
    ax[0].legend()
    ax[1].plot(hist.history["accuracy"], label="train")
    ax[1].plot(hist.history["val_accuracy"], label="validation")
    ax[1].set_title("Accuracy")
    ax[1].legend()
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "training_curves.png"), dpi=150)
    print(f"\nPASS. Saved {out_dir}/mlp_fp32.keras and training_curves.png")


if __name__ == "__main__":
    main()
