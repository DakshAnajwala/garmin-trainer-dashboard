"""All-time personal-best aggregation from accumulated local cache.

CAVEAT (important): these are only accurate from whenever this app started
tracking, plus a light backfill window for HRV/readiness — NOT true Garmin
lifetime history, which would require a much larger historical backfill this
app doesn't attempt. Labelled "since tracking began" in the UI for honesty.
"""
from __future__ import annotations

from typing import Any, Optional

from database import local_store


def _best(entries: dict[str, dict[str, Any]], field: str, want_min: bool) -> Optional[dict[str, Any]]:
    best_date, best_val = None, None
    for date_str, data in entries.items():
        val = (data or {}).get(field)
        if val is None:
            continue
        if best_val is None or (val < best_val if want_min else val > best_val):
            best_val, best_date = val, date_str
    return {"value": best_val, "date": best_date} if best_date else None


def compute_prs() -> dict[str, Any]:
    snapshots = local_store.get_all_snapshots()
    rhr_entries = {d: s.get("resting_heart_rate") for d, s in snapshots.items()}
    vo2_entries = {d: s.get("vo2_max") for d, s in snapshots.items()}

    return {
        "lowest_rhr": _best(rhr_entries, "resting_hr_bpm", want_min=True),
        "highest_vo2max": _best(vo2_entries, "vo2_max_cycling", want_min=False),
        "highest_hrv": _best(local_store.get_all_metric_days("hrv"), "last_night_avg_ms", want_min=False),
        "highest_readiness": _best(local_store.get_all_metric_days("readiness"), "readiness_score", want_min=False),
    }


def pr_markers_by_date(start: str, end: str) -> dict[str, dict[str, Any]]:
    """Per-day markers for the PMC chart's hover tooltip: a new-max manual FTP
    test that date, and a lactate-threshold-HR value that changed from the
    most recently known prior value (both scanned in date order so "new" means
    genuinely new-to-date, not just present)."""
    markers: dict[str, dict[str, Any]] = {}

    running_best_ftp = None
    for test in local_store.get_ftp_history():
        if not (start <= test["date"] <= end):
            if test["date"] < start and (running_best_ftp is None or test["ftp_w"] > running_best_ftp):
                running_best_ftp = test["ftp_w"]
            continue
        if running_best_ftp is None or test["ftp_w"] > running_best_ftp:
            markers.setdefault(test["date"], {})["new_ftp_watts"] = test["ftp_w"]
            running_best_ftp = test["ftp_w"]

    snapshots = local_store.get_all_snapshots()
    last_known_lthr = None
    for date_str in sorted(snapshots):
        lthr = (snapshots[date_str].get("lactate_threshold") or {}).get("threshold_hr_cycling")
        if lthr is None:
            continue
        if start <= date_str <= end and lthr != last_known_lthr and last_known_lthr is not None:
            markers.setdefault(date_str, {})["new_lactate_threshold_hr"] = lthr
        last_known_lthr = lthr

    return markers
