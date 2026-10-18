
## Step 2 assumptions
- float32 = 4 bytes per sample, decimal MB (1e6 bytes)
- 40 door events/day at 50 B each
- 10 alerts/day at 300 B each (edge uplink)
- Vibration at 500 Hz x 3 axes for the bandwidth calc; the simulator (Step 4)
  uses 0.5 Hz RMS values, as specified in task C1
- Detection delay budget: 30 s window + 10 s step = 40 s worst case
- TODO: replace [MEASURED] inference time after benchmarking (Step 9)
- TODO: cite a source for rural 4G RTT

## Step 3 decisions
   - Chosen hardware: Option 1, Raspberry Pi 5 + AI HAT+
   - Dominant vertex: [your choice]
   - Roofline: AI 2.50, ridge 1.33, compute-bound, lower bound 2.81 ms
   - Actual MLP is ~800 params / ~1.5 kFLOPs, far below the 45 MFLOP given in B2
