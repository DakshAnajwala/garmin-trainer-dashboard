"""Local JSON-backed persistence, plus Firestore sync for the small subset of
data that's genuinely irreplaceable.

Single-user, single-machine only for the cache portion. Stores manually-logged
weight (Garmin has no weigh-in data for this account), a durable cache of
fetched Garmin data (daily snapshots + per-day HRV/readiness history records)
so past days never need to be re-fetched, and the current training-block week
(1-4).

Caching rule: entries for dates before today never expire (that data is
final). Today's entry is short-TTL (callers pass max_age_seconds) since it's
still accumulating through the day. This cache is what makes the app not wait
on Garmin every time it's opened — only genuinely new/stale data gets fetched.

Firestore sync (when FIREBASE_CREDENTIALS_PATH is configured): only
_SYNCED_KEYS round-trip through Firestore, so this data follows you across
devices/deploys. Everything else (snapshots, metrics, activity_details,
activity_splits) is a disposable Garmin-derived cache — re-fetchable from
source, deliberately local-disk-only, and excluded to stay well clear of
Firestore's 1MiB-per-document cap (see database/firestore_db.py).
"""
from __future__ import annotations

import json
import time
from datetime import date as date_, timedelta
from pathlib import Path
from typing import Any, Optional

from database import backup, firestore_db

_STORE_PATH = Path(__file__).resolve().parent.parent / "data" / "local_store.json"

_SYNCED_KEYS = {
    "weights",
    "ftp_tests",
    "goals",
    "workouts",
    "strength_sessions",
    "aero_profile",
    "block_week",
    "gear",
    # Both are small, bounded, and represent athlete intent that would be
    # annoying to redo on another device — unlike the bulky Garmin caches.
    "gear_assignments",
    "hidden_activities",
}


def _load_file() -> dict[str, Any]:
    if not _STORE_PATH.exists():
        return {"weights": {}, "snapshots": {}, "metrics": {}}
    with _STORE_PATH.open("r") as f:
        return json.load(f)


def _save_file(store: dict[str, Any]) -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    backup.snapshot_before_write(_STORE_PATH)
    with _STORE_PATH.open("w") as f:
        json.dump(store, f, indent=2, default=str)


def _load() -> dict[str, Any]:
    store = _load_file()
    if firestore_db.available():
        remote = firestore_db.load_main()
        if remote:
            store.update({k: v for k, v in remote.items() if k in _SYNCED_KEYS})
    return store


def _save(store: dict[str, Any]) -> None:
    _save_file(store)
    if firestore_db.available():
        firestore_db.save_main({k: v for k, v in store.items() if k in _SYNCED_KEYS})


def resync_file_to_cloud() -> dict[str, Any]:
    """Push the on-disk file's synced keys up to Firestore, overwriting what's
    there. Needed after a backup restore: _load() lets Firestore win for
    synced keys, so restoring the file alone is invisible to the app — the
    restored values have to be pushed back up to actually take effect."""
    store = _load_file()
    synced = {k: v for k, v in store.items() if k in _SYNCED_KEYS}
    if firestore_db.available():
        firestore_db.save_main(synced)
    return synced


def log_weight(weight_kg: float, for_date: Optional[date_] = None) -> None:
    for_date = for_date or date_.today()
    store = _load()
    store["weights"][for_date.isoformat()] = weight_kg
    _save(store)


def get_weight_history(limit_days: int = 90) -> list[tuple[str, float]]:
    store = _load()
    entries = sorted(store["weights"].items())
    return entries[-limit_days:]


def get_latest_weight() -> Optional[tuple[str, float]]:
    history = get_weight_history(limit_days=1)
    return history[-1] if history else None


def _read_cached(entry: Any, max_age_seconds: Optional[int]) -> Optional[dict[str, Any]]:
    if entry is None:
        return None
    if isinstance(entry, dict) and "fetched_at" in entry and "data" in entry:
        if max_age_seconds is not None and (time.time() - entry["fetched_at"]) > max_age_seconds:
            return None
        return entry["data"]
    return entry  # pre-existing (unwrapped) cache entries from before this format — still valid


def save_snapshot(for_date: date_, snapshot_dict: dict[str, Any]) -> None:
    store = _load()
    store["snapshots"][for_date.isoformat()] = {"fetched_at": time.time(), "data": snapshot_dict}
    _save(store)


def get_snapshot(for_date: date_, max_age_seconds: Optional[int] = None) -> Optional[dict[str, Any]]:
    store = _load()
    return _read_cached(store.get("snapshots", {}).get(for_date.isoformat()), max_age_seconds)


