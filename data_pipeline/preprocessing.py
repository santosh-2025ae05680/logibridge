#!/usr/bin/env python3
"""LogiEdge preprocessing pipeline (Tasks C2 and C3).

raw streams -> 5-sample moving average -> 30 s windows (10 s step)
            -> 6 joint features (feature-level fusion) -> z-score normalisation

Commands:
  python data_pipeline/preprocessing.py compute-stats   # writes training_stats.npy
  python data_pipeline/preprocessing.py check           # sanity table per anomaly mode
  python data_pipeline/preprocessing.py live            # features from live MQTT streams

To import from another folder: sys.path.insert(0, "data_pipeline").
"""
import argparse
import json
import os
import random
import sys
from collections import deque

import numpy as np
from scipy.stats import kurtosis

FEATURE_NAMES = ["temp_mean", "temp_std", "temp_rate_c_per_min",
                 "vib_rms", "vib_peak", "vib_kurtosis"]
MA_SAMPLES = 5
WINDOW_S = 30.0
STEP_S = 10.0
VIB_PERIOD_S = 2.0                                 # 0.5 Hz vibration stream
WARMUP_S = (MA_SAMPLES - 1) * VIB_PERIOD_S         # keep partial averages out of windows
MIN_TEMP_SAMPLES = 15                              # discard windows with sensor dropouts
MIN_VIB_SAMPLES = 8
CLIP_Z = 10.0
EPS = 5e-4
STATS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "training_stats.npy")


class MovingAverage:
    """Causal moving average over the last n samples."""

    def __init__(self, n=MA_SAMPLES):
        self.buf = deque(maxlen=n)

    def update(self, x):
        self.buf.append(x)
        return sum(self.buf) / len(self.buf)


class WindowFeatureExtractor:
    """Streaming filter + windowing + 6-value feature extraction.

    Feed samples with push_temperature / push_vibration (ts in seconds, taken from
    the message payload, not the arrival time). Each call returns a list of
    (window_end_ts, feature_vector) for every window that has just closed.
    """

    def __init__(self, window_s=WINDOW_S, step_s=STEP_S):
        self.window_s = window_s
        self.step_s = step_s
        self.ma_temp = MovingAverage()
        self.ma_vib = MovingAverage()
        self.temp = deque()          # (relative_ts, filtered_value)
        self.vib = deque()
        self.t0 = None
        self.next_end = None         # relative end time of the next window

    def push_temperature(self, ts, value):
        return self._push(ts, self.ma_temp.update(value), self.temp)

    def push_vibration(self, ts, value):
        return self._push(ts, self.ma_vib.update(value), self.vib)

    def _push(self, ts, filtered, buf):
        if self.t0 is None:
            self.t0 = ts
            self.next_end = self.window_s + WARMUP_S
        rel = ts - self.t0
        buf.append((rel, filtered))
        out = []
        # a window closes when the first sample after its end arrives
        while rel > self.next_end + EPS:
            feats = self._features(self.next_end)
            if feats is not None:
                out.append((self.t0 + self.next_end, feats))
            self.next_end += self.step_s
        self._prune(self.next_end - self.window_s)
        return out

    def _prune(self, lo):
        for buf in (self.temp, self.vib):
            while buf and buf[0][0] <= lo + EPS:
                buf.popleft()

    def _features(self, end):
        lo = end - self.window_s
        temp = [(r, x) for r, x in self.temp if lo + EPS < r <= end + EPS]
        vib = [x for r, x in self.vib if lo + EPS < r <= end + EPS]
        if len(temp) < MIN_TEMP_SAMPLES or len(vib) < MIN_VIB_SAMPLES:
            return None
        minutes = np.array([r for r, _ in temp]) / 60.0
        tx = np.array([x for _, x in temp])
        vx = np.array(vib)
        feats = np.array([
            tx.mean(),                             # temperature mean
            tx.std(ddof=1),                        # temperature standard deviation
            np.polyfit(minutes, tx, 1)[0],         # rate of change, C per minute
            np.sqrt(np.mean(vx ** 2)),             # vibration RMS
            vx.max(),                              # vibration peak
            kurtosis(vx),                          # vibration kurtosis
        ])
        return np.nan_to_num(feats, nan=0.0)       # feature-level fusion: one 6-vector


# ---------------- normalisation ----------------
def save_stats(mean, std, path=STATS_PATH):
    np.save(path, np.vstack([mean, std]))


def load_stats(path=STATS_PATH):
    arr = np.load(path)
    return arr[0], arr[1]


def normalise(features, mean, std, clip=CLIP_Z):
    z = (np.asarray(features) - mean) / np.maximum(std, 1e-6)
    return np.clip(z, -clip, clip) if clip else z


def shifted_stats(mean, std, k=3.0):
    """Stats shifted by k sigma, for the mandatory Phase 2 experiment."""
    return mean + k * std, std


