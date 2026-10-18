# LogiEdge: Constraint Analysis (FreightBridge Cold-Chain Pilot)

## Latency
A refrigeration failure raises cargo temperature by about 1 °C per minute, so a
Critical breach (more than 3 °C off setpoint) arrives roughly three minutes after
the fault, and the SLA allows 90 seconds to alert. On the edge, worst-case
detection is bounded by the pipeline design: a fault must enter a 30 s window
that is evaluated every 10 s (at most about 40 s), plus inference of
[MEASURED: x ms] and under a second to log and publish the alert. That totals
about 41 s, leaving roughly 49 s of margin. A credible source is Opensignal’s India Mobile Network Experience Report (April 2019). It reports measured 4G latency for Indian mobile operators: Airtel 64.2 ms, Jio 62.5 ms, Vodafone 68.4 ms, and Idea 78.7 ms. These are national operator-level measurements, not rural-only measurements. The real problems are unpredictable tail delays, retries and, above all, absent coverage.

## Bandwidth
Per truck per day, temperature (1 Hz x 86,400 s x 4 B) is 0.35 MB, vibration
(500 Hz x 3 axes x 86,400 s x 4 B) is 518.4 MB, and door events (assumed 40
events x 50 B) are 0.002 MB. The total is about 518.7 MB, costing ₹51.87 per
truck per day at ₹0.10/MB, or about ₹1.32 lakh per month for 85 trucks. With
edge processing only alerts are transmitted: assuming 10 alerts per day at
300 B, that is 0.003 MB per day (about ₹0.0003), roughly 170,000 times less
data. Vibration dominates the volume, so analysing it locally gives the largest
saving.

## Connectivity
On the Nashik-Aurangabad route, seven locations lose cellular signal for 35 to
90 minutes. A cloud-only system cannot classify anything during these gaps.
Data is either lost or buffered unanalysed, and a fault occurring mid-gap goes
undetected until coverage returns, long after the 3-minute critical threshold
and the 90 s SLA. This is the kind of undetected failure behind the ₹28 lakh
vaccine spoilage. In LogiEdge, the sensors, broker, inference and alert logging
all run on the truck, so classification continues unaffected. Alerts are
written to a persistent local log and queued, then synchronised in order, with
original timestamps, to the operations centre when the uplink returns. This also
gives a complete chain-of-custody record.

## Privacy
Pharmaceutical clients require proof that cargo condition data cannot be
accessed by unauthorised parties. With on-device inference, raw temperature and
vibration streams never leave the truck: the MQTT broker listens only on the
local interface, and only classified alerts (class, confidence, timestamp,
truck ID) are sent upstream over TLS. This reduces the attack surface to one
device and one encrypted channel, avoids storing raw data with a third-party
cloud, and supports a contractual data-minimisation commitment. It reduces
exposure but does not replace device hardening, access control and log
integrity measures.
