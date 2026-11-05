"""Windowed, numeric features shared by detector logging and model inference."""
from __future__ import annotations

import math
import statistics

from rules import Member, haversine_m

FEATURE_NAMES = (
    "nearest_distance_ratio",
    "distance_trend_ratio_s",
    "speed_mps",
    "motion_rms",
    "accuracy_m",
    "age_s",
    "window_distance_mean_ratio",
    "window_distance_std_ratio",
    "window_speed_mean_mps",
    "window_speed_max_mps",
    "window_motion_mean_rms",
    "window_motion_max_rms",
    "window_accuracy_mean_m",
    "samples_in_window",
    "window_duration_s",
)


def build_features(
    history: list[dict],
    member: Member,
    distance_m: float | None,
    age_s: float,
    now: float,
    window_s: float = 30.0,
    separation_limit_m: float = 100.0,
) -> dict[str, float]:
    """Build rolling features, expressing distance relative to the effective limit."""
    if not math.isfinite(separation_limit_m) or separation_limit_m <= 0:
        raise ValueError("separation_limit_m must be a positive finite number")

    window = [sample for sample in history if now - sample["ts"] <= window_s]
    if not window:
        window = [{
            "ts": now,
            "lat": member.lat,
            "lon": member.lon,
            "accuracy_m": member.accuracy_m,
            "motion_rms": member.motion_rms,
            "distance_m": distance_m,
            "threshold_m": separation_limit_m,
        }]

    distance_ratios = [
        float(sample["distance_m"]) / float(sample.get("threshold_m", separation_limit_m))
        for sample in window if sample["distance_m"] is not None
    ]
    motions = [float(s["motion_rms"]) for s in window if s["motion_rms"] is not None]
    accuracies = [float(s["accuracy_m"]) for s in window]
    speeds: list[float] = []
    for previous, current in zip(window, window[1:]):
        elapsed = current["ts"] - previous["ts"]
        if elapsed > 0:
            speeds.append(haversine_m(
                previous["lat"], previous["lon"], current["lat"], current["lon"]
            ) / elapsed)

    first_distance_ratio = distance_ratios[0] if distance_ratios else 0.0
    last_distance_ratio = distance_ratios[-1] if distance_ratios else 0.0
    elapsed_window = max(0.0, window[-1]["ts"] - window[0]["ts"])
    trend = (
        (last_distance_ratio - first_distance_ratio) / elapsed_window
        if elapsed_window else 0.0
    )
    motion_mean = statistics.fmean(motions) if motions else -1.0
    motion_max = max(motions, default=-1.0)
    return {
        "nearest_distance_ratio": (
            float(distance_m) / separation_limit_m if distance_m is not None else -1.0
        ),
        "distance_trend_ratio_s": trend,
        "speed_mps": speeds[-1] if speeds else 0.0,
        "motion_rms": float(member.motion_rms) if member.motion_rms is not None else -1.0,
        "accuracy_m": float(member.accuracy_m),
        "age_s": float(age_s),
        "window_distance_mean_ratio": (
            statistics.fmean(distance_ratios) if distance_ratios else -1.0
        ),
        "window_distance_std_ratio": (
            statistics.pstdev(distance_ratios) if len(distance_ratios) > 1 else 0.0
        ),
        "window_speed_mean_mps": statistics.fmean(speeds) if speeds else 0.0,
        "window_speed_max_mps": max(speeds, default=0.0),
        "window_motion_mean_rms": motion_mean,
        "window_motion_max_rms": motion_max,
        "window_accuracy_mean_m": statistics.fmean(accuracies),
        "samples_in_window": float(len(window)),
        "window_duration_s": elapsed_window,
    }
