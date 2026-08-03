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
    "ride_debriefs",
    "constraints",
    "undo_log",
    # The athlete's actual dated plan: what they intend to do on each day.
    # Real athlete intent (generated then edited, or hand-built), small and
    # painful to redo — unlike the old repeating template it replaces, which
    # was computed on the fly and never stored.
    "planned_workouts",
    # Which rides' power is untrustworthy (bad calibration) and must not feed
    # the power curve / FTP. Athlete judgment that would be genuinely painful
    # to reconstruct — and unlike the Garmin caches it can't be re-derived from
    # source, so it syncs.
    "power_exclusions",
    # Athlete intent around the physiology model and the plan: manual
    # parameter overrides/locks, pinned plan sessions, prescription override
    # log, and race events. All small, all unrecoverable from Garmin.
    # (The *computed* model itself is derived and stays local-only.)
    "model_overrides",
    "plan_pins",
    "prescription_log",
    "race_events",
    # Non-sensitive app config set from the Settings tab (e.g. the intervals.icu
    # athlete ID). Secrets never live here — they stay in the encrypted store
    # (config/secrets.py). Small, and worth carrying between devices.
    "app_config",
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


def get_all_activity_details() -> dict[str, list[dict[str, Any]]]:
    """Every ride we hold samples for — the raw material the measured power
    curve aggregates over. Details are cached lazily (only once a ride has been
    opened), so this is a subset of your history, not all of it."""
    return _load().get("activity_details", {})


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


_UNDO_LOG_MAX = 20


def _push_undo(store: dict[str, Any], collection: str, item: dict[str, Any]) -> None:
    """Records a deleted item so it can be restored — motivated by a real
    incident (see memory: overnight_build_assumptions_5.md) where a gear
    entry was deleted with no way to recover it. Ring buffer capped at
    _UNDO_LOG_MAX; oldest entries fall off rather than growing unbounded."""
    log = store.setdefault("undo_log", [])
    log.append({"id": str(int(time.time() * 1000000)), "collection": collection, "item": item, "deleted_at": time.time()})
    del log[:-_UNDO_LOG_MAX]


def list_undo_log() -> list[dict[str, Any]]:
    return sorted(_load().get("undo_log", []), key=lambda e: e["deleted_at"], reverse=True)


def restore_from_undo(undo_id: str) -> Optional[dict[str, Any]]:
    """Re-inserts a deleted item back into its original collection and
    removes it from the undo log. Returns the restored item, or None if the
    undo_id wasn't found (e.g. already restored, or fell off the ring buffer)."""
    store = _load()
    log = store.get("undo_log", [])
    entry = next((e for e in log if e["id"] == undo_id), None)
    if entry is None:
        return None
    store["undo_log"] = [e for e in log if e["id"] != undo_id]
    store.setdefault(entry["collection"], []).append(entry["item"])
    _save(store)
    return entry["item"]


def delete_workout(workout_id: str) -> None:
    store = _load()
    workouts = store.get("workouts", [])
    removed = next((w for w in workouts if w["id"] == workout_id), None)
    store["workouts"] = [w for w in workouts if w["id"] != workout_id]
    if removed:
        _push_undo(store, "workouts", removed)
    _save(store)


# --- Dated planned workouts (the real, editable plan) ------------------------
#
# Replaces the old repeating template: the calendar used to paint the same
# 7-day pattern onto every week, computed on the fly and impossible to edit.
# Now a planned session is a stored object keyed by its actual date, so the
# calendar starts empty and fills only with what the athlete generated or built.


def get_planned_workouts(start: str, end: str) -> dict[str, Any]:
    """date (ISO) -> planned workout, for every planned day in [start, end]."""
    planned = _load().get("planned_workouts", {})
    return {d: w for d, w in planned.items() if start <= d <= end}


def get_planned_workout(date_str: str) -> Optional[dict[str, Any]]:
    return _load().get("planned_workouts", {}).get(date_str)


def save_planned_workout(date_str: str, workout: dict[str, Any]) -> dict[str, Any]:
    store = _load()
    planned = store.setdefault("planned_workouts", {})
    workout["date"] = date_str
    planned[date_str] = workout
    _save(store)
    return workout


def delete_planned_workout(date_str: str) -> Optional[dict[str, Any]]:
    """Clear a day. Undoable, like every other delete — a mis-clicked plan
    day shouldn't need a second incident to recover from."""
    store = _load()
    planned = store.get("planned_workouts", {})
    removed = planned.pop(date_str, None)
    if removed:
        _push_undo(store, "planned_workouts", {"date": date_str, **removed})
    _save(store)
    return removed


