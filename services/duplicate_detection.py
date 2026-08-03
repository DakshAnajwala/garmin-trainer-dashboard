"""Flags likely-duplicate activities: the same ride recorded twice (head unit
+ phone, or a manual import of a ride Garmin already has).

Scoped down from true multi-channel fusion ("pick the best power/HR/GPS
source per segment") to detection + a one-click resolution using the hide
mechanism that already exists — actually reconciling channels sample-by-
sample is a much larger undertaking than this pass justifies, and simply
letting the athlete pick which copy to keep gets 90% of the value.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

# Two rides starting within this window, of similar duration, are almost
# certainly the same ride recorded twice rather than two genuine separate
# efforts — nobody does two real rides 10 minutes apart.
_START_WINDOW_MIN = 15
_DURATION_TOLERANCE_PCT = 0.15


def _parse(dt: str) -> datetime | None:
    try:
        return datetime.fromisoformat(dt)
    except (TypeError, ValueError):
        return None


def find_duplicates(activities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Returns groups of activity_ids that look like the same ride, newest
    dataset first isn't assumed — caller decides which to keep."""
    dated = [(a, _parse(a.get("start_time_local") or "")) for a in activities]
    dated = [(a, d) for a, d in dated if d is not None]
    dated.sort(key=lambda pair: pair[1])

    groups: list[dict[str, Any]] = []
    used: set[Any] = set()

    for i, (a, a_time) in enumerate(dated):
        if a["activity_id"] in used:
            continue
        group = [a]
        for b, b_time in dated[i + 1 :]:
            if b["activity_id"] in used:
                continue
            gap_min = abs((b_time - a_time).total_seconds()) / 60
            if gap_min > _START_WINDOW_MIN:
                break  # sorted by time, so nothing further can be closer
            a_dur, b_dur = a.get("duration_sec"), b.get("duration_sec")
            if a_dur and b_dur:
                longer, shorter = max(a_dur, b_dur), min(a_dur, b_dur)
                if (longer - shorter) / longer > _DURATION_TOLERANCE_PCT:
                    continue  # started together but very different lengths — probably not the same ride
            group.append(b)

        if len(group) > 1:
            used.update(x["activity_id"] for x in group)
            groups.append(
                {
                    "activity_ids": [x["activity_id"] for x in group],
                    "activities": [
                        {
                            "activity_id": x["activity_id"],
                            "name": x.get("name"),
                            "start_time_local": x.get("start_time_local"),
                            "duration_sec": x.get("duration_sec"),
                            "source": x.get("source", "garmin"),
                        }
                        for x in group
                    ],
                }
            )

    return groups
