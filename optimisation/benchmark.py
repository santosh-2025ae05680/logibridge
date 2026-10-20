#!/usr/bin/env python3
"""Task F2: five-metric benchmark of M1 (FP32), M2 (PTQ INT8) and M3 (pruned + PTQ INT8).

Metrics per variant:
  mean latency (ms) and p95 latency (ms): 200 timed runs after 10 warm-up runs (excluded)
  model file size (KB)
  accuracy (%) on the held-out validation windows
  energy per inference (mJ) = P x t, with P = CPU TDP x (this process's share of the CPU)

Each trial is exactly 200 timed runs after 10 warm-ups. Trials of the three variants are
interleaved (the order rotates every trial), and the reported latencies are the median over
--trials trials (default 5), so drift and scheduler noise do not decide close comparisons.
The timed call is set_tensor + invoke + get_tensor on pre-quantised inputs (single thread).
Power: a CPU-time counter has about 10 ms resolution, far too coarse for a 2 ms trial, so the
process's CPU share is measured over a separate sustained loop of --power-seconds per variant.
"""
import argparse
import csv
import gc
import os
import sys
import time

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
import numpy as np
import psutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "data_pipeline"))
sys.path.insert(0, os.path.join(ROOT, "training"))
import preprocessing as prep  # noqa: E402
from tflite_utils import TFLiteClassifier  # noqa: E402

MODELS = os.path.join(ROOT, "training", "models")
VARIANTS = [
    ("M1 FP32", os.path.join(MODELS, "mlp_fp32.tflite")),
    ("M2 PTQ INT8", os.path.join(MODELS, "mlp_int8.tflite")),
    ("M3 Pruned+INT8", os.path.join(MODELS, "mlp_pruned_int8.tflite")),
]
WARMUP = 10
RUNS = 200
RESULTS = os.path.join(HERE, "results")


def load_validation():
    data = np.load(os.path.join(ROOT, "training", "dataset.npz"))
    mean, std = prep.load_stats()
    X = prep.normalise(data["X_raw"], mean, std).astype(np.float32)
    val = data["is_val"].astype(bool)
    return X[val], data["y"][val].astype(int)


def tensor_memory_bytes(clf):
    """Sum of all tensor sizes: a proxy for the working memory the interpreter needs."""
    total = 0
    for d in clf.interp.get_tensor_details():
        total += int(np.prod(d["shape"])) * np.dtype(d["dtype"]).itemsize
    return total


def time_trial(clf, inputs):
    """One trial: WARMUP excluded runs, then RUNS timed runs. Returns (total_ms, invoke_ms)."""
    interp, i_idx, o_idx = clf.interp, clf.inp["index"], clf.out["index"]
    n = len(inputs)
    for i in range(WARMUP):
        interp.set_tensor(i_idx, inputs[i % n])
        interp.invoke()
        interp.get_tensor(o_idx)
    total = np.empty(RUNS)
    invoke = np.empty(RUNS)
    pc = time.perf_counter
    for i in range(RUNS):
        x = inputs[i % n]
        t0 = pc()
        interp.set_tensor(i_idx, x)
        t1 = pc()
        interp.invoke()
        t2 = pc()
        interp.get_tensor(o_idx)
        t3 = pc()
        total[i] = (t3 - t0) * 1e3
        invoke[i] = (t2 - t1) * 1e3
    return total, invoke


def sustained_cpu_percent(clf, inputs, seconds):
    """Process CPU % (of one core) over a sustained back-to-back inference loop."""
    interp, i_idx, o_idx = clf.interp, clf.inp["index"], clf.out["index"]
    proc = psutil.Process()
    n = len(inputs)
    proc.cpu_percent(None)                        # prime the counter
    end = time.perf_counter() + seconds
    k = 0
    while time.perf_counter() < end:
        for _ in range(200):
            interp.set_tensor(i_idx, inputs[k % n])
            interp.invoke()
            interp.get_tensor(o_idx)
            k += 1
    return proc.cpu_percent(None)


def pareto_flags(rows, tol=0.10):
    pts = [(r["mean_ms"], r["file_kb"], r["energy_mj"], r["accuracy_pct"]) for r in rows]

    def lower(a, b):                              # a clearly lower than b (beyond the tolerance)
        return a < b * (1 - tol)

    def no_worse_lower(a, b):                     # a not clearly higher than b
        return a <= b * (1 + tol)

    def dominates(a, b):
        no_worse = (no_worse_lower(a[0], b[0]) and a[1] <= b[1]
                    and no_worse_lower(a[2], b[2]) and a[3] >= b[3] - 0.5)
        better = lower(a[0], b[0]) or a[1] < b[1] or lower(a[2], b[2]) or a[3] > b[3] + 0.5
        return no_worse and better

    return [not any(dominates(q, p) for j, q in enumerate(pts) if j != i)
            for i, p in enumerate(pts)]


