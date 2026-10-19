#!/usr/bin/env python3
"""Task E3: bandwidth cost per OTA update cycle for three rollout strategies."""
import argparse


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model-kb", type=float, default=280, help="model size (brief: 280 KB)")
    p.add_argument("--trucks", type=int, default=85)
    p.add_argument("--canary", type=int, default=10)
    p.add_argument("--cost-per-mb", type=float, default=0.10)
    p.add_argument("--cycle-weeks", type=float, default=6)
    p.add_argument("--canary-days", type=float, default=3)
    p.add_argument("--health-reports-per-day", type=float, default=4)
    p.add_argument("--health-kb", type=float, default=1.0)
    p.add_argument("--shadow-days", type=float, default=7)
    p.add_argument("--shadow-summary-kb", type=float, default=1.0)
    p.add_argument("--inference-period-s", type=float, default=10)
    p.add_argument("--shadow-record-bytes", type=float, default=100)
    a = p.parse_args()

    mb = a.model_kb / 1000.0                       # decimal units, as the Rs/MB tariff
    n, c = a.trucks, a.canary
    health_mb = c * a.canary_days * a.health_reports_per_day * a.health_kb / 1000.0
    summary_mb = n * a.shadow_days * a.shadow_summary_kb / 1000.0
    per_day = 86400 / a.inference_period_s
    raw_mb = n * a.shadow_days * per_day * a.shadow_record_bytes / 1e6
    cycles = 365 / (7 * a.cycle_weeks)

    # (scenario, MB per cycle, routine cycle?, trucks acting on the unvalidated model)
    rows = [
        ("Full replacement", n * mb, True, n),
        ("Full replacement: bad model, rollback by re-download", 2 * n * mb, False, n),
        ("Canary: success (10, then the other 75)", n * mb + health_mb, True, c),
        ("Canary: bad model caught, rollback to retained model", c * mb + health_mb, False, c),
        ("Canary: bad model caught, rollback by re-download", 2 * c * mb + health_mb, False, c),
        ("Shadow: on-device comparison, daily summary", n * mb + summary_mb, True, 0),
        ("Shadow: upload every shadow output", n * mb + raw_mb, True, 0),
    ]

    print(f"model {a.model_kb:g} KB, {n} trucks, canary {c}, Rs {a.cost_per_mb}/MB, "
          f"cycle {a.cycle_weeks:g} weeks ({cycles:.2f} cycles/year)")
    print(f"telemetry: canary health {health_mb:.3f} MB, shadow summaries {summary_mb:.3f} MB, "
          f"shadow raw upload {raw_mb:.2f} MB\n")
    print(f"{'scenario':55}{'MB/cycle':>10}{'Rs/cycle':>10}{'Rs/year':>9}{'exposed':>9}")
    for name, mbs, routine, exposed in rows:
        year = f"{mbs * a.cost_per_mb * cycles:9.1f}" if routine else f"{'-':>9}"
        print(f"{name:55}{mbs:10.2f}{mbs * a.cost_per_mb:10.3f}{year}{exposed:9d}")


if __name__ == "__main__":
    main()
