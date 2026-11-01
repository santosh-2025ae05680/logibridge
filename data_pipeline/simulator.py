#!/usr/bin/env python3
"""LogiEdge cold-chain sensor simulator (Task C1).

Publishes three streams to a local Mosquitto broker:
  temperature    1 Hz    N(4.0 C, 0.3);  drift modes add +0.08 C per reading
  vibration_rms  0.5 Hz  N(0.45 g, 0.05); fault modes step to N(1.2 g, 0.15)
  door           events  'OPEN' / 'CLOSE' with timestamp

Example:
  python data_pipeline/simulator.py --anomaly combined --duration 900
"""
import argparse
import json
import random
import signal
import sys
import time

import paho.mqtt.client as mqtt

# ---- Parameters from the brief (Task C1) ----
SETPOINT_C = 4.0
TEMP_SIGMA = 0.3
DRIFT_PER_READING = 0.08          # degrees C added per temperature reading
VIB_NORMAL = (0.45, 0.05)         # mean, std in g
VIB_FAULT = (1.2, 0.15)
TEMP_PERIOD_S = 1.0               # 1 Hz
VIB_EVERY_N_TICKS = 2             # 0.5 Hz

TOPIC_ROOT = "logibridge/trucks"
QOS_TEMP, QOS_VIB, QOS_DOOR, QOS_STATUS = 0, 0, 1, 1


class SensorModel:
    """Generates sensor values. Contains no MQTT code, so it can be reused offline."""

    def __init__(self, anomaly, anomaly_after, drift_cap, door_interval, rng, anomaly_until=0.0):
        self.anomaly = anomaly
        self.anomaly_after = anomaly_after
        self.anomaly_until = anomaly_until      # 0 = the anomaly never ends
        self.drift_cap = drift_cap
        self.door_interval = door_interval
        self.rng = rng
        self.drift_readings = 0
        self.door_open = False
        self.next_door_t = rng.expovariate(1.0 / door_interval)

    def anomaly_active(self, t):
        if self.anomaly == "none" or t < self.anomaly_after:
            return False
        return not self.anomaly_until or t < self.anomaly_until

    def temperature(self, t):
        value = self.rng.gauss(SETPOINT_C, TEMP_SIGMA)
        if self.anomaly_active(t) and self.anomaly in ("temp_drift", "combined"):
            self.drift_readings += 1
            offset = DRIFT_PER_READING * self.drift_readings
            if self.drift_cap is not None:
                offset = min(offset, self.drift_cap)
            value += offset
        return value

    def vibration_rms(self, t):
        if self.anomaly_active(t) and self.anomaly in ("vibration", "combined"):
            mean, std = VIB_FAULT
        else:
            mean, std = VIB_NORMAL
        return max(0.0, self.rng.gauss(mean, std))     # RMS cannot be negative

    def door_event(self, t):
        """Return 'OPEN' or 'CLOSE' if a door event is due at time t, else None."""
        if t < self.next_door_t:
            return None
        self.door_open = not self.door_open
        if self.door_open:
            self.next_door_t = t + self.rng.uniform(15, 90)          # open 15-90 s
        else:
            self.next_door_t = t + self.rng.expovariate(1.0 / self.door_interval)
        return "OPEN" if self.door_open else "CLOSE"


def make_client(truck_id):
    client_id = f"sim-{truck_id}"
    try:                                    # paho-mqtt >= 2.0
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    except AttributeError:                  # paho-mqtt 1.x
        return mqtt.Client(client_id=client_id)


def publish(client, topic, payload, qos, retain=False):
    body = json.dumps(payload, separators=(",", ":"))
    return client.publish(topic, body, qos=qos, retain=retain)