# ---------------- offline generation (same code path as live) ----------------
def simulate_windows(anomaly, duration_s, seed=0, anomaly_after=0.0, drift_cap=None):
    """Run the simulator model in virtual time and return the window feature vectors."""
    from simulator import SensorModel
    model = SensorModel(anomaly, anomaly_after, drift_cap, 300, random.Random(seed))
    ext = WindowFeatureExtractor()
    t0 = 1_700_000_000.0
    windows = []
    for tick in range(int(duration_s)):
        ts = t0 + tick
        windows += ext.push_temperature(ts, model.temperature(tick))
        if tick % 2 == 0:
            windows += ext.push_vibration(ts, model.vibration_rms(tick))
    return [f for _, f in windows]


# ---------------- commands ----------------
def cmd_compute_stats(args):
    feats = np.array(simulate_windows("none", args.duration, seed=args.seed))
    if len(feats) < 10:
        sys.exit("Too few windows. Increase --duration.")
    mean = feats.mean(axis=0)
    std = feats.std(axis=0, ddof=1)
    save_stats(mean, std, args.out)
    print(f"Computed from {len(feats)} Normal windows ({args.duration:.0f} s, seed {args.seed})")
    print(f"{'feature':22}{'mean':>10}{'std':>10}")
    for name, m, s in zip(FEATURE_NAMES, mean, std):
        print(f"{name:22}{m:10.4f}{s:10.4f}")
    print(f"Saved to {args.out}")


def cmd_check(args):
    stats = load_stats() if os.path.exists(STATS_PATH) else None
    head = "  ".join(f"{n[:11]:>11}" for n in FEATURE_NAMES)
    print("Mean RAW feature per mode")
    print(f"{'mode':11}{'windows':>8}  {head}")
    rows = {}
    for mode in ("none", "temp_drift", "vibration", "combined"):
        rows[mode] = np.array(simulate_windows(mode, args.duration, seed=1))
        f = rows[mode]
        print(f"{mode:11}{len(f):8d}  " + "  ".join(f"{v:11.3f}" for v in f.mean(axis=0)))
    if stats is not None:
        print(f"\nMean NORMALISED feature per mode (clipped to +/-{CLIP_Z:g})")
        print(f"{'mode':11}{'':>8}  {head}")
        for mode, f in rows.items():
            z = normalise(f, *stats).mean(axis=0)
            print(f"{mode:11}{'':>8}  " + "  ".join(f"{v:11.2f}" for v in z))
    else:
        print("\n(training_stats.npy not found: run compute-stats first for z-scores)")


def _make_client(client_id):
    import paho.mqtt.client as mqtt
    try:                                    # paho-mqtt >= 2.0
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    except AttributeError:                  # paho-mqtt 1.x
        return mqtt.Client(client_id=client_id)


def cmd_live(args):
    np.set_printoptions(precision=3, suppress=True, linewidth=140)
    stats = load_stats() if os.path.exists(STATS_PATH) else None
    if stats is None:
        print("No training_stats.npy found: printing raw features only.")
    ext = WindowFeatureExtractor()
    base = f"logibridge/trucks/{args.truck_id}/sensors"
    client = _make_client(f"prep-{args.truck_id}")     # client IDs must be unique

    def on_connect(client, userdata, *rest):           # works for paho 1.x and 2.x
        client.subscribe([(f"{base}/temperature", 0), (f"{base}/vibration_rms", 0)])

    def on_message(client, userdata, msg):
        try:
            p = json.loads(msg.payload)
            if msg.topic.endswith("/temperature"):
                out = ext.push_temperature(p["ts"], p["value"])
            elif msg.topic.endswith("/vibration_rms"):
                out = ext.push_vibration(p["ts"], p["value"])
            else:
                return
        except (ValueError, KeyError):
            return
        for end_ts, f in out:
            print(f"window closed (end ts {end_ts:.0f})")
            print("  raw:", f)
            if stats is not None:
                print("  z  :", normalise(f, *stats))

    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(args.host, args.port, keepalive=30)
    except OSError as exc:
        sys.exit(f"Cannot reach MQTT broker at {args.host}:{args.port} ({exc}).\n"
                 f"Is Mosquitto running?  ->  service mosquitto start")
    print(f"Listening on {base}/ (first window after about 40 s; Ctrl-C to stop)")
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        pass
    finally:
        client.disconnect()


def main():
    p = argparse.ArgumentParser(description="LogiEdge preprocessing pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("compute-stats", help="compute normalisation stats from clean Normal data")
    s.add_argument("--duration", type=float, default=600, help="simulated seconds (brief: 10 min)")
    s.add_argument("--seed", type=int, default=42)
    s.add_argument("--out", default=STATS_PATH)
    s.set_defaults(fn=cmd_compute_stats)

    c = sub.add_parser("check", help="print mean features for each anomaly mode")
    c.add_argument("--duration", type=float, default=900)
    c.set_defaults(fn=cmd_check)

    l = sub.add_parser("live", help="extract features from live MQTT streams")
    l.add_argument("--truck-id", default="TRUCK_001")
    l.add_argument("--host", default="localhost")
    l.add_argument("--port", type=int, default=1883)
    l.set_defaults(fn=cmd_live)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
