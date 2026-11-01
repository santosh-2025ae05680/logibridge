"""Run a TFLite classifier on normalised float features (handles INT8 input/output)."""
import numpy as np
import tensorflow as tf


class TFLiteClassifier:
    def __init__(self, path, num_threads=1):
        self.interp = tf.lite.Interpreter(model_path=path, num_threads=num_threads)
        self.interp.allocate_tensors()
        self.inp = self.interp.get_input_details()[0]
        self.out = self.interp.get_output_details()[0]

    def _quantise(self, x):
        if self.inp["dtype"] == np.float32:
            return x.astype(np.float32)
        scale, zero_point = self.inp["quantization"]
        info = np.iinfo(self.inp["dtype"])
        q = np.round(x / scale + zero_point)
        return np.clip(q, info.min, info.max).astype(self.inp["dtype"])

    def _dequantise(self, y):
        if self.out["dtype"] == np.float32:
            return y
        scale, zero_point = self.out["quantization"]
        return (y.astype(np.float32) - zero_point) * scale

    def predict_proba(self, X):
        """X: (n, 6) normalised float features -> (n, 3) class probabilities."""
        X = np.asarray(X, dtype=np.float32)
        probs = []
        for row in X:
            self.interp.set_tensor(self.inp["index"], self._quantise(row.reshape(1, -1)))
            self.interp.invoke()
            probs.append(self._dequantise(self.interp.get_tensor(self.out["index"]))[0])
        return np.array(probs)

    def predict(self, X):
        return np.argmax(self.predict_proba(X), axis=1)