def parse_args():
    p = argparse.ArgumentParser(description="LogiEdge cold-chain sensor simulator")
    p.add_argument("--anomaly", choices=["none", "temp_drift", "vibration", "combined"],
                   default="none", help="anomaly mode (default: none)")
    p.add_argument("--truck-id", default="TRUCK_001")
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=1883)
    p.add_argument("--duration", type=float, default=0,
                   help="simulated seconds to run (0 = until Ctrl-C)")
    p.add_argument("--speed", type=float, default=1.0,
                   help="time acceleration factor (1 = real time)")
    p.add_argument("--anomaly-after", type=float, default=0,
                   help="seconds of normal data before the anomaly starts")
    p.add_argument("--anomaly-until", type=float, default=0,
                   help="simulated second at which the anomaly ends (0 = never)")
    p.add_argument("--drift-cap", type=float, default=None,
                   help="optional cap on drift above setpoint, in C (default: none)")
    p.add_argument("--door-interval", type=float, default=300,
                   help="mean seconds between door openings")
    p.add_argument("--seed", type=int, default=None, help="RNG seed for reproducibility")
    p.add_argument("--quiet", action="store_true", help="do not print each reading")
    args = p.parse_args()
    if args.speed <= 0:
        p.error("--speed must be greater than 0")
    return args


def main():
    args = parse_args()
    model = SensorModel(args.anomaly, args.anomaly_after, args.drift_cap,
                        args.door_interval, random.Random(args.seed), args.anomaly_until)

    base = f"{TOPIC_ROOT}/{args.truck_id}"
    topics = {
        "temperature": f"{base}/sensors/temperature",
        "vibration": f"{base}/sensors/vibration_rms",
        "door": f"{base}/sensors/door",
        "status": f"{base}/status/simulator",
    }

    client = make_client(args.truck_id)
    # Last Will: the broker publishes this if the simulator dies without disconnecting
    client.will_set(topics["status"], json.dumps({"state": "offline"}),
                    qos=QOS_STATUS, retain=True)
    try:
        client.connect(args.host, args.port, keepalive=30)
    except OSError as exc:
        sys.exit(f"Cannot reach MQTT broker at {args.host}:{args.port} ({exc}).\n"
                 f"Is Mosquitto running?  ->  service mosquitto start")
    client.loop_start()

    deadline = time.time() + 5
    while not client.is_connected() and time.time() < deadline:
        time.sleep(0.05)
    if not client.is_connected():
        sys.exit("No CONNACK received from the broker within 5 s.")

    publish(client, topics["status"], {"state": "online"}, QOS_STATUS, retain=True)
    print(f"Simulator running: truck={args.truck_id} anomaly={args.anomaly} "
          f"speed={args.speed}x broker={args.host}:{args.port}")

    stop = {"flag": False}

    def handle_stop(signum, frame):
        stop["flag"] = True

    signal.signal(signal.SIGINT, handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)

    epoch0 = time.time()           # simulated timestamps start at the real start time
    wall0 = time.monotonic()
    counts = {"temperature": 0, "vibration": 0, "door": 0}
    announced = False
    ended = False
    tick = 0

    while not stop["flag"]:
        t = tick * TEMP_PERIOD_S
        if args.duration and t >= args.duration:
            break
        ts = round(epoch0 + t, 3)

        if not announced and model.anomaly_active(t):
            print(f"*** anomaly '{args.anomaly}' started at t={t:.0f}s")
            announced = True
        if announced and not ended and not model.anomaly_active(t):
            print(f"*** anomaly ended at t={t:.0f}s: clean data restored")
            ended = True

        temp = model.temperature(t)
        publish(client, topics["temperature"], {"ts": ts, "value": round(temp, 3)}, QOS_TEMP)
        counts["temperature"] += 1

        vib = None
        if tick % VIB_EVERY_N_TICKS == 0:
            vib = model.vibration_rms(t)
            publish(client, topics["vibration"], {"ts": ts, "value": round(vib, 4)}, QOS_VIB)
            counts["vibration"] += 1

        event = model.door_event(t)
        if event:
            publish(client, topics["door"], {"ts": ts, "state": event}, QOS_DOOR)
            counts["door"] += 1

        if not args.quiet:
            line = f"t={t:6.0f}s  temp={temp:7.3f} C"
            if vib is not None:
                line += f"  vib_rms={vib:.3f} g"
            if event:
                line += f"  door={event}"
            print(line)

        tick += 1
        delay = wall0 + tick * TEMP_PERIOD_S / args.speed - time.monotonic()
        if delay > 0:
            time.sleep(delay)

    info = publish(client, topics["status"], {"state": "offline"}, QOS_STATUS, retain=True)
    info.wait_for_publish(timeout=2)
    client.loop_stop()
    client.disconnect()
    print(f"Stopped. Messages published: {counts}")


if __name__ == "__main__":
    main()
