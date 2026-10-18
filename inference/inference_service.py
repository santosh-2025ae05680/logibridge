#!/usr/bin/env python3
"""LogiEdge edge inference service (Task D2).

MQTT sensor streams -> preprocessing (5-sample MA, 30 s windows, 6 features,
normalise) -> TFLite inference -> result published to the local broker.

Environment variables:
  MODEL_PATH  .tflite model to load            (default /app/model.tflite)
  STATS_PATH  normalisation stats              (default /app/training_stats.npy)
  TRUCK_ID    truck identifier                 (default TRUCK_001)
  MQTT_HOST   broker host                      (default localhost)
  MQTT_PORT   broker port                      (default 1883)
  ALERT_LOG   local alert log (JSON lines)     (default /data/alerts.jsonl)
  REALERT_S   repeat an active alert after N s (default 60)
"""
import hashlib
import json
import os
import signal
import sys
import threading
import time

import numpy as np
import paho.mqtt.client as mqtt

import preprocessing as prep
from tflite_runner import TFLiteClassifier

MODEL_PATH = os.environ.get("MODEL_PATH", "/app/model.tflite")
STATS_PATH = os.environ.get("STATS_PATH", "/app/training_stats.npy")
TRUCK_ID = os.environ.get("TRUCK_ID", "TRUCK_001")
MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
ALERT_LOG = os.environ.get("ALERT_LOG", "/data/alerts.jsonl")
REALERT_S = float(os.environ.get("REALERT_S", "60"))
RESET_GAP_S = 120.0          # restart windowing after a sensor gap or a clock jump

LABELS = ["Normal", "Warning", "Critical"]
QOS_SENSOR, QOS_INFERENCE, QOS_ALERT, QOS_STATUS = 0, 0, 1, 1


def jdump(obj):
    return json.dumps(obj, separators=(",", ":"))


def make_client(client_id):
    try:                                    # paho-mqtt >= 2.0
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    except AttributeError:                  # paho-mqtt 1.x
        return mqtt.Client(client_id=client_id)


