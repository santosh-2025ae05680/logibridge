# scenario_architecture/calc.py
# ---- Assumptions (log these in NOTES.md and edit if you disagree) ----
BYTES_PER_SAMPLE = 4        # float32
SECONDS_PER_DAY  = 86_400
COST_PER_MB      = 0.10     # Rs per MB (M2M SIM)
TRUCKS           = 85
DAYS_PER_MONTH   = 30

DOOR_EVENTS_PER_DAY = 40    # assumption: ~20 open/close cycles
BYTES_PER_DOOR_EVENT = 50   # timestamp + state + truck id

ALERTS_PER_DAY   = 10       # assumption: state changes + heartbeats sent upstream
BYTES_PER_ALERT  = 300      # small JSON: truck_id, class, confidence, timestamp, features
MB = 1e6                    # decimal MB

# ---- Raw data per truck per day ----
temp_samples = 1 * SECONDS_PER_DAY
vib_samples  = 500 * 3 * SECONDS_PER_DAY      # 500 Hz x 3 axes

temp_mb = temp_samples * BYTES_PER_SAMPLE / MB
vib_mb  = vib_samples  * BYTES_PER_SAMPLE / MB
door_mb = DOOR_EVENTS_PER_DAY * BYTES_PER_DOOR_EVENT / MB

raw_mb_day   = temp_mb + vib_mb + door_mb
raw_cost_day = raw_mb_day * COST_PER_MB

# ---- Edge-processed alert volume ----
alert_mb_day   = ALERTS_PER_DAY * BYTES_PER_ALERT / MB
alert_cost_day = alert_mb_day * COST_PER_MB

# ---- Report ----
print(f"Temperature : {temp_mb:10.3f} MB/day")
print(f"Vibration   : {vib_mb:10.3f} MB/day")
print(f"Door events : {door_mb:10.3f} MB/day")
print(f"RAW total   : {raw_mb_day:10.3f} MB/day/truck -> Rs {raw_cost_day:.2f}/day")
print(f"RAW fleet   : Rs {raw_cost_day*TRUCKS*DAYS_PER_MONTH:,.0f}/month ({TRUCKS} trucks)")
print(f"EDGE alerts : {alert_mb_day:10.4f} MB/day/truck -> Rs {alert_cost_day:.4f}/day")
print(f"EDGE fleet  : Rs {alert_cost_day*TRUCKS*DAYS_PER_MONTH:.2f}/month")
print(f"Reduction   : {raw_mb_day/alert_mb_day:,.0f}x less data")
