#!/usr/bin/env python3
"""Task F1 (M3): 35% structured pruning with a PolynomialDecay schedule, then full INT8 PTQ.

"Filter" pruning for a Dense MLP means removing whole neurons. tfmot block pruning with
block_size = (in_features, 1) prunes each output neuron's complete weight column; the
pruned neurons are then removed physically, so the model really has fewer weights and MACs.

Stages run in separate processes, so tfmot's legacy-Keras setting cannot interfere with the
TFLite conversion:
  extract : mlp_fp32.keras -> numpy weights
  prune   : tfmot pruning + fine-tuning + removal of the pruned neurons
  convert : compact weights -> full-INT8 TFLite (M3) + evaluation
With no --stage, all three run in order.
"""
import argparse
import os
import subprocess
import sys

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MODELS = os.path.join(HERE, "models")
sys.path.insert(0, os.path.join(ROOT, "data_pipeline"))

FP32_KERAS = os.path.join(MODELS, "mlp_fp32.keras")
FP32_WEIGHTS = os.path.join(MODELS, "mlp_fp32_weights.npz")
COMPACT_WEIGHTS = os.path.join(MODELS, "mlp_pruned_weights.npz")
M2_PATH = os.path.join(MODELS, "mlp_int8.tflite")
M3_PATH = os.path.join(MODELS, "mlp_pruned_int8.tflite")

TARGET_SPARSITY = 0.35
EPOCHS = 30
BATCH = 16
LR = 5e-4
SEED = 0
MIN_CALIBRATION = 200
KEYS = ("W1", "b1", "W2", "b2", "W3", "b3")


def load_data():
    import preprocessing as prep
    data = np.load(os.path.join(HERE, "dataset.npz"))
    mean, std = prep.load_stats()
    X = prep.normalise(data["X_raw"], mean, std).astype(np.float32)
    y = data["y"].astype(np.int32)
    val = data["is_val"].astype(bool)
    return X[~val], y[~val], X[val], y[val]


def forward(X, W1, b1, W2, b2, W3, b3):
    h = np.maximum(X @ W1 + b1, 0)
    h = np.maximum(h @ W2 + b2, 0)
    z = h @ W3 + b3
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def n_params(W1, W2, W3):
    return sum(W.size + W.shape[1] for W in (W1, W2, W3))


def n_macs(W1, W2, W3):
    return sum(W.size for W in (W1, W2, W3))


def pick_units(W, fraction):
    """Indices of the neurons (columns) with the smallest L1 norm."""
    n = W.shape[1]
    k = n - int(round(n * (1.0 - fraction)))
    norms = np.abs(W).sum(axis=0)
    return np.sort(np.argsort(norms)[:k]), norms


# ------------------------------------------------------------------ stage: extract
def stage_extract():
    import tensorflow as tf
    model = tf.keras.models.load_model(FP32_KERAS)
    w = model.get_weights()
    np.savez(FP32_WEIGHTS, **dict(zip(KEYS, w)))
    print(f"Extracted {len(w)} weight arrays from {FP32_KERAS}")


