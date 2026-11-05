"""Subscribes to every phone, decides who is separated, publishes status + alerts.

Run on ONE device (laptop or a member's phone):  python detector.py
"""
from __future__ import annotations

import json
import math
import threading
import time
import uuid
from pathlib import Path

import common as C
from ai_model import HerdSenseModel
from data_logger import DetectorCsvLogger
from features import build_features
from ml_labels import APART, MOVING_AWAY, RULE_TO_LABEL, SAFE, STRAGGLER
from rules import (
    LOST,
    SEPARATED,
    TOGETHER,
    WAITING,
    Config,
    Member,
    debounce_status,
    evaluate,
)

MIN_OUTWARD_TREND_RATIO_S = 0.01


def parse(topic: str, payload: bytes):
    """Validate one telemetry message. Returns None for anything malformed."""
    try:
        d = json.loads(payload)
        name = topic.split("/")[3]
        lat, lon, seq = float(d["lat"]), float(d["lon"]), int(d["sequence"])
        acc = d.get("accuracy_m")
        acc = 999.0 if acc is None else float(acc)  # unknown accuracy -> unusable
        rms = d.get("motion_rms")
        rms = None if rms is None else float(rms)
    except (ValueError, KeyError, TypeError, IndexError):
        return None
    if seq < 0 or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    if not all(math.isfinite(value) for value in (acc,)):
        return None
    if acc < 0 or (rms is not None and (not math.isfinite(rms) or rms < 0)):
        return None
    return name, seq, lat, lon, acc, rms


def append_history_sample(
    history: list[dict],
    member: Member,
    distance_m: float | None,
    received_at: float,
    last_seen: float | None,
    threshold_m: float = 100.0,
) -> bool:
    """Append only when this member has delivered a new telemetry sample."""
    if last_seen == member.last_seen:
        return False
    history.append({
        "ts": received_at,
        "lat": member.lat,
        "lon": member.lon,
        "accuracy_m": member.accuracy_m,
        "motion_rms": member.motion_rms,
        "distance_m": distance_m,
        "threshold_m": threshold_m,
    })
    return True


def format_distance(distance_m: float | None) -> str:
    return "unknown distance" if distance_m is None else f"{distance_m:.0f} m"


def debounced_status(rule_status: str, state: dict, required_samples: int) -> str:
    if rule_status == LOST:
        state.clear()
        state["stable"] = LOST
        return LOST
    return debounce_status(rule_status, state, required_samples)


def choose_status(rule_status: str, ai_status: str | None, guard_reason: str | None) -> tuple[str, str]:
    """Return (candidate status, source). The model decides; rules take over when it is unavailable or contradicted."""
    if rule_status == LOST or ai_status is None:
        return rule_status, "RULE_SAFETY"
    if guard_reason is not None:
        return RULE_TO_LABEL.get(rule_status, rule_status), "RULES_GUARD"
    return ai_status, "AI_MODEL"


def prediction_guard_reason(
    prediction: str,
    rule_status: str,
    distance_m: float | None,
    threshold_m: float,
    distance_trend_ratio_s: float,
) -> str | None:
    if prediction not in (MOVING_AWAY, APART, STRAGGLER):
        return None
    if distance_m is None:
        return "no usable distance to a group member"
    if prediction in (APART, STRAGGLER) and rule_status == TOGETHER and distance_m < threshold_m:
        return "rules report TOGETHER within the separation limit"
    if prediction == MOVING_AWAY and (
        distance_m <= threshold_m * 0.8
        or distance_trend_ratio_s <= MIN_OUTWARD_TREND_RATIO_S
    ):
        return "distance is not clearly increasing beyond the hysteresis range"
    return None


def decide_alert(
    cur: str,
    prev: str | None,
    distance_m: float | None,
    now: float,
    last_alert: float,
    cooldown: float,
) -> tuple[str, str] | None:
    distance_text = format_distance(distance_m)
    if cur in (APART, SEPARATED) and (prev not in (APART, SEPARATED) or now - last_alert >= cooldown):
        return "warn", f"is {distance_text} from the group"
    if cur in (MOVING_AWAY,) and prev not in (MOVING_AWAY, APART, SEPARATED):
        return "info", f"is starting to drift away ({distance_text})"
    if cur in (STRAGGLER, WAITING) and prev not in (STRAGGLER, WAITING, APART, SEPARATED):
        return "info", f"stopped {distance_text} from the group"
    if cur in (SAFE, TOGETHER) and prev in (MOVING_AWAY, STRAGGLER, WAITING, APART, SEPARATED):
        return "info", "is back with the group"
    if cur == LOST and prev not in (LOST, None):
        return "info", "no signal"
    return None


