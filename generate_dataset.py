"""Generate noisy GPS trips with labels derived from simulator ground-truth states."""
from __future__ import annotations

import argparse
import csv
import math
import random
import uuid
from pathlib import Path

from data_logger import CSV_COLUMNS
from features import build_features
from ml_labels import APART, MOVING_AWAY, SAFE, STRAGGLER
from rules import Config, Member, evaluate

STEP_S = 3.0
SCENARIOS = (
    (SAFE, 12),
    (MOVING_AWAY, 16),
    (STRAGGLER, 15),
    (APART, 20),
)


def coordinates(lat: float, lon: float, east_m: float, north_m: float) -> tuple[float, float]:
    latitude = lat + north_m / 111_111.0
    longitude_scale = 111_111.0 * max(0.1, math.cos(math.radians(lat)))
    return latitude, lon + east_m / longitude_scale


def make_dataset(path: Path, sessions: int, seed: int, cfg: Config) -> int:
    rng = random.Random(seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows_written = 0

    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for session_number in range(sessions):
            session_id = f"sim-{session_number + 1:04d}-{uuid.uuid4().hex[:8]}"
            base_lat = rng.uniform(-45.0, 45.0)
            base_lon = rng.uniform(-150.0, 150.0)
            history: list[dict] = []
            memory: dict = {}
            time_s = 0.0
            safe_offset = rng.uniform(4.0, 24.0)
            drift_rate = rng.uniform(0.45, 0.9)
            separated_rate = rng.uniform(0.35, 1.1)
            scenarios = list(SCENARIOS)
            rng.shuffle(scenarios)

            for label, sample_count in scenarios:
                phase_start = time_s
                phase_offset = safe_offset if label == SAFE else rng.uniform(5.0, 15.0)
                for sample_index in range(sample_count):
                    now = time_s
                    if label == SAFE:
                        true_distance = safe_offset + rng.uniform(-1.5, 1.5)
                        motion = rng.uniform(0.35, 1.4)
                    elif label == MOVING_AWAY:
                        true_distance = phase_offset + drift_rate * (sample_index * STEP_S)
                        motion = rng.uniform(0.65, 2.2)
                    elif label == STRAGGLER:
                        true_distance = rng.uniform(112.0, 165.0)
                        motion = rng.uniform(0.02, 0.22)
                    else:
                        true_distance = 118.0 + separated_rate * (sample_index * STEP_S)
                        motion = rng.uniform(0.75, 2.5)

                    group_accuracy = rng.uniform(4.0, 24.0)
                    member_accuracy = rng.uniform(4.0, 24.0)
                    group_lat, group_lon = coordinates(
                        base_lat,
                        base_lon,
                        rng.gauss(0.0, group_accuracy * 0.45),
                        rng.gauss(0.0, group_accuracy * 0.45),
                    )
                    member_lat, member_lon = coordinates(
                        base_lat,
                        base_lon,
                        true_distance + rng.gauss(0.0, member_accuracy * 0.45),
                        rng.gauss(0.0, member_accuracy * 0.45),
                    )
                    group = Member(
                        "groupmate", group_lat, group_lon, group_accuracy,
                        rng.uniform(0.35, 1.3), now,
                    )
                    member = Member(
                        "simulated-cow", member_lat, member_lon, member_accuracy,
                        motion, now,
                    )
                    decisions = evaluate(
                        {"groupmate": group, "simulated-cow": member}, now, cfg, memory
                    )
                    result = decisions["simulated-cow"]
                    history.append({
                        "ts": now,
                        "lat": member_lat,
                        "lon": member_lon,
                        "accuracy_m": member_accuracy,
                        "motion_rms": motion,
                        "distance_m": result["distance_m"],
                    })
                    history = [sample for sample in history if now - sample["ts"] <= 30.0]
                    features = build_features(
                        history, member, result["distance_m"], 0.0, now, 30.0
                    )
                    rule_status = result["status"]
                    writer.writerow({
                        "session_id": session_id,
                        "timestamp_ms": int((session_number * 10_000 + now) * 1000),
                        "member": "simulated-cow",
                        **features,
                        "rule_status": rule_status,
                        "status": label,
                        "ai_status": "",
                        "ai_confidence": "",
                        "label": label,
                    })
                    rows_written += 1
                    time_s += STEP_S
                if time_s <= phase_start:
                    raise RuntimeError("Simulator failed to advance its clock")

    return rows_written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/synthetic_dataset.csv"))
    parser.add_argument("--sessions", type=int, default=120)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--separation-m", type=float, default=100.0)
    args = parser.parse_args()
    if args.sessions < 6:
        parser.error("--sessions must be at least 6 for session-based train/validation/test splits")
    if args.separation_m <= 0:
        parser.error("--separation-m must be positive")

    row_count = make_dataset(
        args.output,
        args.sessions,
        args.seed,
        Config(separation_m=args.separation_m),
    )
    print(f"Generated {row_count} labeled samples from {args.sessions} sessions: {args.output}")
    print("Labels are simulator ground truth; GPS coordinates include independent measurement noise.")


if __name__ == "__main__":
    main()