def planned_dates_in_week(monday: str, sunday: str) -> set[str]:
    return set(get_planned_workouts(monday, sunday).keys())


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
    sessions = store.get("strength_sessions", [])
    removed = next((s for s in sessions if s.get("id") == session_id), None)
    store["strength_sessions"] = [s for s in sessions if s.get("id") != session_id]
    if removed:
        _push_undo(store, "strength_sessions", removed)
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
    goals = store.get("goals", [])
    removed = next((g for g in goals if g["id"] == goal_id), None)
    store["goals"] = [g for g in goals if g["id"] != goal_id]
    if removed:
        _push_undo(store, "goals", removed)
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
    items = store.get("gear", [])
    removed = next((g for g in items if g["id"] == gear_id), None)
    store["gear"] = [g for g in items if g["id"] != gear_id]
    if removed:
        _push_undo(store, "gear", removed)
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


def get_constraints() -> dict[str, Any]:
    """Race date + travel/reduced-availability windows the athlete has told
    the app about — small bounded record, Firestore-synced. Solving the
    training block around declared reality rather than planning in a vacuum
    and hoping the week cooperates."""
    return _load().get("constraints", {"race_date": None, "travel_windows": []})


def save_constraints(constraints: dict[str, Any]) -> dict[str, Any]:
    store = _load()
    store["constraints"] = constraints
    _save(store)
    return constraints


def get_ride_debrief(activity_id: str) -> Optional[str]:
    """How the ride felt, in your own words — the subjective half of the
    ride analysis. Small bounded map (activity_id -> text), Firestore-synced
    like gear_assignments above."""
    return _load().get("ride_debriefs", {}).get(str(activity_id))


def save_ride_debrief(activity_id: str, text: str) -> None:
    store = _load()
    debriefs = store.setdefault("ride_debriefs", {})
    if text.strip():
        debriefs[str(activity_id)] = text.strip()
    else:
        debriefs.pop(str(activity_id), None)
    _save(store)


def get_power_exclusions() -> dict[str, Any]:
    """activity_id -> {excluded: bool, reason: str, ranges: [{start_sec, end_sec}]}.

    Records *which* power data to ignore when aggregating the power curve and
    FTP — never a copy of the data itself. The raw samples in activity_details
    stay byte-for-byte untouched, so this is always reversible: clearing an
    exclusion restores the previous curve exactly, because the curve is
    recomputed from those untouched samples every time.
    """
    return _load().get("power_exclusions", {})


def get_power_exclusion(activity_id: str) -> dict[str, Any]:
    entry = get_power_exclusions().get(str(activity_id)) or {}
    return {
        "excluded": bool(entry.get("excluded", False)),
        "reason": entry.get("reason") or "",
        "ranges": entry.get("ranges") or [],
    }