def save_metric_day(metric: str, for_date: date_, data: dict[str, Any]) -> None:
    store = _load()
    store.setdefault("metrics", {}).setdefault(metric, {})[for_date.isoformat()] = {
        "fetched_at": time.time(),
        "data": data,
    }
    _save(store)


def get_metric_day(metric: str, for_date: date_, max_age_seconds: Optional[int] = None) -> Optional[dict[str, Any]]:
    store = _load()
    entry = store.get("metrics", {}).get(metric, {}).get(for_date.isoformat())
    return _read_cached(entry, max_age_seconds)


def get_ftp_history() -> list[dict[str, Any]]:
    """Seeded once from config.athlete_profile.FTP_TEST_HISTORY (the two known
    manual tests), then grows via log_ftp_test — replaces the old hardcoded list."""
    store = _load()
    if "ftp_tests" not in store:
        from config.athlete_profile import FTP_TEST_HISTORY

        store["ftp_tests"] = [dict(t) for t in FTP_TEST_HISTORY]
        _save(store)
    return sorted(store["ftp_tests"], key=lambda t: t["date"])


def log_ftp_test(power_20min_w: float, for_date: Optional[date_] = None) -> dict[str, Any]:
    for_date = for_date or date_.today()
    store = _load()
    tests = store.setdefault("ftp_tests", get_ftp_history())
    entry = {"date": for_date.isoformat(), "power_20min_w": power_20min_w, "ftp_w": round(power_20min_w * 0.95, 1)}
    tests[:] = [t for t in tests if t["date"] != entry["date"]] + [entry]
    _save(store)
    return entry


def get_latest_manual_ftp() -> Optional[dict[str, Any]]:
    history = get_ftp_history()
    return history[-1] if history else None


def get_all_snapshots() -> dict[str, dict[str, Any]]:
    store = _load()
    return {d: _read_cached(e, None) for d, e in store.get("snapshots", {}).items()}


def get_all_metric_days(metric: str) -> dict[str, dict[str, Any]]:
    store = _load()
    return {d: _read_cached(e, None) for d, e in store.get("metrics", {}).get(metric, {}).items()}


def get_activity_splits(activity_id: int) -> Optional[list[dict[str, Any]]]:
    """Splits for a completed activity never change — cached permanently, keyed by id."""
    store = _load()
    entry = store.get("activity_splits", {}).get(str(activity_id))
    return entry if entry is not None else None


def save_activity_splits(activity_id: int, splits: list[dict[str, Any]]) -> None:
    store = _load()
    store.setdefault("activity_splits", {})[str(activity_id)] = splits
    _save(store)


def get_activity_details(activity_id: int) -> Optional[list[dict[str, Any]]]:
    """Raw sample series for a completed activity never changes — cached permanently."""
    store = _load()
    return store.get("activity_details", {}).get(str(activity_id))


def save_activity_details(activity_id: int, samples: list[dict[str, Any]]) -> None:
    store = _load()
    store.setdefault("activity_details", {})[str(activity_id)] = samples
    _save(store)


def list_workouts() -> list[dict[str, Any]]:
    store = _load()
    return store.get("workouts", [])


def get_workout(workout_id: str) -> Optional[dict[str, Any]]:
    return next((w for w in list_workouts() if w["id"] == workout_id), None)


def save_workout(workout: dict[str, Any]) -> dict[str, Any]:
    store = _load()
    workouts = store.setdefault("workouts", [])
    if not workout.get("id"):
        workout["id"] = str(int(time.time() * 1000))
    workouts[:] = [w for w in workouts if w["id"] != workout["id"]] + [workout]
    _save(store)
    return workout


def delete_workout(workout_id: str) -> None:
    store = _load()
    store["workouts"] = [w for w in store.get("workouts", []) if w["id"] != workout_id]
    _save(store)


def log_strength_session(entry: dict[str, Any]) -> dict[str, Any]:
    store = _load()
    sessions = store.setdefault("strength_sessions", [])
    entry.setdefault("id", str(int(time.time() * 1000)))
    sessions.append(entry)
    _save(store)
    return entry


def get_strength_sessions(limit_days: int = 180) -> list[dict[str, Any]]:
    store = _load()
    sessions = store.get("strength_sessions", [])
    cutoff = (date_.today() - timedelta(days=limit_days)).isoformat()
    return sorted((s for s in sessions if s.get("date", "") >= cutoff), key=lambda s: s["date"])


