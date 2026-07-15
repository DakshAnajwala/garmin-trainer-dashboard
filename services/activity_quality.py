"""Flags activities that look like transfers/soft-pedals rather than training.

These matter beyond tidiness: gear auto-claim sums every assigned ride's
distance, and the PMC counts every ride's load, so a handful of 2-minute
car-park rolls quietly inflate both.

Deliberately **flag, never auto-delete or silently exclude**. Checking the
athlete's real data showed a duration-only rule would wrongly bin genuine
sessions — "Bintan - activations" (14.7min) is a deliberate pre-race
activation, and a 7.8min indoor effort at 38km/h is a real, hard, short
ride. What actually separates junk is short *and slow*: you don't average
14km/h for 8 minutes while training, you do it rolling to a cafe.

Flagged rides still count everywhere until the athlete hides them (hiding
already excludes a ride from lists, calendar, PMC and gear totals), so the
decision stays theirs.
"""
from __future__ import annotations

from typing import Any, Optional

_MAX_JUNK_DURATION_SEC = 12 * 60
_MAX_JUNK_SPEED_KMH = 20.0
_CYCLING_TYPES = {"road_biking", "indoor_cycling", "virtual_ride", "cycling"}


def _avg_speed_kmh(activity: dict[str, Any]) -> Optional[float]:
    duration = activity.get("duration_sec")
    distance = activity.get("distance_m")
    if not duration or not distance:
        return None
    return (distance / duration) * 3.6


def assess(activity: dict[str, Any]) -> dict[str, Any]:
    if activity.get("type") not in _CYCLING_TYPES:
        return {"likely_junk": False, "reason": None}

    duration = activity.get("duration_sec") or 0
    speed = _avg_speed_kmh(activity)
    if duration >= _MAX_JUNK_DURATION_SEC or speed is None or speed >= _MAX_JUNK_SPEED_KMH:
        return {"likely_junk": False, "reason": None}

    return {
        "likely_junk": True,
        "reason": (
            f"{round(duration / 60)}min at {speed:.1f} km/h — short and slow enough to look like a transfer "
            f"or roll-out rather than training. It still counts toward gear mileage and training load until hidden."
        ),
    }
