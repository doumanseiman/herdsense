"""Edge device: reads GPS + accelerometer, publishes to MQTT, shows alerts."""

from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import statistics
import subprocess
import time

import common as C

# Simulator only: base point (decimal degrees) where simulated phones stand.
# Read from .env; defaults to central Jakarta. Real phones ignore these.
SIM_LAT = float(C.env("SIM_LAT", "-6.1754"))
SIM_LON = float(C.env("SIM_LON", "106.8272"))


# ---------- real sensors (Termux:API) ----------
def _parse_many(text: str) -> list[dict]:
    """termux-sensor prints several JSON objects back to back."""
    dec, i, out = json.JSONDecoder(), 0, []
    while i < len(text):
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text):
            break
        try:
            obj, i = dec.raw_decode(text, i)
        except ValueError:
            break
        out.append(obj)
    return out


def read_motion_rms() -> float | None:
    """Std-dev of acceleration magnitude over ~1.2 s: ~0 standing still, 1-3 walking."""
    try:
        out = subprocess.run(
            ["termux-sensor", "-s", "acc", "-d", "100", "-n", "12"],
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    mags = []
    for obj in _parse_many(out):
        for key, val in obj.items():
            k = key.lower()
            if "acc" in k and not any(x in k for x in ("uncal", "linear", "gravity")):
                v = val.get("values", [])
                if len(v) >= 3:
                    mags.append(math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2))
                break
    return statistics.pstdev(mags) if len(mags) >= 3 else None


def read_gps() -> dict | None:
    """Try real GPS first, fall back to network location."""
    for provider in ("gps", "network"):
        try:
            out = subprocess.run(
                ["termux-location", "-p", provider, "-r", "once"],
                capture_output=True,
                text=True,
                timeout=20,
            ).stdout
            d = json.loads(out)
            return {
                "lat": d["latitude"],
                "lon": d["longitude"],
                "accuracy_m": d.get("accuracy"),
            }
        except (OSError, subprocess.TimeoutExpired, ValueError, KeyError):
            continue
    return None


# ---------- simulator ----------
def sim_reading(t: float, args, rng: random.Random, off: tuple[float, float]) -> dict:
    """Everyone stands around one spot. Scenarios:
    together  stays with the group (walking in place)
    drift     walks away from the spot at --speed after --drift-after seconds
    still     stands motionless (use it on one phone while the others 'drift' away)"""
    since = t - args.drift_after
    d = since * args.speed if args.scenario == "drift" and since > 0 else 0.0
    x = off[0] + d + rng.gauss(0, 2)
    y = off[1] + rng.gauss(0, 2)
    rms = (
        0.1 + abs(rng.gauss(0, 0.05))
        if args.scenario == "still"
        else abs(rng.gauss(1.5, 0.3))
    )
    return {
        # metres -> degrees: 1 deg latitude ~ 111320 m; longitude shrinks by cos(latitude)
        "lat": SIM_LAT + y / 111320,
        "lon": SIM_LON + x / (111320 * math.cos(math.radians(SIM_LAT))),
        "accuracy_m": round(rng.uniform(4, 12), 1),
        "motion_rms": round(rms, 2),
    }


# ---------- main ----------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["termux", "simulator"], default="termux")
    ap.add_argument(
        "--scenario", choices=["together", "drift", "still"], default="together"
    )
    ap.add_argument(
        "--speed",
        type=float,
        default=2.0,
        help="simulator: metres/second when moving away",
    )
    ap.add_argument(
        "--drift-after",
        type=float,
        default=20,
        help="simulator: seconds before leaving",
    )
    args = ap.parse_args()
    interval = float(C.env("SEND_INTERVAL_S", "3"))
    termux = args.source == "termux"

    def on_connect(c, u, flags, rc, props=None):
        c.subscribe(C.T_ALERTS, qos=1)
        print(f"[{C.MEMBER}] connected to {C.HOST}, source={args.source}")

    def on_message(c, u, msg):
        try:
            a = json.loads(msg.payload)
            text, level = str(a["message"]), a.get("level", "info")
        except (ValueError, KeyError):
            return
        print(f"[{C.MEMBER}] ALERT ({level}): {text}")
        if termux and shutil.which("termux-notification"):
            subprocess.Popen(
                [
                    "termux-notification",
                    "--id",
                    "trip-alert",
                    "--title",
                    "Group alert" if level == "warn" else "Group update",
                    "--content",
                    text,
                ]
            )
            if level == "warn" and shutil.which("termux-vibrate"):
                subprocess.Popen(["termux-vibrate", "-d", "600"])

    client = C.make_client("phone", on_connect, on_message)
    C.connect(client)

    rng = random.Random()
    fixed = random.Random(C.MEMBER)
    off = (fixed.uniform(-5, 5), fixed.uniform(-5, 5))
    start, seq = time.time(), 0
    while True:
        loop_start = time.time()
        reading = (
            sim_reading(loop_start - start, args, rng, off)
            if not termux
            else read_gps()
        )
        if reading is None:
            print(f"[{C.MEMBER}] no GPS fix, skipping")
        else:
            if termux:
                reading["motion_rms"] = read_motion_rms()
            payload = {
                "device_id": C.MEMBER,
                "sequence": seq,
                **reading,
                "sent_at_ms": C.now_ms(),
            }
            client.publish(C.t_telemetry(C.MEMBER), json.dumps(payload), qos=0)
            print(
                f"[{C.MEMBER}] #{seq} lat={reading['lat']:.5f} lon={reading['lon']:.5f} "
                f"acc={reading['accuracy_m']} rms={reading['motion_rms']}"
            )
            seq += 1
        time.sleep(max(0.0, interval - (time.time() - loop_start)))


if __name__ == "__main__":
    main()
