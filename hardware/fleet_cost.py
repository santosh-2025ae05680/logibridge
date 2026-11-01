"""Task B1 support: fleet cost and power budget check for the three options."""
POWER_BUDGET_W = 10.0
SUPPLY_V       = 12.0
DC_DC_EFF      = 0.90      # assumption: DC-DC converter efficiency
PILOT, FULL    = 85, 265

options = {
    "1  Pi 5 + Hailo-8L": (15_000, 7.5),
    "2  Jetson Orin Nano": (45_000, 15.0),
    "3  STM32H7 custom":   (3_500, 0.4),
}

print(f"{'Option':22}{'Rs/unit':>9}{'Pilot(85) lakh':>16}{'Full(265) lakh':>16}"
      f"{'W':>6}{'<=10W':>7}{'I@12V(A)':>10}{'Wh/day':>8}")
for name, (price, watts) in options.items():
    ok = "yes" if watts <= POWER_BUDGET_W else "NO"
    amps = watts / (SUPPLY_V * DC_DC_EFF)
    print(f"{name:22}{price:>9,}{price*PILOT/1e5:>16.3f}{price*FULL/1e5:>16.3f}"
          f"{watts:>6.1f}{ok:>7}{amps:>10.2f}{watts*24:>8.1f}")
