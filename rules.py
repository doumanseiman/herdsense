"""Pure group-separation logic (no I/O) so it can be unit-tested."""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

TOGETHER, WAITING, SEPARATED, LOST = "TOGETHER", "STRAGGLER_WAITING", "SEPARATED", "LOST_SIGNAL"
INITIALIZING = "INITIALIZING"


@dataclass
class Config:
    separation_m: float = 100.0   # "far from group" distance
    min_separation_m: float = 50.0
    hysteresis: float = 0.8       # must come back inside 80% of the limit to be TOGETHER again
    stale_s: float = 30.0         # no data this long -> LOST_SIGNAL
    min_accuracy_m: float = 60.0  # worse GPS than this -> LOST_SIGNAL
    still_rms: float = 0.35       # accelerometer std-dev below this = standing still
    grace_s: float = 60.0         # stopped + far this long -> SEPARATED
    smoothing_samples: int = 3


@dataclass
class Member:
    name: str
    lat: float
    lon: float
    accuracy_m: float
    motion_rms: float | None
    last_seen: float  # time the detector RECEIVED it (avoids phone clock differences)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Processing A: great-circle distance in metres."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


def is_usable(m: Member, now: float, cfg: Config) -> bool:
    return (now - m.last_seen) <= cfg.stale_s and m.accuracy_m <= cfg.min_accuracy_m


def is_moving(m: Member, cfg: Config) -> bool:
    """Processing B: movement state from accelerometer RMS. Unknown counts as moving."""
    return m.motion_rms is None or m.motion_rms >= cfg.still_rms


def evaluate(members: dict[str, Member], now: float, cfg: Config, memory: dict) -> dict[str, dict]:
    """Algorithm: rule-based fusion of distance (A) + movement state (B).

    Distance is measured to the NEAREST groupmate (not the group average, which one
    far-away person would drag away from everybody else). In a 2-person group both
    people are each other's nearest groupmate, so both get flagged - that is expected.

    LOST_SIGNAL   stale data or poor GPS accuracy
    TOGETHER      within the limit of at least one groupmate
    WAITING       far, but standing still (probably stopped at a shop) - soft warning
    SEPARATED     far AND moving, or stopped-and-far longer than grace_s
    `memory` keeps per-member state between calls (previous status, when they went far).
    """
    usable = {n: m for n, m in members.items() if is_usable(m, now, cfg)}
    out: dict[str, dict] = {}
    for name, m in members.items():
        mem = memory.setdefault(name, {})
        prev = mem.get("status")
        moving = is_moving(m, cfg)
        dist, raw_dist, nearest, threshold = None, None, None, cfg.separation_m
        if name not in usable:
            status = LOST
            mem.pop("over_since", None)
            mem.pop("distance_samples", None)
            mem.pop("distance_peer", None)
        else:
            others = [o for n, o in usable.items() if n != name]
            if not others:
                status = TOGETHER  # nobody to compare with
                mem.pop("distance_samples", None)
                mem.pop("distance_peer", None)
            else:
                nearest_member = min(
                    others, key=lambda o: haversine_m(m.lat, m.lon, o.lat, o.lon)
                )
                raw_dist = haversine_m(m.lat, m.lon, nearest_member.lat, nearest_member.lon)
                nearest = nearest_member.name
                if mem.get("distance_peer") != nearest:
                    mem["distance_samples"] = []
                    mem["distance_peer"] = nearest
                threshold = max(
                    cfg.separation_m,
                    cfg.min_separation_m,
                    math.hypot(m.accuracy_m, nearest_member.accuracy_m),
                )
                samples = mem.setdefault("distance_samples", [])
                samples.append(raw_dist)
                del samples[:-max(1, cfg.smoothing_samples)]
                dist = statistics.median(samples)
                limit = threshold * (cfg.hysteresis if prev in (WAITING, SEPARATED) else 1.0)
                if dist <= limit:
                    status = TOGETHER
                    mem.pop("over_since", None)
                else:
                    since = mem.setdefault("over_since", now)
                    if prev == SEPARATED or moving or now - since >= cfg.grace_s:
                        status = SEPARATED
                    else:
                        status = WAITING
        mem["status"] = status
        out[name] = {"status": status,
                     "distance_m": None if dist is None else round(dist, 1),
                     "raw_distance_m": None if raw_dist is None else round(raw_dist, 1),
                     "threshold_m": round(threshold, 1),
                     "nearest": nearest,
                     "moving": moving}
    return out


def debounce_status(candidate: str, state: dict, required_samples: int) -> str:
    """Only publish a state after it has appeared in consecutive detector cycles."""
    required = max(1, required_samples)
    if candidate == state.get("stable"):
        state.pop("pending", None)
        state.pop("count", None)
        return candidate

    if candidate == state.get("pending"):
        state["count"] += 1
    else:
        state["pending"] = candidate
        state["count"] = 1

    if state["count"] >= required:
        state["stable"] = candidate
        state.pop("pending", None)
        state.pop("count", None)
        return candidate
    return state.get("stable", INITIALIZING)