# ------------------------------------------------------------------ stage: prune
def stage_prune():
    import tensorflow as tf
    import tensorflow_model_optimization as tfmot

    np.random.seed(SEED)
    tf.random.set_seed(SEED)
    Xtr, ytr, Xva, yva = load_data()
    w = np.load(FP32_WEIGHTS)
    W = {k: w[k] for k in KEYS}
    n1, n2 = W["W1"].shape[1], W["W2"].shape[1]

    steps_per_epoch = int(np.ceil(len(Xtr) / BATCH))
    total_steps = steps_per_epoch * EPOCHS
    schedule = tfmot.sparsity.keras.PolynomialDecay(
        initial_sparsity=0.0, final_sparsity=TARGET_SPARSITY,
        begin_step=0, end_step=int(0.8 * total_steps), frequency=5)
    print(f"Pruning schedule: 0 -> {TARGET_SPARSITY:.0%} over {int(0.8 * total_steps)} of "
          f"{total_steps} steps (PolynomialDecay)")

    L = tf.keras.layers

    def dense(units, activation, in_dim, wk, bk):
        layer = L.Dense(units, activation=activation)
        layer.build((None, in_dim))
        layer.set_weights([W[wk], W[bk]])
        return layer

    d1 = dense(n1, "relu", 6, "W1", "b1")
    d2 = dense(n2, "relu", n1, "W2", "b2")
    d3 = dense(3, "softmax", n2, "W3", "b3")
    prune = tfmot.sparsity.keras.prune_low_magnitude
    model = tf.keras.Sequential([
        tf.keras.Input(shape=(6,)),
        prune(d1, pruning_schedule=schedule, block_size=(6, 1)),     # whole neurons
        prune(d2, pruning_schedule=schedule, block_size=(n1, 1)),
        d3,                                                          # output layer kept
    ])
    model.compile(optimizer=tf.keras.optimizers.Adam(LR),
                  loss="sparse_categorical_crossentropy", metrics=["accuracy"])
    model.fit(Xtr, ytr, validation_data=(Xva, yva), epochs=EPOCHS, batch_size=BATCH,
              shuffle=True, verbose=2, callbacks=[tfmot.sparsity.keras.UpdatePruningStep()])
    stripped = tfmot.sparsity.keras.strip_pruning(model)
    p = dict(zip(KEYS, [np.array(a) for a in stripped.get_weights()]))

    # ---- identify the pruned neurons and make the pruned reference exact ----
    idx1, norms1 = pick_units(p["W1"], TARGET_SPARSITY)
    idx2, norms2 = pick_units(p["W2"], TARGET_SPARSITY)
    dead1 = np.zeros(n1, bool)
    dead1[idx1] = True
    dead2 = np.zeros(n2, bool)
    dead2[idx2] = True
    print(f"\nLayer 1: pruned {dead1.sum()} of {n1} neurons; largest removed L1 norm "
          f"{norms1[dead1].max():.2e}, smallest kept {norms1[~dead1].min():.3f}")
    print(f"Layer 2: pruned {dead2.sum()} of {n2} neurons; largest removed L1 norm "
          f"{norms2[dead2].max():.2e}, smallest kept {norms2[~dead2].min():.3f}")
    if norms1[dead1].max() > 1e-3 * norms1[~dead1].min() or \
            norms2[dead2].max() > 1e-3 * norms2[~dead2].min():
        print("WARNING: removed neurons are not (near) zero; pruning masks may not have been "
              "applied. Send me this output.")
    p["W1"][:, dead1] = 0.0
    p["W2"][:, dead2] = 0.0
    pruned_ref = (p["W1"], p["b1"], p["W2"], p["b2"], p["W3"], p["b3"])

    # ---- physical removal; constants of dead neurons are folded into the next bias ----
    b2 = p["b2"] + np.maximum(p["b1"][dead1], 0) @ p["W2"][dead1, :]
    b3 = p["b3"] + np.maximum(b2[dead2], 0) @ p["W3"][dead2, :]
    c = {
        "W1": p["W1"][:, ~dead1], "b1": p["b1"][~dead1],
        "W2": p["W2"][~dead1][:, ~dead2], "b2": b2[~dead2],
        "W3": p["W3"][~dead2, :], "b3": b3,
    }

    Xall = np.vstack([Xtr, Xva])
    ref_p = forward(Xall, *pruned_ref)
    cmp_p = forward(Xall, c["W1"], c["b1"], c["W2"], c["b2"], c["W3"], c["b3"])
    diff = float(np.abs(ref_p - cmp_p).max())
    print(f"\nCompact vs pruned-reference max |delta prob|: {diff:.2e} "
          f"({'exact' if diff < 1e-5 else 'MISMATCH'})")
    if diff >= 1e-5:
        sys.exit("Neuron removal changed the function; stopping.")

    acc_ref = 100.0 * np.mean(np.argmax(forward(Xva, *pruned_ref), axis=1) == yva)
    acc_cmp = 100.0 * np.mean(np.argmax(forward(Xva, c["W1"], c["b1"], c["W2"], c["b2"],
                                                c["W3"], c["b3"]), axis=1) == yva)
    print(f"Validation accuracy after pruning (FP32): {acc_ref:.2f}% (compact: {acc_cmp:.2f}%)")
    print(f"Parameters: {n_params(W['W1'], W['W2'], W['W3'])} -> "
          f"{n_params(c['W1'], c['W2'], c['W3'])}")
    print(f"MACs      : {n_macs(W['W1'], W['W2'], W['W3'])} -> "
          f"{n_macs(c['W1'], c['W2'], c['W3'])}")
    print(f"Layer widths: 6-{n1}-{n2}-3  ->  6-{c['W1'].shape[1]}-{c['W2'].shape[1]}-3")
    np.savez(COMPACT_WEIGHTS, **c)
    print(f"Saved {COMPACT_WEIGHTS}")