class InferenceService:
    def __init__(self):
        if not os.path.exists(MODEL_PATH):
            sys.exit(f"Model not found: {MODEL_PATH}")
        with open(MODEL_PATH, "rb") as f:
            sha = hashlib.sha256(f.read()).hexdigest()[:8]
        self.model_tag = f"{os.path.basename(MODEL_PATH)}@{sha}"
        self.model = TFLiteClassifier(MODEL_PATH)
        self.mean, self.std = prep.load_stats(STATS_PATH)   # never recomputed at runtime

        base = f"logibridge/trucks/{TRUCK_ID}"
        self.t_temp = f"{base}/sensors/temperature"
        self.t_vib = f"{base}/sensors/vibration_rms"
        self.t_inference = f"{base}/inference"
        self.t_alerts = f"{base}/alerts"
        self.t_status = f"{base}/status/inference"

        self.reset()
        self.client = make_client(f"infer-{TRUCK_ID}")

    def reset(self):
        self.extractor = prep.WindowFeatureExtractor()
        self.last_ts = None
        self.last_class = 0
        self.last_alert_ts = None

    # ---- MQTT callbacks (signatures work for paho 1.x and 2.x) ----
    def on_connect(self, client, userdata, *rest):
        client.subscribe([(self.t_temp, QOS_SENSOR), (self.t_vib, QOS_SENSOR)])
        client.publish(self.t_status, jdump({"state": "online", "model": self.model_tag}),
                       qos=QOS_STATUS, retain=True)
        print("connected; subscribed to sensor topics", flush=True)

    def on_message(self, client, userdata, msg):
        try:
            p = json.loads(msg.payload)
            ts, value = float(p["ts"]), float(p["value"])
        except (ValueError, KeyError, TypeError):
            return
        if self.last_ts is not None and (ts < self.last_ts - 5 or ts - self.last_ts > RESET_GAP_S):
            print(f"stream discontinuity at ts={ts:.0f}: resetting window state", flush=True)
            self.reset()
        self.last_ts = ts

        if msg.topic == self.t_temp:
            windows = self.extractor.push_temperature(ts, value)
        elif msg.topic == self.t_vib:
            windows = self.extractor.push_vibration(ts, value)
        else:
            return
        for end_ts, feats in windows:
            self.classify(end_ts, feats)

    # ---- inference and alerting ----
    def classify(self, end_ts, feats):
        z = prep.normalise(feats, self.mean, self.std).astype(np.float32)
        t0 = time.perf_counter()
        probs = self.model.predict_proba(z.reshape(1, -1))[0]
        latency_ms = (time.perf_counter() - t0) * 1000.0
        cls = int(np.argmax(probs))
        result = {
            "ts": round(end_ts, 3), "class": cls, "label": LABELS[cls],
            "confidence": round(float(probs[cls]), 4),
            "p_normal": round(float(probs[0]), 4),
            "probs": [round(float(p), 4) for p in probs],
            "latency_ms": round(latency_ms, 3), "model": self.model_tag,
        }
        self.client.publish(self.t_inference, jdump(result), qos=QOS_INFERENCE)
        print(f"window end={end_ts:.0f}  {LABELS[cls]:8}  conf={probs[cls]:.3f}  "
              f"p_normal={probs[0]:.3f}  lat={latency_ms:.3f} ms", flush=True)
        self.maybe_alert(end_ts, cls, probs)

    def maybe_alert(self, end_ts, cls, probs):
        if cls == 0:
            self.last_alert_ts = None
        else:
            due = (self.last_alert_ts is None or cls > self.last_class
                   or end_ts - self.last_alert_ts >= REALERT_S)
            if due:
                alert = {"alert_id": f"{TRUCK_ID}-{int(end_ts)}", "truck_id": TRUCK_ID,
                         "ts": round(end_ts, 3), "class": cls, "label": LABELS[cls],
                         "confidence": round(float(probs[cls]), 4), "model": self.model_tag}
                self.client.publish(self.t_alerts, jdump(alert), qos=QOS_ALERT)
                try:
                    os.makedirs(os.path.dirname(ALERT_LOG), exist_ok=True)
                    with open(ALERT_LOG, "a") as f:
                        f.write(jdump(alert) + "\n")
                except OSError as exc:
                    print(f"warning: cannot write alert log ({exc})", flush=True)
                print(f"ALERT {LABELS[cls]} id={alert['alert_id']}", flush=True)
                self.last_alert_ts = end_ts
        self.last_class = cls


def main():
    svc = InferenceService()
    c = svc.client
    c.will_set(svc.t_status, jdump({"state": "offline"}), qos=QOS_STATUS, retain=True)
    c.on_connect = svc.on_connect
    c.on_message = svc.on_message
    c.reconnect_delay_set(min_delay=1, max_delay=30)
    print(f"model={svc.model_tag} input={svc.model.inp['dtype'].__name__} "
          f"broker={MQTT_HOST}:{MQTT_PORT} truck={TRUCK_ID}", flush=True)

    while True:                             # the broker may start after this container
        try:
            c.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
            break
        except OSError as exc:
            print(f"broker {MQTT_HOST}:{MQTT_PORT} not reachable ({exc}); retrying in 3 s",
                  flush=True)
            time.sleep(3)
    c.loop_start()

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *a: stop.set())   # docker stop sends SIGTERM
    signal.signal(signal.SIGINT, lambda *a: stop.set())
    while not stop.wait(1.0):
        pass

    try:
        info = c.publish(svc.t_status, jdump({"state": "offline"}), qos=QOS_STATUS, retain=True)
        info.wait_for_publish(timeout=2)
    except Exception:
        pass
    c.disconnect()
    c.loop_stop()
    print("stopped", flush=True)


if __name__ == "__main__":
    main()
