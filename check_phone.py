"""Readiness check. Run on every phone before the real code:  python check_phone.py
On a laptop without Termux:  python check_phone.py --skip-sensors
"""
from __future__ import annotations

import shutil
import sys
import threading
import time

import common as C

results: list[tuple[str, bool, str]] = []


def check(label: str, fn) -> None:
    try:
        ok, detail = fn()
    except Exception as e:  # noqa: BLE001 - report any failure, never crash
        ok, detail = False, f"{type(e).__name__}: {e}"
    results.append((label, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {label}: {detail}")


def c_env():
    bad = []
    if C.GROUP_ID.startswith("change-me"):
        bad.append("GROUP_ID not set in .env")
    if C.MEMBER == "member1":
        bad.append("MEMBER_NAME still default")
    return (not bad, "; ".join(bad) or f"member={C.MEMBER}, group={C.GROUP_ID[:10]}...")


def c_commands():
    missing = [c for c in ("termux-sensor", "termux-location", "termux-notification") if not shutil.which(c)]
    return (not missing, f"missing: {', '.join(missing)}" if missing else "termux-api commands found")


def c_accel():
    from phone import read_motion_rms
    v = read_motion_rms()
    return (v is not None, f"motion_rms={v:.3f} (hold still ~0, walk 1-3)" if v is not None
            else "no data - install Termux:API app + 'pkg install termux-api'")


def c_gps():
    from phone import read_gps
    g = read_gps()
    if not g:
        return False, "no fix - grant location permission, try outdoors"
    return True, f"lat={g['lat']:.5f} lon={g['lon']:.5f} accuracy={g['accuracy_m']} m"


def c_mqtt():
    topic = C.topic("selftest", C.MEMBER)
    connected = threading.Event()
    subscribed = threading.Event()
    got = threading.Event()
    failure = []

    def on_connect(client, userdata, flags, reason_code, properties=None):
        connected.set()
        if getattr(reason_code, "is_failure", False):
            failure.append(f"broker rejected connection: {reason_code}")
            return
        client.subscribe(topic)

    def on_subscribe(client, userdata, mid, reason_codes, properties=None):
        if any(getattr(code, "is_failure", False) for code in reason_codes):
            failure.append("broker rejected test subscription")
        else:
            subscribed.set()

    def on_message(client, userdata, message):
        if message.payload == b"ping":
            got.set()

    c = C.make_client("check", on_connect=on_connect, on_message=on_message)
    c.on_subscribe = on_subscribe
    try:
        C.connect(c)
        if not connected.wait(15):
            return False, f"connection timeout via {C.HOST}:{C.PORT}"
        if failure:
            return False, failure[0]
        if not subscribed.wait(10):
            return False, f"subscription timeout via {C.HOST}:{C.PORT}"
        if failure:
            return False, failure[0]
        c.publish(topic, b"ping", qos=1)
        ok = got.wait(10)
        detail = f"round trip via {C.HOST}:{C.PORT}" if ok else f"no echo from {C.HOST}:{C.PORT}"
        return ok, detail
    finally:
        c.disconnect()
        c.loop_stop()


if __name__ == "__main__":
    check("Config (.env)", c_env)
    if "--skip-sensors" not in sys.argv:
        check("Termux:API commands", c_commands)
        check("Accelerometer", c_accel)
        check("GPS fix", c_gps)
    check("MQTT publish/receive", c_mqtt)
    failed = [r[0] for r in results if not r[1]]
    print("\nREADY" if not failed else f"\nNOT READY: {', '.join(failed)}")
    sys.exit(1 if failed else 0)
