"""Simulates a multi-phase group scenario demonstrating movement-aware fusion:
Phase 1 (0-20s):  Bob & Sera walk closely together (~4m). Both moving.
Phase 2 (20-60s): Bob stops dead (RMS ~0.1). Sera drifts away past 50m.
                  Bob becomes WAITING (Tertinggal), Sera becomes SEPARATED (Terpisah).
Phase 3 (60-85s): Sera walks back to Bob. Regroup within hysteresis (<40m) -> TOGETHER (Aman).
Phase 4 (85-125s): Sera drifts away past 50m again, BUT Bob KEEPS MOVING (RMS ~1.5).
                  Both become SEPARATED (Terpisah).
"""
from __future__ import annotations

import json
import math
import random
import sys
import time

import common as C

SIM_LAT = float(C.env("SIM_LAT", "-6.1754"))
SIM_LON = float(C.env("SIM_LON", "106.8272"))
INTERVAL = float(C.env("SEND_INTERVAL_S", "2.5"))


def to_coords(x_m: float, y_m: float) -> tuple[float, float]:
    lat = SIM_LAT + y_m / 111320.0
    lon = SIM_LON + x_m / (111320.0 * math.cos(math.radians(SIM_LAT)))
    return lat, lon


def run_choreography() -> None:
    rng = random.Random(42)
    client = C.make_client("choreography")
    connected = False

    def on_connect(_c, _u, _f, rc, _p=None):
        nonlocal connected
        connected = True

    client.on_connect = on_connect
    C.connect(client)

    print(f"[choreography] Connecting to {C.HOST}:{C.PORT} (GROUP_ID={C.GROUP_ID})...")
    for _ in range(30):
        if connected:
            break
        time.sleep(0.2)

    if not connected:
        print("[choreography] Error: Could not connect to MQTT broker.")
        sys.exit(1)

    print("[choreography] Connected! Starting 4-phase simulation.\n")

    start_time = time.time()
    seq_bob = 0
    seq_sera = 0

    # Initial positions
    bob_x, bob_y = 0.0, 0.0
    sera_x, sera_y = 4.0, 0.0

    sera_speed = 2.5  # m/s

    try:
        while True:
            t = time.time() - start_time

            # Phase definitions
            if t < 20.0:
                phase_name = "Phase 1: Walking closely together"
                bob_moving = True
                sera_moving = True
                bob_x = 0.0
                sera_x = 4.0
                expected = "Both AMAN / TOGETHER"
            elif t < 60.0:
                dt = t - 20.0
                bob_moving = False  # Bob STOPS
                sera_moving = True   # Sera WALKS AWAY
                bob_x = 0.0
                sera_x = 4.0 + min(dt * sera_speed, 65.0)
                if sera_x < 50.0:
                    phase_name = "Phase 2a: Bob stopped, Sera drifting (<50m)"
                    expected = "AI predicts MULAI MENJAUH"
                else:
                    phase_name = "Phase 2b: Bob stopped, Sera separated (>50m)"
                    expected = "Bob = TERTINGGAL (waiting/still), Sera = TERPISAH (moving)"
            elif t < 85.0:
                dt = t - 60.0
                phase_name = "Phase 3: Regrouping (Sera walks back to Bob)"
                bob_moving = False  # Bob waits for her
                sera_moving = True   # Sera returning
                sera_x = max(4.0, 65.0 - dt * sera_speed)
                expected = "Recovering to AMAN / TOGETHER (Hysteresis <40m)"
            elif t < 125.0:
                dt = t - 85.0
                bob_moving = True   # Bob KEEPS MOVING this time!
                sera_moving = True  # Sera drifts away
                bob_x = 0.0
                sera_x = 4.0 + min(dt * sera_speed, 65.0)
                if sera_x < 50.0:
                    phase_name = "Phase 4a: Both moving, Sera drifting (<50m)"
                    expected = "AI predicts MULAI MENJAUH"
                else:
                    phase_name = "Phase 4b: Both moving, Sera separated (>50m)"
                    expected = "BOTH Bob & Sera = TERPISAH (both moving!)"
            else:
                print("\n[choreography] All 4 phases completed! Looping or press Ctrl+C to stop.")
                start_time = time.time()
                continue

            dist = abs(sera_x - bob_x)

            # Generate sensor readings with small jitter
            bob_rms = abs(rng.gauss(1.4, 0.2)) if bob_moving else abs(rng.gauss(0.1, 0.03))
            sera_rms = abs(rng.gauss(1.5, 0.2)) if sera_moving else abs(rng.gauss(0.1, 0.03))

            bob_lat, bob_lon = to_coords(bob_x + rng.gauss(0, 1.0), bob_y + rng.gauss(0, 1.0))
            sera_lat, sera_lon = to_coords(sera_x + rng.gauss(0, 1.0), sera_y + rng.gauss(0, 1.0))

            seq_bob += 1
            seq_sera += 1
            now_ms = C.now_ms()

            bob_msg = {
                "lat": bob_lat,
                "lon": bob_lon,
                "accuracy_m": round(rng.uniform(5.0, 9.0), 1),
                "motion_rms": round(bob_rms, 2),
                "sequence": seq_bob,
                "ts": now_ms,
            }
            sera_msg = {
                "lat": sera_lat,
                "lon": sera_lon,
                "accuracy_m": round(rng.uniform(5.0, 9.0), 1),
                "motion_rms": round(sera_rms, 2),
                "sequence": seq_sera,
                "ts": now_ms,
            }

            client.publish(C.t_telemetry("Bob"), json.dumps(bob_msg), qos=0)
            client.publish(C.t_telemetry("Sera"), json.dumps(sera_msg), qos=0)

            print(
                f"[{t:4.1f}s] {phase_name:<46} | Dist: {dist:4.1f}m | "
                f"Bob:{'moving' if bob_moving else 'STILL '}({bob_rms:.2f}) "
                f"Sera:{'moving' if sera_moving else 'STILL '}({sera_rms:.2f}) -> {expected}"
            )

            time.sleep(INTERVAL)

    except KeyboardInterrupt:
        print("\n[choreography] Stopped.")
        client.disconnect()


if __name__ == "__main__":
    run_choreography()
