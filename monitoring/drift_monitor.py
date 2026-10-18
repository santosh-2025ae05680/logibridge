#!/usr/bin/env python3
"""LogiEdge PSI drift monitor (Task E1).

Commands:
  build-reference   300 clean Normal windows -> monitoring/reference_dist.json
  monitor           rolling PSI over the last 100 inferences, evaluated every 60 s
  offline-check     fast simulated run (no MQTT) comparing the two score definitions

Score: "p_normal" (probability of the Normal class, default) or "max_prob"
(probability of the winning class).
"""
import argparse
import collections
import datetime
import hashlib
import json
import os
import random
import signal
import sys
import threading
import time

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "data_pipeline"))
sys.path.insert(0, os.path.join(ROOT, "inference"))

REF_PATH = os.path.join(ROOT, "monitoring", "reference_dist.json")
MODEL_PATH = os.path.join(ROOT, "inference", "model.tflite")
BIN_EDGES = [0.0, 0.25, 0.50, 0.75, 1.0]      # [0,.25) [.25,.5) [.5,.75) [.75,1.0]
PSI_ALERT = 0.25
PSI_RECOVERED = 0.10
EPS = 1e-4
REF_WINDOWS = 300


def bin_proportions(scores):
    idx = np.digitize(np.asarray(scores, dtype=float), BIN_EDGES[1:-1])
    counts = np.bincount(idx, minlength=4)
    return counts, counts / max(int(counts.sum()), 1)


def psi(expected, actual, eps=EPS):
    e = np.clip(np.asarray(expected, dtype=float), eps, None)
    a = np.clip(np.asarray(actual, dtype=float), eps, None)
    return float(np.sum((a - e) * np.log(a / e)))


def pick_score(probs, score):
    probs = np.asarray(probs)
    return probs[:, 0] if score == "p_normal" else probs.max(axis=1)


def level(value):
    return "ALERT" if value > PSI_ALERT else ("watch" if value >= PSI_RECOVERED else "ok")


def load_model_and_stats(model_path):
    import preprocessing as prep
    from tflite_runner import TFLiteClassifier
    mean, std = prep.load_stats()
    return prep, TFLiteClassifier(model_path), mean, std


def clean_reference_probs(prep, model, mean, std, seed, n=REF_WINDOWS):
    feats = prep.simulate_windows("none", 38 + 10 * n, seed=seed)[:n]
    if len(feats) < n:
        sys.exit(f"Only {len(feats)} clean windows generated, need {n}")
    z = prep.normalise(np.array(feats), mean, std).astype(np.float32)
    return model.predict_proba(z)


# ---------------------------------------------------------------- build-reference
def cmd_build_reference(args):
    prep, model, mean, std = load_model_and_stats(args.model)
    scores = pick_score(clean_reference_probs(prep, model, mean, std, args.seed), args.score)
    counts, props = bin_proportions(scores)
    with open(args.model, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()[:8]
    ref = {
        "score": args.score, "bin_edges": BIN_EDGES, "n": int(len(scores)),
        "counts": [int(c) for c in counts],
        "proportions": [round(float(p), 6) for p in props],
        "model": f"{os.path.basename(args.model)}@{sha}", "seed": args.seed,
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(ref, f, indent=2)
    print(f"Reference from {len(scores)} clean Normal windows, score={args.score}")
    print(f"  model      : {ref['model']}")
    print(f"  bin counts : {ref['counts']}   (bins: [0,.25) [.25,.5) [.5,.75) [.75,1.0])")
    print(f"  proportions: {ref['proportions']}")
    print(f"  score min/mean: {scores.min():.3f} / {scores.mean():.3f}")
    print(f"Saved {args.out}")


# ---------------------------------------------------------------- monitor
def cmd_monitor(args):
    import paho.mqtt.client as mqtt
    with open(args.reference) as f:
        ref = json.load(f)
    if ref["score"] != args.score:
        sys.exit(f"Reference was built for score '{ref['score']}' but --score is '{args.score}'")
    expected = ref["proportions"]
    topic = f"logibridge/trucks/{args.truck_id}/inference"
    buf = collections.deque(maxlen=args.window)
    state = {"model": None}
    lock = threading.Lock()

    try:                                    # paho-mqtt >= 2.0
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"drift-{args.truck_id}")
    except AttributeError:                  # paho-mqtt 1.x
        client = mqtt.Client(client_id=f"drift-{args.truck_id}")

    def on_connect(client, userdata, *rest):
        client.subscribe(topic, 0)
        print(f"monitoring {topic}  score={args.score}  window={args.window}  "
              f"every {args.interval:.0f} s", flush=True)

    def on_message(client, userdata, msg):
        try:
            p = json.loads(msg.payload)
            value = float(p["p_normal"] if args.score == "p_normal" else p["confidence"])
        except (ValueError, KeyError, TypeError):
            return
        with lock:
            buf.append(value)
            state["model"] = p.get("model")

    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(args.host, args.port, keepalive=30)
    except OSError as exc:
        sys.exit(f"Cannot reach MQTT broker at {args.host}:{args.port} ({exc})")
    client.loop_start()

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *a: stop.set())
    signal.signal(signal.SIGTERM, lambda *a: stop.set())
    next_tick = time.monotonic() + args.interval
    warned = False
    while not stop.wait(0.5):
        if time.monotonic() < next_tick:
            continue
        next_tick += args.interval
        with lock:
            scores = list(buf)
            model_tag = state["model"]
        now = datetime.datetime.now().strftime("%H:%M:%S")
        if len(scores) < args.min_samples:
            print(f"[{now}] warming up: {len(scores)}/{args.min_samples} inferences", flush=True)
            continue
        if model_tag and ref.get("model") and model_tag != ref["model"] and not warned:
            print(f"[{now}] warning: reference built for {ref['model']}, "
                  f"service runs {model_tag}", flush=True)
            warned = True
        _, props = bin_proportions(scores)
        value = psi(expected, props, args.eps)
        bins = ", ".join(f"{p:.2f}" for p in props)
        print(f"[{now}] PSI={value:.3f}  n={len(scores)}  bins=[{bins}]  {level(value)}", flush=True)
        if value > PSI_ALERT:
            print(f"[LOGIBRIDGE DRIFT ALERT] PSI={value:.3f}", flush=True)
    client.disconnect()
    client.loop_stop()