def main() -> None:
    cfg = Config(separation_m=float(C.env("SEPARATION_M", "100")),
                 stale_s=float(C.env("STALE_S", "30")),
                 min_accuracy_m=float(C.env("MIN_ACCURACY_M", "60")),
                 grace_s=float(C.env("GRACE_S", "60")),
                 min_separation_m=float(C.env("MIN_SEPARATION_M", "50")),
                 smoothing_samples=int(C.env("SMOOTHING_SAMPLES", "3")))
    cooldown = float(C.env("ALERT_COOLDOWN_S", "30"))
    debounce_samples = int(C.env("DEBOUNCE_SAMPLES", "3"))
    window_s = float(C.env("FEATURE_WINDOW_S", "30"))
    if debounce_samples < 1 or window_s <= 0:
        raise ValueError("Invalid debounce or feature-window configuration")

    model_path = Path(C.env("AI_MODEL_PATH", "models/herdsense_gbc.joblib"))
    if not model_path.is_absolute():
        model_path = C.ROOT / model_path
    ai_model = HerdSenseModel.load(model_path)
    print(f"[detector] Gradient Boosting model loaded: {model_path}")

    session_id = uuid.uuid4().hex
    log_path = Path(C.env("DATA_LOG_PATH", "data/detector_v2.csv"))
    if not log_path.is_absolute():
        log_path = C.ROOT / log_path
    csv_logger = DetectorCsvLogger(log_path, session_id)
    print(f"[detector] logging feature windows to {log_path} (session {session_id[:8]})")

    members: dict[str, Member] = {}
    memory: dict = {}
    stable_statuses: dict[str, dict] = {}
    histories: dict[str, list[dict]] = {}
    last_history_seen: dict[str, float] = {}
    last_seq: dict[str, int] = {}
    last_alert: dict[str, float] = {}
    lock = threading.Lock()

    def on_connect(c, _userdata, _flags, _reason_code, _properties=None):
        c.subscribe(C.topic("edge", "+", "telemetry"))
        print(f"[detector] connected, group={C.GROUP_ID[:12]}..., limit={cfg.separation_m:.0f} m")

    def on_message(_client, _userdata, msg):
        r = parse(msg.topic, msg.payload)
        if not r:
            return
        name, seq, lat, lon, acc, rms = r
        with lock:
            if last_seq.get(name) == seq:  # drop duplicates
                return
            last_seq[name] = seq
            members[name] = Member(name, lat, lon, acc, rms, time.time())

    client = C.make_client("detector", on_connect, on_message)
    C.connect(client)

    def alert(level: str, who: str, text: str) -> None:
        client.publish(C.T_ALERTS, json.dumps(
            {"level": level, "member": who, "message": text, "ts": C.now_ms()}), qos=1)
        print(f"   !! [{level}] {text}")

    while True:
        time.sleep(4)
        now = time.time()
        with lock:
            snap = dict(members)
        if not snap:
            continue
        prevs = {n: stable_statuses.get(n, {}).get("stable") for n in snap}
        res = evaluate(snap, now, cfg, memory)

        status = {"ts": C.now_ms(), "threshold_m": cfg.separation_m, "members": {}}
        for n, r in res.items():
            m = snap[n]
            age_s = round(now - m.last_seen, 1)
            history = histories.setdefault(n, [])
            if append_history_sample(
                history,
                m,
                r["distance_m"],
                now,
                last_history_seen.get(n),
                r["threshold_m"],
            ):
                last_history_seen[n] = m.last_seen
            cutoff = now - window_s
            while history and history[0]["ts"] < cutoff:
                history.pop(0)
            features = build_features(
                history,
                m,
                r["distance_m"],
                age_s,
                now,
                window_s,
                r["threshold_m"],
            )

            rule_status = r["status"]
            if rule_status == LOST:
                ai_status, ai_confidence = None, None
                ai_guard_reason = None
            else:
                ai_status, ai_confidence = ai_model.predict(features)
                ai_guard_reason = prediction_guard_reason(
                    ai_status,
                    rule_status,
                    r["distance_m"],
                    r["threshold_m"],
                    features["distance_trend_ratio_s"],
                )

            candidate_status, status_source = choose_status(rule_status, ai_status, ai_guard_reason)

            ai_reason = None
            if ai_status is not None:
                ai_reason = (
                    f"{features['samples_in_window']:.0f} samples / {window_s:.0f}s; "
                    f"distance={features['nearest_distance_ratio']:.2f}x limit, "
                    f"trend={features['distance_trend_ratio_s']:+.3f}x limit/s, "
                    f"speed={features['speed_mps']:.2f}m/s, "
                    f"motion RMS={features['motion_rms']:.2f}, "
                    f"GPS accuracy={features['accuracy_m']:.0f}m"
                )

            final_status = debounced_status(
                candidate_status, stable_statuses.setdefault(n, {}), debounce_samples
            )
            member_status = {
                **r,
                "rule_status": rule_status,
                "status": final_status,
                "ai_status": ai_status,
                "ai_confidence": None if ai_confidence is None else round(ai_confidence, 3),
                "ai_reason": ai_reason,
                "ai_guarded": ai_guard_reason is not None,
                "ai_guard_reason": ai_guard_reason,
                "status_source": status_source,
                "lat": m.lat,
                "lon": m.lon,
                "accuracy_m": m.accuracy_m,
                "motion_rms": m.motion_rms,
                "age_s": age_s,
                "features": features,
            }
            status["members"][n] = member_status
            csv_logger.log(
                status["ts"], n, features, rule_status, final_status, ai_status, ai_confidence
            )
        client.publish(C.T_STATUS, json.dumps(status), qos=0, retain=True)

        for n, r in status["members"].items():
            cur, prev, d = r["status"], prevs[n], r["distance_m"]
            ev = decide_alert(cur, prev, d, now, last_alert.get(n, 0), cooldown)
            if ev:
                level, msg = ev
                if level == "warn":
                    last_alert[n] = now
                if msg == "no signal":
                    alert(level, n, f"No signal from {n}")
                else:
                    alert(level, n, f"{n} {msg}")

        print(time.strftime("%H:%M:%S"), " | ".join(
            f"{n}:{r['status']} ({r['status_source']}, ai:{r['ai_status'] or 'safety'})"
            f":{'-' if r['distance_m'] is None else str(int(r['distance_m'])) + 'm'}"
            for n, r in status["members"].items()))


if __name__ == "__main__":
    main()