def set_power_exclusion(
    activity_id: str,
    excluded: Optional[bool] = None,
    reason: Optional[str] = None,
    ranges: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Partial update — only the fields passed are changed.

    Ranges survive toggling the whole-ride switch off and on, so a rider who
    brushed out three bad segments doesn't lose that work by flipping the
    ride-level toggle. The entry is dropped entirely once it carries no
    information, keeping this map small enough to sync.
    """
    store = _load()
    exclusions = store.setdefault("power_exclusions", {})
    entry = dict(exclusions.get(str(activity_id)) or {})

    if excluded is not None:
        entry["excluded"] = bool(excluded)
    if reason is not None:
        entry["reason"] = reason.strip()
    if ranges is not None:
        entry["ranges"] = [
            {"start_sec": int(r["start_sec"]), "end_sec": int(r["end_sec"])}
            for r in ranges
            if int(r["end_sec"]) > int(r["start_sec"])
        ]

    if not entry.get("excluded") and not entry.get("ranges") and not entry.get("reason"):
        exclusions.pop(str(activity_id), None)
    else:
        exclusions[str(activity_id)] = entry

    _save(store)
    return get_power_exclusion(activity_id)


# --- Physiology model (F6) ---------------------------------------------------


def get_app_config() -> dict[str, Any]:
    """Non-sensitive settings set from the Settings tab. Secrets never appear
    here — those stay in the encrypted store (config/secrets.py)."""
    return _load().get("app_config", {})


def set_app_config(key: str, value: Any) -> dict[str, Any]:
    store = _load()
    config = store.setdefault("app_config", {})
    if value in (None, ""):
        config.pop(key, None)
    else:
        config[key] = value
    _save(store)
    return config


def get_physiology_model() -> Optional[dict[str, Any]]:
    """Last computed model, with its input snapshot. Derived data — local-only,
    recomputable at will; what syncs is the athlete's *intent* (overrides)."""
    return _load().get("physiology_model")


def save_physiology_model(model: dict[str, Any]) -> None:
    store = _load()
    store["physiology_model"] = model
    _save(store)


def get_model_overrides() -> dict[str, Any]:
    """param name -> {value, locked, reason, set_at}. A locked param survives
    every auto-recompute until explicitly unlocked — the whole point is that
    the athlete knows something the data doesn't (illness, a new meter)."""
    return _load().get("model_overrides", {})


def set_model_override(
    name: str, value: Optional[float], locked: bool, reason: str = ""
) -> dict[str, Any]:
    store = _load()
    overrides = store.setdefault("model_overrides", {})
    if value is None:
        overrides.pop(name, None)
    else:
        overrides[name] = {"value": value, "locked": locked, "reason": reason.strip(), "set_at": time.time()}
    _save(store)
    return overrides.get(name, {})


# --- Plan pins + prescription log (F8 / F2) ----------------------------------


def get_plan_pins() -> dict[str, Any]:
    """ISO date -> {reason}. A pinned session is immovable by reflow."""
    return _load().get("plan_pins", {})


def set_plan_pin(date_str: str, pinned: bool, reason: str = "") -> None:
    store = _load()
    pins = store.setdefault("plan_pins", {})
    if pinned:
        pins[date_str] = {"reason": reason.strip(), "set_at": time.time()}
    else:
        pins.pop(date_str, None)
    _save(store)


def log_prescription_decision(date_str: str, decision: str, reason: str = "") -> None:
    """decision: accepted | overridden. The override log is how the plan learns
    what the athlete actually does with advice."""
    store = _load()
    log = store.setdefault("prescription_log", {})
    log[date_str] = {"decision": decision, "reason": reason.strip(), "logged_at": time.time()}
    _save(store)


def get_prescription_log() -> dict[str, Any]:
    return _load().get("prescription_log", {})


# --- Race events + demand profiles (F1) --------------------------------------


def list_race_events() -> list[dict[str, Any]]:
    """Event metadata only (name, date, mass, conditions choice) — small and
    synced. The route track itself can be thousands of points, which is
    exactly the bulk the Firestore 1MiB cap exists to keep out, so it lives
    local-only under event_routes like activity_details does."""
    return _load().get("race_events", [])


def get_event_route(event_id: str) -> Optional[list[dict[str, Any]]]:
    return _load().get("event_routes", {}).get(event_id)


def save_event_route(event_id: str, points: list[dict[str, Any]]) -> None:
    store = _load()
    store.setdefault("event_routes", {})[event_id] = points
    _save(store)


def save_race_event(event: dict[str, Any]) -> dict[str, Any]:
    store = _load()
    events = store.setdefault("race_events", [])
    events[:] = [e for e in events if e["id"] != event["id"]] + [event]
    _save(store)
    return event


def delete_race_event(event_id: str) -> None:
    store = _load()
    store["race_events"] = [e for e in store.get("race_events", []) if e["id"] != event_id]
    store.get("demand_profiles", {}).pop(event_id, None)
    store.get("event_routes", {}).pop(event_id, None)
    _save(store)


def get_demand_profile(event_id: str) -> Optional[dict[str, Any]]:
    """Derived from the event's route+conditions — local-only, like the
    computed model; the event itself (with its route) is what syncs."""
    return _load().get("demand_profiles", {}).get(event_id)


def save_demand_profile(event_id: str, profile: dict[str, Any]) -> None:
    store = _load()
    store.setdefault("demand_profiles", {})[event_id] = profile
    _save(store)


# --- Ask-your-own-data query cache (F5) ---------------------------------------


def get_cached_query(normalized: str) -> Optional[dict[str, Any]]:
    return _load().get("query_cache", {}).get(normalized)


def cache_query(normalized: str, result: dict[str, Any]) -> None:
    store = _load()
    cache = store.setdefault("query_cache", {})
    cache[normalized] = {**result, "cached_at": time.time()}
    if len(cache) > 100:
        oldest = sorted(cache, key=lambda k: cache[k].get("cached_at", 0))[: len(cache) - 100]
        for k in oldest:
            cache.pop(k, None)
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
