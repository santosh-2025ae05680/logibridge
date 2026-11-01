"""Task B2: Arithmetic Intensity and Roofline analysis (Raspberry Pi 5 CPU)."""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ---- Given in the brief ----
FLOPS_PER_INF = 45e6     # 45 MFLOPs per inference
BYTES_PER_INF = 18e6     # 18 MB (weights + activations) per inference
PEAK_FLOPS    = 16e9     # 16 GFLOP/s (NEON SIMD)
PEAK_BW       = 12e9     # 12 GB/s (LPDDR4X)

# ---- Roofline quantities ----
ai         = FLOPS_PER_INF / BYTES_PER_INF        # FLOP/byte
ridge      = PEAK_FLOPS / PEAK_BW                 # FLOP/byte
attainable = min(PEAK_FLOPS, ai * PEAK_BW)        # FLOP/s
t_compute  = FLOPS_PER_INF / PEAK_FLOPS           # s
t_memory   = BYTES_PER_INF / PEAK_BW              # s
t_bound    = max(t_compute, t_memory)             # lower bound on latency
regime     = "compute-bound" if ai > ridge else "memory-bandwidth-bound"

print(f"Arithmetic Intensity : {ai:.2f} FLOP/byte")
print(f"Ridge point          : {ridge:.2f} FLOP/byte")
print(f"Classification       : {regime}")
print(f"Attainable perf      : {attainable/1e9:.2f} GFLOP/s")
print(f"Compute time         : {t_compute*1e3:.3f} ms")
print(f"Memory time          : {t_memory*1e3:.3f} ms")
print(f"Latency lower bound  : {t_bound*1e3:.3f} ms")
print(f"Margin vs 90 s SLA   : {90/t_bound:,.0f}x")

# ---- Illustrative what-if (state your own assumptions in the report) ----
PRUNE_FRACTION = 0.35     # matches M3 (35% pruning); FLOP reduction is approximate
t_pruned = (FLOPS_PER_INF * (1 - PRUNE_FRACTION)) / PEAK_FLOPS
print(f"What-if {PRUNE_FRACTION:.0%} fewer FLOPs : compute time {t_pruned*1e3:.3f} ms")

# ---- Plot ----
x = np.logspace(-2, 3, 400)
y = np.minimum(PEAK_FLOPS, x * PEAK_BW) / 1e9
plt.figure(figsize=(7, 4.5))
plt.loglog(x, y, lw=2, label="Pi 5 CPU roofline")
plt.axvline(ridge, ls="--", c="gray", lw=1)
plt.scatter([ridge], [PEAK_FLOPS / 1e9], c="gray", zorder=3)
plt.annotate(f"ridge = {ridge:.2f}", (ridge, PEAK_FLOPS / 1e9),
             textcoords="offset points", xytext=(-70, -20))
plt.scatter([ai], [attainable / 1e9], c="red", zorder=3, label=f"LogiEdge model (AI={ai:.2f})")
plt.annotate(regime, (ai, attainable / 1e9), textcoords="offset points", xytext=(10, -25))
plt.xlabel("Arithmetic intensity (FLOP/byte)")
plt.ylabel("Attainable performance (GFLOP/s)")
plt.title("Roofline: Raspberry Pi 5 CPU (NEON)")
plt.grid(True, which="both", alpha=0.3)
plt.legend()
plt.tight_layout()
plt.savefig("hardware/roofline.png", dpi=200)
print("Saved hardware/roofline.png")
