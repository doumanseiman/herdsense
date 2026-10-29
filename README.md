# Group Travel Tracker (IoT, multicommunication + multisensor)

Phones publish GPS + accelerometer data over MQTT. A detector decides who has drifted away from
the group and sends alerts back to every phone (vibration + notification). A web dashboard shows
live status.

```
phones (Termux)  <--MQTT-->  broker  <--MQTT-->  detector.py
                               |
                               +--MQTT(WebSocket)--> dashboard/index.html
```

| Piece | File |
|---|---|
| Edge: sensors, processing, publish, receive alerts | `phone.py` |
| Rules (distance + movement fusion), pure and tested | `rules.py`, `tests/` |
| Detector + alerts | `detector.py` |
| Dashboard | `dashboard/index.html` |
| Per-phone readiness check | `check_phone.py` |

## Setup (every device)
1. Termux + Termux:API from F-Droid, then `pkg install python git termux-api`
2. `git clone <repo> && cd <repo> && pip install -r requirements.txt`
3. `cp .env.example .env` and edit: shared `GROUP_ID` (long, random, share privately), unique `MEMBER_NAME`
4. `python check_phone.py` until it prints READY

## Run
- **Detector (one device):** `python detector.py`
- **Each phone:** `python phone.py` (run `termux-wake-lock` first so Android keeps it alive)
- **Dashboard:** open `dashboard/index.html` in a browser, enter the `GROUP_ID`, Connect
  (or `index.html?group=YOUR_GROUP_ID`; add `&host=...&port=...&user=...&pass=...` for another broker)

## Demo without being together (simulator, any PC)
Lower the limit in `.env` (`SEPARATION_M=30`, `GRACE_S=10`), then:
- **Someone walks away:** two phones `python phone.py --source simulator`, one with `--scenario drift --speed 3`
- **Someone stopped behind:** two phones `--scenario drift --speed 3`, one `--scenario still`

Each simulated phone needs its own `MEMBER_NAME` (`MEMBER_NAME=ayu python phone.py ...`).

## MQTT topics
```
trip/<GROUP_ID>/edge/<member>/telemetry   phone -> broker    {device_id, sequence, lat, lon, accuracy_m, motion_rms, sent_at_ms}
trip/<GROUP_ID>/alerts                    detector -> phones {level, member, message, ts}
trip/<GROUP_ID>/status                    detector -> dashboard (retained)
```

## Detector rules (`rules.py`)
Distance (haversine) is measured to the **nearest groupmate**; movement state comes from accelerometer RMS.

| Condition | Status |
|---|---|
| no data for `STALE_S` or GPS accuracy worse than `MIN_ACCURACY_M` | LOST_SIGNAL |
| within `SEPARATION_M` of a groupmate | TOGETHER |
| far but standing still | STRAGGLER_WAITING (info alert) |
| far and moving, or stopped-and-far longer than `GRACE_S` | SEPARATED (warn alert, repeated every `ALERT_COOLDOWN_S`) |

Coming back needs distance under 80% of the limit (hysteresis), so GPS jitter doesn't flap the status.
Limitation: in a 2-person group both people are flagged when apart.

Tests: `python -m unittest tests.test_rules -v`

## Notes
- The default broker is public: keep `GROUP_ID` long and random, and use simulated tracks for demos.
  For privacy use a broker with login (set `MQTT_USERNAME`/`MQTT_PASSWORD`, `MQTT_TLS=true`, port 8883).
- GPS is only accurate to ~5-20 m. Keep `SEPARATION_M` at least 50 m in real use.
- Plumbing (Termux sensor reading, MQTT structure) follows the course example
  https://github.com/myudak/contoh-project-iot1; the idea, rules and dashboard are original.
