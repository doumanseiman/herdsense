"""Windowed, numeric features shared by detector logging and model inference."""
from __future__ import annotations

import statistics

from rules import Member, haversine_m

FEATURE_NAMES = (
    "nearest_distance_m",
    "distance_trend_mps",
    "speed_mps",
    "motion_rms",
    "accuracy_m",
    "age_s",
    "window_distance_mean_m",
    "window_distance_std_m",
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
) -> dict[str, float]:
    """Build the same 15-feature rolling window for logging and inference."""
    window = [sample for sample in history if now - sample["ts"] <= window_s]
    if not window:
        window = [{
            "ts": now,
            "lat": member.lat,
            "lon": member.lon,
            "accuracy_m": member.accuracy_m,
            "motion_rms": member.motion_rms,
            "distance_m": distance_m,
        }]

    distances = [float(s["distance_m"]) for s in window if s["distance_m"] is not None]
    motions = [float(s["motion_rms"]) for s in window if s["motion_rms"] is not None]
    accuracies = [float(s["accuracy_m"]) for s in window]
    speeds: list[float] = []
    for previous, current in zip(window, window[1:]):
        elapsed = current["ts"] - previous["ts"]
        if elapsed > 0:
            speeds.append(haversine_m(
                previous["lat"], previous["lon"], current["lat"], current["lon"]
            ) / elapsed)

    first_distance = distances[0] if distances else 0.0
    last_distance = distances[-1] if distances else 0.0
    elapsed_window = max(0.0, window[-1]["ts"] - window[0]["ts"])
    trend = (last_distance - first_distance) / elapsed_window if elapsed_window else 0.0
    motion_mean = statistics.fmean(motions) if motions else -1.0
    motion_max = max(motions, default=-1.0)
    return {
        "nearest_distance_m": float(distance_m) if distance_m is not None else -1.0,
        "distance_trend_mps": trend,
        "speed_mps": speeds[-1] if speeds else 0.0,
        "motion_rms": float(member.motion_rms) if member.motion_rms is not None else -1.0,
        "accuracy_m": float(member.accuracy_m),
        "age_s": float(age_s),
        "window_distance_mean_m": statistics.fmean(distances) if distances else -1.0,
        "window_distance_std_m": statistics.pstdev(distances) if len(distances) > 1 else 0.0,
        "window_speed_mean_mps": statistics.fmean(speeds) if speeds else 0.0,
        "window_speed_max_mps": max(speeds, default=0.0),
        "window_motion_mean_rms": motion_mean,
        "window_motion_max_rms": motion_max,
        "window_accuracy_mean_m": statistics.fmean(accuracies),
        "samples_in_window": float(len(window)),
        "window_duration_s": elapsed_window,
    }