# ------------------------------------------------------------------ stage: convert
def stage_convert():
    import tensorflow as tf
    from tflite_utils import TFLiteClassifier

    Xtr, ytr, Xva, yva = load_data()
    if len(Xtr) < MIN_CALIBRATION:
        sys.exit(f"Need >= {MIN_CALIBRATION} calibration samples, have {len(Xtr)}")
    w = np.load(COMPACT_WEIGHTS)
    c = {k: w[k] for k in KEYS}
    n1, n2 = c["W1"].shape[1], c["W2"].shape[1]

    L = tf.keras.layers
    model = tf.keras.Sequential([
        tf.keras.Input(shape=(6,)),
        L.Dense(n1, activation="relu"),
        L.Dense(n2, activation="relu"),
        L.Dense(3, activation="softmax"),
    ])
    model.set_weights([c[k] for k in KEYS])

    def representative_data():
        for row in Xtr:
            yield [row.reshape(1, 6)]

    conv = tf.lite.TFLiteConverter.from_keras_model(model)
    conv.optimizations = [tf.lite.Optimize.DEFAULT]
    conv.representative_dataset = representative_data
    conv.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    conv.inference_input_type = tf.int8
    conv.inference_output_type = tf.int8
    with open(M3_PATH, "wb") as f:
        f.write(conv.convert())
    print(f"Calibration samples: {len(Xtr)}; saved {M3_PATH}")

    def evaluate(path):
        pred = TFLiteClassifier(path).predict(Xva)
        crit = yva == 2
        return 100.0 * np.mean(pred == yva), 100.0 * np.mean(pred[crit] == 2)

    w0 = np.load(FP32_WEIGHTS)
    rows = [("M2 PTQ INT8", M2_PATH, n_params(w0["W1"], w0["W2"], w0["W3"]),
             n_macs(w0["W1"], w0["W2"], w0["W3"])),
            ("M3 pruned+INT8", M3_PATH, n_params(c["W1"], c["W2"], c["W3"]),
             n_macs(c["W1"], c["W2"], c["W3"]))]
    print(f"\n{'variant':16}{'params':>8}{'MACs':>7}{'size KB':>9}{'val acc %':>11}{'Crit recall %':>15}")
    for name, path, params, macs in rows:
        acc, rec = evaluate(path)
        print(f"{name:16}{params:8d}{macs:7d}{os.path.getsize(path) / 1024:9.2f}{acc:11.2f}{rec:15.2f}")


def main():
    p = argparse.ArgumentParser(description="M3: structured pruning + INT8 PTQ")
    p.add_argument("--stage", choices=["extract", "prune", "convert"], default=None)
    args = p.parse_args()
    if args.stage is None:
        for st in ("extract", "prune", "convert"):
            print(f"\n=== stage: {st} ===", flush=True)
            subprocess.run([sys.executable, os.path.abspath(__file__), "--stage", st], check=True)
        return
    {"extract": stage_extract, "prune": stage_prune, "convert": stage_convert}[args.stage]()


if __name__ == "__main__":
    main()
