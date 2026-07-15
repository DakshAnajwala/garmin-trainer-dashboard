"""Gear distance totals: manual base + auto-summed assigned activities.

Garmin doesn't tag activities with which bike/component was used, so
assignment is a manual per-activity choice (or the default-gear rule below);
only the *totalling* is automatic. The manual base is kept as its own field
rather than folded into the total, so gear logged before assignment existed
(e.g. "this bike already had 3400km on it") stays meaningful and the two
numbers can be shown separately.
"""
from __future__ import annotations

from typing import Any, Optional

from database import local_store


def _activity_distances(activities: list[dict[str, Any]]) -> dict[str, float]:
    return {
        str(a.get("activity_id")): (a.get("distance_m") or 0) / 1000
        for a in activities
        if a.get("activity_id") is not None
    }


def resolve_gear_id(activity: dict[str, Any], assignments: dict[str, str], gear: list[dict[str, Any]]) -> Optional[str]:
    """Explicit per-activity assignment wins; otherwise fall back to a gear
    item marked as the default for this activity type."""
    explicit = assignments.get(str(activity.get("activity_id")))
    if explicit:
        return explicit
    activity_type = activity.get("type")
    for g in gear:
        if activity_type and activity_type in (g.get("default_for_types") or []):
            return g["id"]
    return None


def with_distances(activities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each gear item + manual_distance_km / auto_distance_km / total_distance_km
    and the count of activities feeding the auto total."""
    gear = local_store.list_gear()
    assignments = local_store.gear_assignments()
    distances = _activity_distances(activities)

    auto_km: dict[str, float] = {}
    auto_count: dict[str, int] = {}
    for activity in activities:
        gear_id = resolve_gear_id(activity, assignments, gear)
        if not gear_id:
            continue
        km = distances.get(str(activity.get("activity_id")), 0)
        auto_km[gear_id] = auto_km.get(gear_id, 0) + km
        auto_count[gear_id] = auto_count.get(gear_id, 0) + 1

    out = []
    for g in gear:
        manual = g.get("accumulated_distance_km") or 0
        auto = round(auto_km.get(g["id"], 0), 1)
        out.append(
            {
                **g,
                "manual_distance_km": manual,
                "auto_distance_km": auto,
                "auto_activity_count": auto_count.get(g["id"], 0),
                "total_distance_km": round(manual + auto, 1),
            }
        )
    return out