# ---------------------------------------------------------------- offline-check
def cmd_offline_check(args):
    from simulator import SensorModel
    prep, model, mean, std = load_model_and_stats(args.model)
    ref_probs = clean_reference_probs(prep, model, mean, std, args.seed)
    refs = {s: bin_proportions(pick_score(ref_probs, s))[1] for s in ("p_normal", "max_prob")}

    sim = SensorModel("combined", args.anomaly_after, None, 300,
                      random.Random(args.seed + 1), args.anomaly_until)
    ext = prep.WindowFeatureExtractor()
    t0 = 1_700_000_000.0
    ends, feats = [], []
    for tick in range(int(args.duration)):
        ts = t0 + tick
        out = ext.push_temperature(ts, sim.temperature(tick))
        if tick % 2 == 0:
            out += ext.push_vibration(ts, sim.vibration_rms(tick))
        for end_ts, f in out:
            ends.append(end_ts - t0)
            feats.append(f)
    z = prep.normalise(np.array(feats), mean, std).astype(np.float32)
    probs = model.predict_proba(z)
    ends = np.array(ends)

    print(f"anomaly 'combined' from t={args.anomaly_after:.0f}s to t={args.anomaly_until:.0f}s "
          f"(simulated); PSI every {args.tick_s:.0f} simulated s over the last {args.window} windows\n")
    print(f"{'t (s)':>7}{'windows':>9}{'PSI p_normal':>14}{'PSI max_prob':>14}   status (p_normal)")
    for tick_s in np.arange(args.tick_s, args.duration + 1, args.tick_s):
        upto = int(np.searchsorted(ends, tick_s, side="right"))
        sel = probs[max(0, upto - args.window):upto]
        if len(sel) < args.min_samples:
            print(f"{tick_s:7.0f}{len(sel):9d}   warming up")
            continue
        v = {s: psi(refs[s], bin_proportions(pick_score(sel, s))[1], args.eps) for s in refs}
        print(f"{tick_s:7.0f}{len(sel):9d}{v['p_normal']:14.3f}{v['max_prob']:14.3f}   {level(v['p_normal'])}")


def main():
    p = argparse.ArgumentParser(description="LogiEdge PSI drift monitor")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build-reference", help="clean-window reference distribution")
    b.add_argument("--model", default=MODEL_PATH)
    b.add_argument("--out", default=REF_PATH)
    b.add_argument("--seed", type=int, default=202)
    b.add_argument("--score", choices=["p_normal", "max_prob"], default="p_normal")
    b.set_defaults(fn=cmd_build_reference)

    m = sub.add_parser("monitor", help="rolling PSI on live inference results")
    m.add_argument("--host", default="localhost")
    m.add_argument("--port", type=int, default=1883)
    m.add_argument("--truck-id", default="TRUCK_001")
    m.add_argument("--reference", default=REF_PATH)
    m.add_argument("--score", choices=["p_normal", "max_prob"], default="p_normal")
    m.add_argument("--interval", type=float, default=60, help="seconds between PSI evaluations")
    m.add_argument("--window", type=int, default=100, help="rolling window of inferences")
    m.add_argument("--min-samples", type=int, default=20)
    m.add_argument("--eps", type=float, default=EPS)
    m.set_defaults(fn=cmd_monitor)

    o = sub.add_parser("offline-check", help="fast simulated run, no MQTT")
    o.add_argument("--model", default=MODEL_PATH)
    o.add_argument("--seed", type=int, default=202)
    o.add_argument("--duration", type=float, default=2700)
    o.add_argument("--anomaly-after", type=float, default=600)
    o.add_argument("--anomaly-until", type=float, default=1200)
    o.add_argument("--tick-s", type=float, default=300,
                   help="simulated seconds per PSI tick (300 = 60 s at 5x speed)")
    o.add_argument("--window", type=int, default=100)
    o.add_argument("--min-samples", type=int, default=20)
    o.add_argument("--eps", type=float, default=EPS)
    o.set_defaults(fn=cmd_offline_check)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
