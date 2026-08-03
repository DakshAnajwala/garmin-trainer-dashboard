"""Weekly distance compliance against the team's 300km/week minimum.

This is a separate requirement from Saturday's non-negotiable team ride — a
club-wide volume floor tracked across the whole week, not a single-ride
target. Never surfaced anywhere in the app until now.

Reuses the deduplicate-by-activity_id approach from services/data_query.py's
distance-metric branch: each cached day snapshots the same recent activities,
so summing raw payloads double- or triple-counts a ride. See the "distance in
june" bug fixed in batch 10 for what happens without this.
"""
from __future__ import annotations

from datetime import date as date_, timedelta
from typing import Any

from database import local_store

WEEKLY_DISTANCE_TARGET_KM = 300.0


def _week_bounds(today: date_) -> tuple[date_, date_]:
    monday = today - timedelta(days=today.weekday())
    return monday, monday + timedelta(days=6)


def week_distance_km(today: date_ | None = None) -> dict[str, Any]:
    today = today or date_.today()
    monday, sunday = _week_bounds(today)
    # Count only up to `today`, not to Sunday. "Distance so far" has to be
    # measured over the same window as the pace it's compared against —
    # otherwise asking about a past week mid-week credits rides that hadn't
    # happened yet against a shorter elapsed period and always reads on-pace.
    start, end = monday.isoformat(), min(today, sunday).isoformat()

    by_activity: dict[str, float] = {}
    for metric in ("activities_list_large", "activities_list"):
        for _cached_day, payload in local_store.get_all_metric_days(metric).items():
            for a in (payload or {}).get("items", []):
                d = str(a.get("start_time_local", ""))[:10]
                if not (start <= d <= end):
                    continue
                km = (a.get("distance_m") or 0) / 1000
                if km:
                    by_activity[str(a.get("activity_id"))] = km

    total_km = round(sum(by_activity.values()), 1)
    days_elapsed = (today - monday).days + 1
    days_remaining = 7 - days_elapsed
    remaining_km = round(max(0.0, WEEKLY_DISTANCE_TARGET_KM - total_km), 1)
    # On pace if today's total is at or above a flat linear share of the
    # weekly target — not a fitted trend, since 7 points/week isn't enough
    # to fit anything fancier than "are we behind a straight line."
    expected_by_now_km = WEEKLY_DISTANCE_TARGET_KM * days_elapsed / 7
    on_pace = total_km >= expected_by_now_km

    return {
        "week_start": monday.isoformat(),
        "week_end": sunday.isoformat(),
        # Where counting stopped. Equals week_end only once the week is over —
        # distinct from it so the UI can label the window honestly.
        "counted_through": end,
        "target_km": WEEKLY_DISTANCE_TARGET_KM,
        "distance_km": total_km,
        "remaining_km": remaining_km,
        "rides": len(by_activity),
        "days_remaining": days_remaining,
        "met": total_km >= WEEKLY_DISTANCE_TARGET_KM,
        "on_pace": on_pace,
    }
