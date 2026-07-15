"""Manual .fit/.gpx/.tcx activity import — the file-upload framework for
the Strava/Wahoo/Zwift "import" feature. Full OAuth live-sync to those
platforms is explicitly out of scope for now (each needs a separate
developer app registration that only the athlete can do) — this covers the
much simpler case of exporting an activity file from any of those platforms
and dragging it in by hand.

Only extracts summary fields (duration, distance, HR, power, elevation) —
matching the same shape client.get_activities() returns — not full
per-sample time series. That keeps imported activities working everywhere
Garmin activities already work (activity list, calendar, PMC tooltip)
without needing a second code path for the segment-selector's per-sample
view, which imported activities simply don't support.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Optional

import fitparse
import gpxpy

_SUPPORTED_EXTENSIONS = {"fit", "gpx", "tcx"}


def is_supported(filename: str) -> bool:
    return filename.rsplit(".", 1)[-1].lower() in _SUPPORTED_EXTENSIONS if "." in filename else False


def parse_activity_file(filename: str, content: bytes) -> dict[str, Any]:
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext == "fit":
        record = _parse_fit(content)
    elif ext == "gpx":
        record = _parse_gpx(content)
    elif ext == "tcx":
        record = _parse_tcx(content)
    else:
        raise ValueError(f"Unsupported file type: .{ext} (supported: .fit, .gpx, .tcx)")
    record["source"] = "imported"
    record.setdefault("name", filename.rsplit(".", 1)[0])
    return record


def _parse_fit(content: bytes) -> dict[str, Any]:
    import io

    fit = fitparse.FitFile(io.BytesIO(content))
    session: dict[str, Any] = {}
    for msg in fit.get_messages("session"):
        session = {f.name: f.value for f in msg}
        break  # first session record has the summary totals
    start_time = session.get("start_time")
    return {
        "name": session.get("sport") and str(session["sport"]).replace("_", " ").title(),
        "type": str(session.get("sport") or "cycling").lower(),
        "start_time_local": _iso(start_time),
        "duration_sec": session.get("total_timer_time"),
        "distance_m": session.get("total_distance"),
        "avg_hr": session.get("avg_heart_rate"),
        "max_hr": session.get("max_heart_rate"),
        "elevation_gain_m": session.get("total_ascent"),
        "avg_power_w": session.get("avg_power"),
        "max_power_w": session.get("max_power"),
        "norm_power_w": session.get("normalized_power"),
        "calories": session.get("total_calories"),
    }


def _parse_gpx(content: bytes) -> dict[str, Any]:
    gpx = gpxpy.parse(content.decode("utf-8", errors="ignore"))
    points = [p for track in gpx.tracks for seg in track.segments for p in seg.points]
    if not points:
        raise ValueError("No track points found in GPX file")
    start = points[0].time
    end = points[-1].time
    duration_sec = (end - start).total_seconds() if start and end else None
    distance_m = gpx.length_2d()
    uphill, _ = gpx.get_uphill_downhill()
    return {
        "name": gpx.tracks[0].name if gpx.tracks else None,
        "type": "cycling",
        "start_time_local": _iso(start),
        "duration_sec": duration_sec,
        "distance_m": distance_m,
        "elevation_gain_m": uphill,
        "avg_hr": None,
        "max_hr": None,
        "avg_power_w": None,
    }


_TCX_NS = {"tcx": "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"}


def _tcx_find_all_text(root, path: str) -> list[str]:
    return [el.text for el in root.findall(path, _TCX_NS) if el.text is not None]


def _parse_tcx(content: bytes) -> dict[str, Any]:
    root = ET.fromstring(content)
    activity = root.find(".//tcx:Activity", _TCX_NS)
    if activity is None:
        raise ValueError("No <Activity> found in TCX file")
    sport = activity.get("Sport", "cycling")
    laps = activity.findall("tcx:Lap", _TCX_NS)
    total_time = sum(float(t) for t in _tcx_find_all_text(activity, "tcx:Lap/tcx:TotalTimeSeconds"))
    total_distance = sum(float(d) for d in _tcx_find_all_text(activity, "tcx:Lap/tcx:DistanceMeters"))
    calories = sum(int(c) for c in _tcx_find_all_text(activity, "tcx:Lap/tcx:Calories"))
    hr_values = [int(h) for h in _tcx_find_all_text(activity, ".//tcx:HeartRateBpm/tcx:Value")]
    start_el = activity.find("tcx:Id", _TCX_NS)
    return {
        "name": sport,
        "type": sport.lower(),
        "start_time_local": start_el.text if start_el is not None else None,
        "duration_sec": total_time or None,
        "distance_m": total_distance or None,
        "avg_hr": round(sum(hr_values) / len(hr_values)) if hr_values else None,
        "max_hr": max(hr_values) if hr_values else None,
        "calories": calories or None,
        "avg_power_w": None,
        "lap_count": len(laps),
    }


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()
