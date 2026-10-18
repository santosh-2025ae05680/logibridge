
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
   - Dominant vertex: Power
   - Roofline: AI 2.50, ridge 1.33, compute-bound, lower bound 2.81 ms
   - Actual MLP is ~800 params / ~1.5 kFLOPs, far below the 45 MFLOP given in B2

## Step 4 decisions
- Simulator publishes the vibration RMS stream at 0.5 Hz as specified; the raw 500 Hz x 3-axis stream is not simulated (only used in the bandwidth calculation).
- Drift is implemented literally: +0.08 C per reading = 4.8 C/min, ~+72 C after 15 min. Unrealistic vs. the 1 C/min in the scenario; optional --drift-cap flag exists. Handle large feature range by clipping normalised features in preprocessing (Step 5).
- Door events are independent of temperature (the brief doesn't couple them).
- --speed and --anomaly-after added for fast dataset generation and for the E1 drift-injection demo.

## Step 5 decisions (preprocessing, C2/C3)
- Causal 5-sample MA; first window ends at 38 s so no warm-up partial averages are used.
- Window closes on the first sample after its end (+~1 s latency; worst-case detection ~41 s + inference).
- Vibration features come from the 0.5 Hz RMS stream: 15 samples per window, so kurtosis is noisy; MA before peak/kurtosis smooths them (order fixed by the brief).
- Features: temp mean, temp std (ddof=1), temp slope C/min (least squares), vib RMS, vib peak, vib kurtosis (Fisher).
- Normalised features clipped to +/-10 to protect INT8 input resolution (drift gives z-scores in the hundreds).
- training_stats.npy: 10 min Normal, seed 42, shape (2, 6) = [mean; std].
- Door events are logged only; they are not part of the 6-feature vector.
- Fusion (C3): feature-level. Report arguments: data-level fusion is awkward (1 Hz vs 0.5 Hz, different units and noise, bigger model); decision-level fusion cannot see cross-sensor interaction (Warning vs Critical differ by the combination of temperature and vibration) and needs extra models on a 10 W device.
- TODO Step 7: run the 3-sigma shifted-stats experiment (shifted_stats() already implemented).

## Step 6 decisions (dataset + training, D1)
- Dataset generated in virtual time from SensorModel + the live preprocessing code (seeds 101/102/103; normalisation stats used seed 42).
- Windows: Normal 117, Warning 87, Critical 87. Split by time: last 20% per class = validation, 2 windows purged between train and val (windows overlap by 20 s, so a random split would leak).
- Model: 6-32-16-3 MLP, ReLU, softmax; Adam 1e-3, batch 16, 60 epochs; 803 parameters.
- Validation accuracy: [fill in]; Class 2 recall: [fill in]. Near-100% is expected because the simulated classes are trivially separable once features are clipped; kurtosis carries no class information (Gaussian noise).
- Step 8 TODO: define "confidence" for PSI. Max-softmax stays ~1 for every class; P(Normal) separates clean from drifted data. Document the choice.
