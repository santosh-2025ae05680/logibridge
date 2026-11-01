#!/usr/bin/env python3
"""Task F1 (M1 and M2): TFLite FP32 baseline and full-INT8 post-training quantisation."""
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

MODELS = os.path.join(HERE, "models")
MIN_CALIBRATION = 200


def kb(path):
    return os.path.getsize(path) / 1024


def main():
    data = np.load(os.path.join(ROOT, "training", "dataset.npz"))
    mean, std = prep.load_stats()
    X = prep.normalise(data["X_raw"], mean, std).astype(np.float32)
    y = data["y"].astype(int)
    val = data["is_val"].astype(bool)
    Xtr, Xva, yva = X[~val], X[val], y[val]
    if len(Xtr) < MIN_CALIBRATION:
        sys.exit(f"Need >= {MIN_CALIBRATION} calibration samples, have {len(Xtr)}")
    print(f"Calibration samples: {len(Xtr)} (training windows only)")

    model = tf.keras.models.load_model(os.path.join(MODELS, "mlp_fp32.keras"))

    # ---- M1: FP32 TFLite baseline ----
    fp32_path = os.path.join(MODELS, "mlp_fp32.tflite")
    with open(fp32_path, "wb") as f:
        f.write(tf.lite.TFLiteConverter.from_keras_model(model).convert())

    # ---- M2: full-integer INT8 post-training quantisation ----
    def representative_data():
        for row in Xtr:
            yield [row.reshape(1, 6)]

    conv = tf.lite.TFLiteConverter.from_keras_model(model)
    conv.optimizations = [tf.lite.Optimize.DEFAULT]
    conv.representative_dataset = representative_data
    conv.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    conv.inference_input_type = tf.int8
    conv.inference_output_type = tf.int8
    int8_path = os.path.join(MODELS, "mlp_int8.tflite")
    with open(int8_path, "wb") as f:
        f.write(conv.convert())

    # ---- Evaluate on the held-out validation windows ----
    keras_p = model.predict(Xva, verbose=0)
    fp32 = TFLiteClassifier(fp32_path)
    int8 = TFLiteClassifier(int8_path)
    p_fp32 = fp32.predict_proba(Xva)
    p_int8 = int8.predict_proba(Xva)
    crit = yva == 2

    def acc(p):
        return 100.0 * np.mean(np.argmax(p, axis=1) == yva)

    def crit_recall(p):
        return 100.0 * np.mean(np.argmax(p, axis=1)[crit] == 2)

    print(f"\n{'variant':16}{'size KB':>9}{'val acc %':>11}{'Critical recall %':>19}")
    print(f"{'Keras FP32':16}{'-':>9}{acc(keras_p):11.2f}{crit_recall(keras_p):19.2f}")
    print(f"{'M1 TFLite FP32':16}{kb(fp32_path):9.2f}{acc(p_fp32):11.2f}{crit_recall(p_fp32):19.2f}")
    print(f"{'M2 TFLite INT8':16}{kb(int8_path):9.2f}{acc(p_int8):11.2f}{crit_recall(p_int8):19.2f}")

    agree = 100.0 * np.mean(fp32.predict(X) == int8.predict(X))
    print(f"\nFP32 vs INT8 class agreement on all {len(X)} windows: {agree:.2f}%")
    print(f"Max |P_fp32 - P_int8| on validation: {np.abs(p_fp32 - p_int8).max():.4f}")
    print(f"INT8 input  (scale, zero_point): {int8.inp['quantization']}")
    print(f"INT8 output (scale, zero_point): {int8.out['quantization']}")
    print(f"\nSaved {fp32_path}\n      {int8_path}")


if __name__ == "__main__":
    main()