def delete_strength_session(session_id: str) -> None:
    store = _load()
    store["strength_sessions"] = [s for s in store.get("strength_sessions", []) if s.get("id") != session_id]
    _save(store)


def save_goal(goal: dict[str, Any]) -> dict[str, Any]:
    store = _load()
    goals = store.setdefault("goals", [])
    if not goal.get("id"):
        goal["id"] = str(int(time.time() * 1000))
    goals[:] = [g for g in goals if g["id"] != goal["id"]] + [goal]
    _save(store)
    return goal


def list_goals() -> list[dict[str, Any]]:
    store = _load()
    return store.get("goals", [])


def delete_goal(goal_id: str) -> None:
    store = _load()
    store["goals"] = [g for g in store.get("goals", []) if g["id"] != goal_id]
    _save(store)


def save_gear(gear: dict[str, Any]) -> dict[str, Any]:
    store = _load()
    items = store.setdefault("gear", [])
    if not gear.get("id"):
        gear["id"] = str(int(time.time() * 1000))
    items[:] = [g for g in items if g["id"] != gear["id"]] + [gear]
    _save(store)
    return gear


def list_gear() -> list[dict[str, Any]]:
    store = _load()
    return store.get("gear", [])


def delete_gear(gear_id: str) -> None:
    store = _load()
    store["gear"] = [g for g in store.get("gear", []) if g["id"] != gear_id]
    _save(store)


def save_imported_activity(activity: dict[str, Any]) -> dict[str, Any]:
    """Manually-imported .fit/.gpx/.tcx activities, kept separate from the
    Garmin activities_list cache (which gets overwritten wholesale on each
    refetch) so an import survives the next Garmin sync."""
    store = _load()
    items = store.setdefault("imported_activities", [])
    if not activity.get("activity_id"):
        activity["activity_id"] = f"import-{int(time.time() * 1000)}"
    items.append(activity)
    _save(store)
    return activity


def list_imported_activities() -> list[dict[str, Any]]:
    store = _load()
    return store.get("imported_activities", [])


def delete_imported_activity(activity_id: str) -> bool:
    """Imported activities are ours, so this is a real delete (unlike Garmin
    activities, which only support hide_activity below). Returns whether
    anything was actually removed."""
    store = _load()
    items = store.get("imported_activities", [])
    remaining = [a for a in items if str(a.get("activity_id")) != str(activity_id)]
    if len(remaining) == len(items):
        return False
    store["imported_activities"] = remaining
    _save(store)
    return True


def hidden_activity_ids() -> set[str]:
    return {str(i) for i in _load().get("hidden_activities", [])}


def hide_activity(activity_id: str) -> None:
    """Garmin owns its activities — deleting our cached copy just means it
    reappears on the next refetch, so "delete" for a Garmin activity is a
    local hide list instead. Deleting for real has to happen in Garmin
    Connect itself (the MCP client exposes no delete tool)."""
    store = _load()
    hidden = store.setdefault("hidden_activities", [])
    if str(activity_id) not in {str(i) for i in hidden}:
        hidden.append(str(activity_id))
        _save(store)


def unhide_activity(activity_id: str) -> None:
    store = _load()
    store["hidden_activities"] = [i for i in store.get("hidden_activities", []) if str(i) != str(activity_id)]
    _save(store)


def gear_assignments() -> dict[str, str]:
    """activity_id -> gear_id. Small bounded map (one short string pair per
    ride), so it's Firestore-synced unlike the bulky activity caches."""
    return _load().get("gear_assignments", {})


def assign_gear(activity_id: str, gear_id: Optional[str]) -> None:
    store = _load()
    assignments = store.setdefault("gear_assignments", {})
    if gear_id:
        assignments[str(activity_id)] = gear_id
    else:
        assignments.pop(str(activity_id), None)
    _save(store)


def get_aero_profile() -> dict[str, Any]:
    store = _load()
    return store.get("aero_profile", {"position": "relaxed", "frame_type": "neutral"})


def save_aero_profile(profile: dict[str, Any]) -> dict[str, Any]:
    store = _load()
    store["aero_profile"] = profile
    _save(store)
    return profile


def get_block_week() -> int:
    """Which week (1-4) of the 4-week training block we're in. Week 4 = recovery.
    Only the athlete knows their real block start, so this is manually set, not inferred."""
    store = _load()
    return store.get("block_week", 1)


def set_block_week(week: int) -> None:
    if week not in (1, 2, 3, 4):
        raise ValueError("block_week must be 1-4")
    store = _load()
    store["block_week"] = week
    _save(store)
