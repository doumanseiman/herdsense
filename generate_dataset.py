"""Generate continuous noisy trips with labels derived from simulator ground truth."""
from __future__ import annotations

import argparse
import csv
import math
import random
import uuid
from dataclasses import replace
from pathlib import Path

from data_logger import CSV_COLUMNS
from features import build_features
from ml_labels import APART, MOVING_AWAY, SAFE, STRAGGLER
from rules import Config, Member, evaluate

STEP_S = 3.0
WINDOW_S = 30.0


def coordinates(
    lat: float, lon: float, east_m: float, north_m: float
) -> tuple[float, float]:
    latitude = lat + north_m / 111_111.0
    longitude_scale = 111_111.0 * max(0.1, math.cos(math.radians(lat)))
    return latitude, lon + east_m / longitude_scale


def ground_truth_label(
    distance_m: float, limit_m: float, behavior: str, moving_away: bool
) -> str:
    if distance_m >= limit_m:
        return STRAGGLER if behavior == "still" else APART
    if moving_away and distance_m >= 0.3 * limit_m:
        return MOVING_AWAY
    return SAFE


def sample_separation_limit(
    rng: random.Random, min_limit_m: float, max_limit_m: float
) -> float:
    return rng.uniform(min_limit_m, max_limit_m)


def make_dataset(
    path: Path,
    sessions: int,
    seed: int,
    cfg: Config,
    min_limit_m: float = 50.0,
    max_limit_m: float = 300.0,
) -> int:
    if sessions < 1:
        raise ValueError("sessions must be positive")
    min_limit_m = max(min_limit_m, cfg.min_separation_m)
    if not math.isfinite(min_limit_m) or not math.isfinite(max_limit_m):
        raise ValueError("Distance limits must be finite")
    if min_limit_m <= 0 or max_limit_m < min_limit_m:
        raise ValueError("Distance limits must satisfy 0 < minimum <= maximum")

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
            angle = rng.uniform(0.0, 2 * math.pi)
            limit_m = sample_separation_limit(rng, min_limit_m, max_limit_m)
            session_cfg = replace(cfg, separation_m=limit_m)
            start_distance = rng.uniform(0.08, 0.85) * limit_m
            far_distance = rng.uniform(1.25, 1.65) * limit_m

            moving_out_count = rng.randint(18, 30)
            still_count = rng.randint(9, 15)
            moving_home_count = rng.randint(18, 30)
            safe_count = rng.randint(8, 14)
            phases = (
                ("together", start_distance, start_distance, False, rng.randint(8, 14)),
                ("outward", start_distance, far_distance, True, moving_out_count),
                ("still", far_distance, far_distance, False, still_count),
                ("return", far_distance, start_distance, False, moving_home_count),
                ("together", start_distance, start_distance, False, safe_count),
            )

            history: list[dict] = []
            memory: dict = {}
            time_s = 0.0
            previous_true_distance = start_distance

            for behavior, begin_distance, end_distance, moving_away, count in phases:
                for sample_index in range(count):
                    fraction = sample_index / max(1, count - 1)
                    true_distance = begin_distance + (end_distance - begin_distance) * fraction
                    if behavior == "still":
                        motion = rng.uniform(0.02, 0.25)
                    else:
                        motion = rng.uniform(0.4, 2.5)

                    east = true_distance * math.cos(angle)
                    north = true_distance * math.sin(angle)
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
                        east + rng.gauss(0.0, member_accuracy * 0.45),
                        north + rng.gauss(0.0, member_accuracy * 0.45),
                    )
                    group = Member(
                        "groupmate",
                        group_lat,
                        group_lon,
                        group_accuracy,
                        rng.uniform(0.4, 2.5),
                        time_s,
                    )
                    member = Member(
                        "simulated-cow",
                        member_lat,
                        member_lon,
                        member_accuracy,
                        motion,
                        time_s,
                    )
                    decisions = evaluate(
                        {"groupmate": group, "simulated-cow": member},
                        time_s,
                        session_cfg,
                        memory,
                    )
                    result = decisions["simulated-cow"]
                    history.append({
                        "ts": time_s,
                        "lat": member_lat,
                        "lon": member_lon,
                        "accuracy_m": member_accuracy,
                        "motion_rms": motion,
                        "distance_m": result["distance_m"],
                        "threshold_m": result["threshold_m"],
                    })
                    history = [
                        sample for sample in history
                        if time_s - sample["ts"] <= WINDOW_S
                    ]
                    features = build_features(
                        history,
                        member,
                        result["distance_m"],
                        0.0,
                        time_s,
                        WINDOW_S,
                        result["threshold_m"],
                    )
                    true_label = ground_truth_label(
                        true_distance, limit_m, behavior, moving_away
                    )
                    writer.writerow({
                        "session_id": session_id,
                        "timestamp_ms": int((session_number * 100_000 + time_s) * 1000),
                        "member": "simulated-cow",
                        **features,
                        "rule_status": result["status"],
                        "status": true_label,
                        "ai_status": "",
                        "ai_confidence": "",
                        "label": true_label,
                    })
                    rows_written += 1
                    previous_true_distance = true_distance
                    time_s += STEP_S

            if previous_true_distance != start_distance:
                raise RuntimeError("Simulator path did not end at its starting position")

    return rows_written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/synthetic_dataset.csv"))
    parser.add_argument("--sessions", type=int, default=120)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--min-limit-m", type=float, default=50.0)
    parser.add_argument("--max-limit-m", type=float, default=300.0)
    args = parser.parse_args()
    if args.sessions < 6:
        parser.error("--sessions must be at least 6 for session-based train/validation/test splits")
    if args.min_limit_m <= 0 or args.max_limit_m < args.min_limit_m:
        parser.error("distance limits must satisfy 0 < --min-limit-m <= --max-limit-m")

    row_count = make_dataset(
        args.output,
        args.sessions,
        args.seed,
        Config(min_separation_m=args.min_limit_m),
        args.min_limit_m,
        args.max_limit_m,
    )
    print(f"Generated {row_count} labeled samples from {args.sessions} continuous sessions: {args.output}")
    print(
        f"Configured separation limits vary from {args.min_limit_m:g} to "
        f"{args.max_limit_m:g} m; labels use true simulator positions and GPS readings are noisy."
    )


if __name__ == "__main__":
    main()
