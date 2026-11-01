# Hardware Selection and Justification (Tasks B1, B2)

## 1. Options compared
| Option | Hardware | Price/truck | Power | Within 10 W AI budget | Pilot (85) | Full (265) |
|---|---|---|---|---|---|---|
| 1 | Raspberry Pi 5 (8 GB) + AI HAT+ (Hailo-8L, 13 TOPS) | Rs 15,000 | 7.5 W | Yes (75% of budget) | Rs 12.75 lakh | Rs 39.75 lakh |
| 2 | Jetson Orin Nano Super (67 TOPS) | Rs 45,000 | 15 W | No (150% of budget) | Rs 38.25 lakh | Rs 119.25 lakh |
| 3 | STM32H7 custom MCU + sensor ICs | Rs 3,500 | 0.4 W | Yes (4% of budget) | Rs 2.98 lakh | Rs 9.28 lakh |

Supply-side figures (12 V rail, assuming 90% DC-DC efficiency): Option 1 draws
0.69 A (180 Wh/day), Option 2 draws 1.39 A (360 Wh/day) and Option 3 draws 0.04 A
(9.6 Wh/day).

## 2. Constraint Triangle
Vertices used: Performance, Power, Cost.

- **Option 1 (Pi 5 + Hailo):** Performance is ample, with a full Linux platform
  and a CPU rated at 16 GFLOP/s. Power (7.5 W) fits inside the budget with 2.5 W
  of headroom. Cost is mid-range. It is the most balanced point on the triangle.
- **Option 2 (Jetson):** the highest performance, at the extreme corner of the
  triangle. It breaks the power budget and has the highest cost.
- **Option 3 (STM32H7):** the best power and cost corner. Its compute is adequate
  for a very small model, but it offers a bare-metal or RTOS stack only.

## 3. Dominant constraint vertex: Power
1. Power is the only hard, pass/fail limit in the deployment. The AI node must
   stay within 10 W from the 12 V truck supply through a DC-DC converter.
2. The 90 s latency requirement does not discriminate between the options. The
   Roofline lower bound on inference is 2.8 ms, a margin of about 32,000x, and
   the pipeline's windowing adds at most about 40 s. Every option can meet it.
3. Cost ranks the options that pass the power test but does not eliminate any.
   Cost alone would choose the STM32, which cannot host the required software
   stack (section 4).
4. Power also drives operating risk: heat dissipation in an enclosed cab and
   continuous current draw from the truck supply.

Power therefore removes Option 2. Between Options 1 and 3, which both satisfy
the power budget, the choice is made by Performance (the capability to run the
required stack) and Cost.

## 4. Recommendation: Option 1 (Raspberry Pi 5)
**For:**
- Meets the 10 W budget at 7.5 W and draws only 0.69 A from the 12 V supply.
- A full Linux environment lets the architecture run as designed: local
  Mosquitto broker, Docker container, Ansible deployment and registry-based
  OTA model updates.
- Meets the 90 s SLA with a very large margin (about 2.8 ms inference lower
  bound plus at most 40 s of windowing).
- Costs Rs 12.75 lakh for the 85-truck pilot and Rs 39.75 lakh at 265 trucks,
  one third of the Jetson cost.

**Against Option 2 (Jetson):**
- At 15 W under moderate load it exceeds the 10 W budget by 50%. A lower-power
  mode may exist, but it would throttle the performance the extra cost pays for.
- It costs 3x as much (Rs 38.25 lakh pilot, Rs 119.25 lakh at 265 trucks), for
  67 TOPS that a model of this size cannot use.

**Against Option 3 (STM32H7):**
- It is the cheapest (Rs 2.98 lakh pilot) and the lowest power, and would be a
  valid choice for a firmware-only design.
- It cannot run Docker, a Mosquitto broker or Ansible, which the required
  architecture, container-based OTA and MLOps tasks depend on.
- The premium for Option 1 is Rs 9.78 lakh at pilot scale (Rs 30.48 lakh at 265
  trucks), which buys a maintainable Linux platform that can be updated every
  6 weeks over a rural M2M link.

## 5. Caveats
- The Hailo accelerator is not needed for this model, which runs on the CPU
  (this is why B2 analyses the Pi 5 CPU). Hailo-8L also needs models compiled to
  its own format, not plain TFLite. A Pi 5 without the HAT may be sufficient.
- Automotive conditions: 12 V transients and cab temperatures. Confirm the
  Pi 5's rated ambient range against its datasheet and plan an automotive-grade
  DC-DC converter and enclosure.

## 6. Roofline analysis (Task B2)
| Quantity | Value |
|---|---|
| Arithmetic Intensity (45 MFLOP / 18 MB) | 2.50 FLOP/byte |
| Ridge point (16 GFLOP/s / 12 GB/s) | 1.33 FLOP/byte |
| Classification | Compute-bound (AI > ridge) |
| Attainable performance | 16.00 GFLOP/s |
| Compute time / memory time | 2.81 ms / 1.50 ms |
| Margin vs 90 s SLA | about 32,000x |

The model lies right of the ridge point, on the flat compute roof. Compute time
exceeds memory time, so latency is limited by arithmetic throughput.
**Optimisation:** reduce the work or raise compute throughput. Options are INT8
quantisation (integer SIMD, which also cuts memory traffic about 4x), structured
pruning (35% fewer FLOPs gives about 1.83 ms) or a smaller architecture.
Reducing memory traffic alone would not help, because memory time is already
below compute time. These map directly to variants M2 and M3 in Task F1.

**Note for the report:** the actual MLP (6-32-16-3) has about 800 parameters and
about 1.5 kFLOPs, far below the 45 MFLOP / 18 MB figures given for this
exercise. The B2 analysis uses the brief's numbers; the real model has far more
latency headroom.