def pareto_chart(rows, path, tol=0.10):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    front = pareto_flags(rows, tol)
    fig, ax = plt.subplots(figsize=(8, 5))
    colours = ["#4C72B0", "#55A868", "#C44E52"]
    for r, on_front, col in zip(rows, front, colours):
        ax.errorbar(r["mean_ms"], r["file_kb"], xerr=[[0], [max(r["p95_ms"] - r["mean_ms"], 0)]],
                    fmt="o", ms=11, color=col, mfc=col if on_front else "white", mew=2,
                    capsize=4, zorder=3)
        label = (f"{r['variant']}\n{r['accuracy_pct']:.1f}% acc, "
                 f"{r['energy_mj'] * 1000:.2f} uJ" + ("" if on_front else "\n(dominated)"))
        ax.annotate(label, (r["mean_ms"], r["file_kb"]), textcoords="offset points",
                    xytext=(10, 8), fontsize=9)
    fr = sorted((r for r, f in zip(rows, front) if f), key=lambda r: r["mean_ms"])
    if len(fr) > 1:
        ax.plot([r["mean_ms"] for r in fr], [r["file_kb"] for r in fr], "--", color="gray",
                lw=1, zorder=1, label="Pareto front")
        ax.legend(loc="upper right")
    ax.set_xlabel("Mean inference latency (ms); bar extends to p95")
    ax.set_ylabel("Model file size (KB)")
    ax.set_title("Latency vs size (accuracy and energy annotated)\n"
                 "filled = Pareto-optimal (latency/energy within the tie tolerance count as equal)")
    ax.grid(True, alpha=0.3)
    ax.set_xlim(0, max(r['p95_ms'] for r in rows) * 1.9)   # start at zero: tiny differences stay tiny
    ax.margins(y=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=200)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--tdp-w", type=float, default=45.0,
                   help="TDP of this machine's CPU in watts (check your CPU's spec sheet)")
    p.add_argument("--trials", type=int, default=5)
    p.add_argument("--power-seconds", type=float, default=3.0,
                   help="length of the sustained loop used to measure CPU share")
    p.add_argument("--tie-tol", type=float, default=0.10,
                   help="relative latency/energy difference treated as a tie in the Pareto test")
    args = p.parse_args()

    X, y = load_validation()
    ncpu = psutil.cpu_count()
    print(f"validation windows: {len(y)}; logical CPUs: {ncpu}; TDP assumption: {args.tdp_w:g} W; "
          f"{args.trials} trials x {RUNS} runs (+{WARMUP} warm-up each)\n")

    clfs, inputs_by, acc_by, crit_by = {}, {}, {}, {}
    for name, path in VARIANTS:
        if not os.path.exists(path):
            sys.exit(f"Missing model file: {path}")
        clf = TFLiteClassifier(path, num_threads=1)
        pred = clf.predict(X)
        clfs[name] = clf
        acc_by[name] = 100.0 * np.mean(pred == y)
        crit_by[name] = 100.0 * np.mean(pred[y == 2] == 2)
        inputs_by[name] = [clf._quantise(x.reshape(1, -1)) for x in X]

    names = [n for n, _ in VARIANTS]
    means = {n: [] for n in names}
    p95s = {n: [] for n in names}
    invokes = {n: [] for n in names}
    gc.collect()
    gc.disable()
    for t in range(args.trials):                  # interleaved, order rotated every trial
        for name in names[t % len(names):] + names[:t % len(names)]:
            total, invoke = time_trial(clfs[name], inputs_by[name])
            means[name].append(total.mean())
            p95s[name].append(np.percentile(total, 95))
            invokes[name].append(invoke.mean())
    gc.enable()

    rows = []
    for name, path in VARIANTS:
        cpu_pct = sustained_cpu_percent(clfs[name], inputs_by[name], args.power_seconds)
        mean_ms = float(np.median(means[name]))
        share = cpu_pct / 100.0 / ncpu            # this process's share of the whole CPU
        power_w = args.tdp_w * share
        rows.append({
            "variant": name,
            "mean_ms": round(mean_ms, 6),
            "p95_ms": round(float(np.median(p95s[name])), 6),
            "file_kb": round(os.path.getsize(path) / 1024, 2),
            "accuracy_pct": round(acc_by[name], 2),
            "energy_mj": round(power_w * mean_ms, 7),            # W x ms = mJ
            "critical_recall_pct": round(crit_by[name], 2),
            "invoke_mean_ms": round(float(np.median(invokes[name])), 6),
            "mean_ms_min": round(float(min(means[name])), 6),
            "mean_ms_max": round(float(max(means[name])), 6),
            "cpu_pct_of_one_core": round(cpu_pct, 1),
            "assumed_power_w": round(power_w, 3),
            "tensor_memory_bytes": tensor_memory_bytes(clfs[name]),
        })

    print(f"{'variant':16}{'mean ms':>10}{'p95 ms':>10}{'size KB':>9}{'acc %':>8}{'energy mJ':>12}"
          f"{'crit rec %':>12}{'invoke ms':>11}   trial spread of mean (ms)")
    for r in rows:
        print(f"{r['variant']:16}{r['mean_ms']:10.5f}{r['p95_ms']:10.5f}{r['file_kb']:9.2f}"
              f"{r['accuracy_pct']:8.2f}{r['energy_mj']:12.6f}{r['critical_recall_pct']:12.2f}"
              f"{r['invoke_mean_ms']:11.5f}   {r['mean_ms_min']:.5f} - {r['mean_ms_max']:.5f}")
    print(f"\nCPU use during timing: "
          + ", ".join(f"{r['variant']} {r['cpu_pct_of_one_core']}% of one core" for r in rows))
    print(f"Assumed power attributed to the process: "
          + ", ".join(f"{r['variant']} {r['assumed_power_w']} W" for r in rows))
    print("Tensor memory (bytes): "
          + ", ".join(f"{r['variant']} {r['tensor_memory_bytes']}" for r in rows))

    os.makedirs(RESULTS, exist_ok=True)
    csv_path = os.path.join(RESULTS, "benchmark_results.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    chart_path = os.path.join(RESULTS, "pareto_chart.png")
    pareto_chart(rows, chart_path, args.tie_tol)
    front = pareto_flags(rows, args.tie_tol)
    print("\nPareto-optimal: " + ", ".join(r["variant"] for r, f in zip(rows, front) if f))
    print(f"Saved {csv_path}\n      {chart_path}")


if __name__ == "__main__":
    main()
