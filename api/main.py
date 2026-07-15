"""FastAPI backend for the React frontend — wraps the existing Garmin MCP
client, local storage, and Claude coaching service behind a REST API.

Run with: uvicorn api.main:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import date as date_, timedelta
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from auth.firebase_auth import verify_token
from config.athlete_profile import POWER_CURVE_SECONDS, POWER_CURVE_UNVERIFIED
from config.settings import settings
from database import local_store
from garmin_mcp.garmin_client import GarminMCPClient
from garmin_mcp.schemas import DailyHealthSnapshot
from services import activity_import
from services import activity_quality
from services import claude_analyzer
from services import coggan
from services import export as export_service
from services import ftp as ftp_service
from services import ftp_test
from services import gear as gear_service
from services import intervals_icu, personal_records, ride_analysis, rider_profile, trajectory
from services.readiness import compute_verdict
from services.training_plan import build_week_plan, todays_prescription, wednesday_workout_steps
from services import zones as zones_service
from services.workout_export import to_zwo

# Every route requires a valid Firebase ID token (verify_token no-ops if
# Firebase isn't configured, so local dev without it still works).
app = FastAPI(title="Garmin Trainer Dashboard API", dependencies=[Depends(verify_token)])

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
    # Browsers hide all but a handful of "simple" response headers on
    # cross-origin requests unless the server explicitly exposes them —
    # without this, /api/export's real filename is invisible to the
    # frontend's fetch() in local dev (production is same-origin, unaffected).
    expose_headers=["Content-Disposition"],
)

# Today's data is still accumulating through the day, so it gets a short TTL;
# every prior day is cached on disk forever (see database/local_store.py).
_TODAY_TTL_SECONDS = 900


def _max_age_for(target_date: date_) -> Optional[int]:
    return _TODAY_TTL_SECONDS if target_date == date_.today() else None


async def _get_snapshot_dict(target_date: date_) -> dict[str, Any]:
    cached = local_store.get_snapshot(target_date, max_age_seconds=_max_age_for(target_date))
    if cached is not None:
        return cached
    async with GarminMCPClient() as client:
        snapshot = await client.get_daily_snapshot(target_date)
    result = snapshot.model_dump(mode="json")
    local_store.save_snapshot(target_date, result)
    return result


def _parse_date(date_str: Optional[str]) -> date_:
    return date_.fromisoformat(date_str) if date_str else date_.today()


def _date_range(start: date_, end: date_) -> list[date_]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


async def _cached_metric_range(
    metric: str, start: date_, end: date_, fetch_fn
) -> list[dict[str, Any]]:
    """Serve a date-keyed metric range from disk where possible; only calls
    Garmin (once, for the whole span) if any non-expired-cache day is missing."""
    dates = _date_range(start, end)
    by_date: dict[str, dict[str, Any]] = {}
    missing = False
    for d in dates:
        cached = local_store.get_metric_day(metric, d, max_age_seconds=_max_age_for(d))
        if cached is not None:
            by_date[d.isoformat()] = cached
        else:
            missing = True

    if missing:
        try:
            fetched = await fetch_fn(start, end)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Garmin MCP error: {exc}") from exc
        for record in fetched:
            record_date = record.get("date")
            if not record_date:
                continue
            local_store.save_metric_day(metric, date_.fromisoformat(record_date), record)
            by_date[record_date] = record

    return [by_date[d.isoformat()] for d in dates if d.isoformat() in by_date]


@app.get("/api/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.get("/api/snapshot")
async def snapshot(date: Optional[str] = None) -> dict[str, Any]:
    try:
        return await _get_snapshot_dict(_parse_date(date))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Garmin MCP error: {exc}") from exc


@app.get("/api/readiness")
async def readiness(date: Optional[str] = None) -> dict[str, Any]:
    target_date = _parse_date(date)
    snapshot_dict = await snapshot(date)
    snapshot_obj = DailyHealthSnapshot.model_validate(snapshot_dict)
    verdict = compute_verdict(snapshot_obj, target_date)
    garmin_ftp_watts = (snapshot_dict.get("cycling_ftp") or {}).get("ftp_watts")
    return {
        "snapshot": snapshot_dict,
        "verdict": asdict(verdict),
        "current_ftp": ftp_service.current_ftp(garmin_ftp_watts),
    }


def _resolve_range(days: int, start: Optional[str], end: Optional[str]) -> tuple[date_, date_]:
    end_date = _parse_date(end)
    start_date = _parse_date(start) if start else end_date - timedelta(days=days)
    if start_date > end_date:
        raise HTTPException(status_code=422, detail="start date must be on or before end date")
    return start_date, end_date


@app.get("/api/history/hrv")
async def hrv_history(days: int = 30, start: Optional[str] = None, end: Optional[str] = None) -> list[dict[str, Any]]:
    start_date, end_date = _resolve_range(days, start, end)

    async def fetch(s: date_, e: date_) -> list[dict[str, Any]]:
        async with GarminMCPClient() as client:
            return await client.get_hrv_history(start_date=s, end_date=e)

    return await _cached_metric_range("hrv", start_date, end_date, fetch)


@app.get("/api/history/readiness")
async def readiness_history(
    days: int = 30, start: Optional[str] = None, end: Optional[str] = None
) -> list[dict[str, Any]]:
    start_date, end_date = _resolve_range(days, start, end)

    async def fetch(s: date_, e: date_) -> list[dict[str, Any]]:
        async with GarminMCPClient() as client:
            return await client.get_training_readiness_history(start_date=s, end_date=e)

    return await _cached_metric_range("readiness", start_date, end_date, fetch)


class WeightLogRequest(BaseModel):
    weight_kg: float
    date: Optional[date_] = None


@app.get("/api/weight")
async def weight_history(days: int = 180) -> list[list[Any]]:
    return local_store.get_weight_history(limit_days=days)


@app.post("/api/weight")
async def log_weight(payload: WeightLogRequest) -> dict[str, bool]:
    local_store.log_weight(payload.weight_kg, payload.date)
    return {"ok": True}


@app.get("/api/overview")
async def overview(date: Optional[str] = None) -> dict[str, Any]:
    snapshot_dict = await snapshot(date)
    latest_weight = local_store.get_latest_weight()
    garmin_ftp_watts = (snapshot_dict.get("cycling_ftp") or {}).get("ftp_watts")
    current = ftp_service.current_ftp(garmin_ftp_watts)
    return {
        "power_curve": POWER_CURVE_SECONDS,
        "power_curve_unverified": list(POWER_CURVE_UNVERIFIED),
        "ftp_history": local_store.get_ftp_history(),
        "garmin_ftp": snapshot_dict.get("cycling_ftp"),
        "current_ftp": current,
        "rider_profile": rider_profile.classify(current["ftp_watts"]),
        "target_wkg": settings.target_wkg,
        "latest_weight": latest_weight,
        "weight_history": local_store.get_weight_history(limit_days=180),
    }


class FtpLogRequest(BaseModel):
    power_20min_w: float
    date: Optional[date_] = None


@app.post("/api/ftp")
async def log_ftp(payload: FtpLogRequest) -> dict[str, Any]:
    return local_store.log_ftp_test(payload.power_20min_w, payload.date)


@app.get("/api/personal-records")
async def personal_records_endpoint() -> dict[str, Any]:
    return personal_records.compute_prs()


class BlockWeekRequest(BaseModel):
    block_week: int


@app.get("/api/plan/block-week")
async def get_block_week() -> dict[str, int]:
    return {"block_week": local_store.get_block_week()}


@app.post("/api/plan/block-week")
async def set_block_week(payload: BlockWeekRequest) -> dict[str, bool]:
    try:
        local_store.set_block_week(payload.block_week)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True}


def _resolved_ftp_watts(snapshot_dict: dict[str, Any]) -> Optional[float]:
    garmin_ftp_watts = (snapshot_dict.get("cycling_ftp") or {}).get("ftp_watts")
    return ftp_service.current_ftp(garmin_ftp_watts)["ftp_watts"]


@app.get("/api/plan/week")
async def week_plan(date: Optional[str] = None) -> list[dict[str, Any]]:
    snapshot_dict = await snapshot(date)
    ftp_watts = _resolved_ftp_watts(snapshot_dict)
    block_week = local_store.get_block_week()
    return [asdict(p) for p in build_week_plan(ftp_watts, block_week)]


@app.get("/api/plan/today")
async def today_plan(date: Optional[str] = None) -> dict[str, Any]:
    target_date = _parse_date(date)
    readiness_data = await readiness(date)
    ftp_watts = _resolved_ftp_watts(readiness_data["snapshot"])
    block_week = local_store.get_block_week()
    prescription = todays_prescription(target_date, ftp_watts, block_week, readiness_data["verdict"]["verdict"])
    return asdict(prescription)


async def _all_activities(include_hidden: bool = False) -> list[dict[str, Any]]:
    """Garmin's recent activities merged with manually-imported ones, newest
    first, minus anything the athlete has hidden.

    Garmin's get_activities ignores date-range args (verified) and caps limit
    at 100 (also verified — it rejects anything higher), so this covers only
    roughly the last 100 activities however it's sliced. One shared cache for
    every caller, since they all want the same underlying list."""
    cached = local_store.get_metric_day("activities_list_large", date_.today(), max_age_seconds=_TODAY_TTL_SECONDS)
    if cached is not None:
        items = cached["items"]
    else:
        try:
            async with GarminMCPClient() as client:
                items = await client.get_activities(limit=100)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Garmin MCP error: {exc}") from exc
        local_store.save_metric_day(
            "activities_list_large", date_.today(), {"date": date_.today().isoformat(), "items": items}
        )

    merged = list(items) + local_store.list_imported_activities()
    if not include_hidden:
        hidden = local_store.hidden_activity_ids()
        merged = [a for a in merged if str(a.get("activity_id")) not in hidden]
    return sorted(merged, key=lambda a: a.get("start_time_local") or "", reverse=True)


@app.get("/api/activities")
async def activities(limit: int = 20, include_hidden: bool = False) -> list[dict[str, Any]]:
    items = await _all_activities(include_hidden=include_hidden)
    hidden = local_store.hidden_activity_ids()
    assignments = local_store.gear_assignments()
    gear = local_store.list_gear()
    return [
        {
            **a,
            **activity_quality.assess(a),
            "hidden": str(a.get("activity_id")) in hidden,
            "gear_id": gear_service.resolve_gear_id(a, assignments, gear),
            "gear_assigned_explicitly": str(a.get("activity_id")) in assignments,
        }
        for a in items[:limit]
    ]


@app.post("/api/activities/hide-junk")
async def hide_junk_activities() -> dict[str, Any]:
    """Hide every currently-flagged junk ride in one go. Returns what it did
    rather than a bare ok — hiding things silently in bulk is exactly the kind
    of operation that should be able to be reviewed afterwards."""
    hidden_now = []
    for activity in await _all_activities():
        if activity_quality.assess(activity)["likely_junk"]:
            local_store.hide_activity(str(activity["activity_id"]))
            hidden_now.append({"activity_id": activity["activity_id"], "name": activity.get("name")})
    return {"ok": True, "hidden_count": len(hidden_now), "hidden": hidden_now}


@app.get("/api/activities/by-date")
async def activities_by_date(start: Optional[str] = None, end: Optional[str] = None) -> dict[str, list[dict[str, Any]]]:
    """Activities grouped by day, for the PMC chart's hover tooltip and the
    calendar view."""
    start_date = _parse_date(start) if start else date_.today() - timedelta(days=365)
    end_date = _parse_date(end)

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in await _all_activities():
        item_date = (item.get("start_time_local") or "")[:10]
        if item_date and start_date.isoformat() <= item_date <= end_date.isoformat():
            grouped.setdefault(item_date, []).append(item)
    return grouped


@app.delete("/api/activities/{activity_id}")
async def delete_activity(activity_id: str) -> dict[str, Any]:
    """Imported activities are deleted for real. Garmin activities can't be —
    our copy is just a cache that refetches — so they're added to a local hide
    list instead, and the response says which happened."""
    if local_store.delete_imported_activity(activity_id):
        return {"ok": True, "action": "deleted"}
    local_store.hide_activity(activity_id)
    return {"ok": True, "action": "hidden"}


@app.post("/api/activities/{activity_id}/unhide")
async def unhide_activity(activity_id: str) -> dict[str, bool]:
    local_store.unhide_activity(activity_id)
    return {"ok": True}


@app.get("/api/activities/{activity_id}/decoupling")
async def activity_decoupling(activity_id: int) -> dict[str, Any]:
    samples = await activity_details(activity_id)
    return ride_analysis.decoupling(samples)


@app.get("/api/activities/{activity_id}/zones")
async def activity_zones(activity_id: int) -> dict[str, Any]:
    samples = await activity_details(activity_id)
    snapshot_dict = await snapshot(None)
    return zones_service.time_in_zone(samples, _resolved_ftp_watts(snapshot_dict))


@app.post("/api/activities/{activity_id}/analyze")
async def analyze_ride(activity_id: int) -> dict[str, str]:
    activity = next(
        (a for a in await _all_activities(include_hidden=True) if str(a.get("activity_id")) == str(activity_id)), None
    )
    if activity is None:
        raise HTTPException(status_code=404, detail="Activity not found")

    samples = await activity_details(activity_id)
    try:
        splits = await activity_splits(activity_id)
    except HTTPException:
        splits = []  # splits are a nice-to-have for the prompt, not worth failing the analysis over

    snapshot_dict = await snapshot(None)
    ftp_watts = _resolved_ftp_watts(snapshot_dict)
    try:
        reply = await asyncio.to_thread(
            claude_analyzer.analyze_ride, activity, splits, ride_analysis.decoupling(samples), ftp_watts
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"reply": reply}


@app.get("/api/trajectory")
async def trajectory_endpoint(forecast_days: int = 365) -> dict[str, Any]:
    return trajectory.build(forecast_days=forecast_days)


@app.get("/api/ftp-test-status")
async def ftp_test_status() -> dict[str, Any]:
    """Form comes from intervals.icu when it's connected — it's the best
    available read on whether today would produce a representative test.
    Without it, the assessment falls back to block week."""
    form = None
    if intervals_icu.is_configured():
        try:
            recent = await intervals_icu.get_wellness_range(date_.today() - timedelta(days=7), date_.today())
            with_form = [r for r in recent if r.get("form") is not None]
            if with_form:
                form = with_form[-1]["form"]
        except Exception:
            pass  # intervals.icu being down shouldn't break the reminder
    return ftp_test.assess(form=form)


class GearAssignmentRequest(BaseModel):
    gear_id: Optional[str] = None  # null clears the assignment


@app.post("/api/activities/{activity_id}/gear")
async def assign_activity_gear(activity_id: str, payload: GearAssignmentRequest) -> dict[str, bool]:
    local_store.assign_gear(activity_id, payload.gear_id)
    return {"ok": True}


@app.get("/api/activities/{activity_id}/splits")
async def activity_splits(activity_id: int) -> list[dict[str, Any]]:
    cached = local_store.get_activity_splits(activity_id)
    if cached is not None:
        return cached
    try:
        async with GarminMCPClient() as client:
            splits = await client.get_activity_splits(activity_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Garmin MCP error: {exc}") from exc
    local_store.save_activity_splits(activity_id, splits)
    return splits


@app.get("/api/activities/{activity_id}/details")
async def activity_details(activity_id: int) -> list[dict[str, Any]]:
    """Per-sample time series for the ride-segment selector (distance/elevation/
    speed/HR/gradient for a user-selected portion of the ride)."""
    cached = local_store.get_activity_details(activity_id)
    if cached is not None:
        return cached
    try:
        async with GarminMCPClient() as client:
            samples = await client.get_activity_details(activity_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Garmin MCP error: {exc}") from exc
    local_store.save_activity_details(activity_id, samples)
    return samples


@app.get("/api/calendar")
async def calendar(start: str, end: str) -> dict[str, dict[str, Any]]:
    """Month-view data: completed activities (real, from Garmin) + planned
    workouts. block_week is a single current value with no historical/future
    per-week record (see database/local_store.get_block_week), so there's no
    real "what was planned 3 weeks ago" to reconstruct — every week in range
    shows the same current weekly template repeated by weekday. Past days
    still show their real completed activities; only the "planned" chip is
    a repeating template rather than a true historical schedule."""
    start_date = _parse_date(start)
    end_date = _parse_date(end)
    activities = await activities_by_date(start, end)

    snapshot_dict = await snapshot(None)
    ftp_watts = _resolved_ftp_watts(snapshot_dict)
    block_week = local_store.get_block_week()
    plan_by_weekday = {p.weekday: p for p in build_week_plan(ftp_watts, block_week)}

    result: dict[str, dict[str, Any]] = {}
    d = start_date
    while d <= end_date:
        iso = d.isoformat()
        prescription = plan_by_weekday.get(d.weekday())
        result[iso] = {
            "activities": activities.get(iso, []),
            "planned": asdict(prescription) if prescription else None,
        }
        d += timedelta(days=1)
    return result


@app.get("/api/coggan-profile")
async def coggan_profile_endpoint(date: Optional[str] = None) -> dict[str, Any]:
    snapshot_dict = await snapshot(date)
    ftp_watts = _resolved_ftp_watts(snapshot_dict)
    latest_weight = local_store.get_latest_weight()
    weight_kg = latest_weight[1] if latest_weight else None
    profile = coggan.build_profile(weight_kg, ftp_watts)
    profile["curve"] = coggan.build_curve(weight_kg, ftp_watts)
    return profile


class StrengthSessionRequest(BaseModel):
    date: Optional[date_] = None
    session_type: str = "general"
    duration_min: Optional[int] = None
    notes: str = ""


@app.get("/api/strength")
async def strength_sessions(days: int = 180) -> list[dict[str, Any]]:
    return local_store.get_strength_sessions(limit_days=days)


@app.post("/api/strength")
async def log_strength(payload: StrengthSessionRequest) -> dict[str, Any]:
    entry = payload.model_dump()
    entry["date"] = (payload.date or date_.today()).isoformat()
    return local_store.log_strength_session(entry)


@app.delete("/api/strength/{session_id}")
async def delete_strength(session_id: str) -> dict[str, bool]:
    local_store.delete_strength_session(session_id)
    return {"ok": True}


@app.get("/api/intervals/status")
async def intervals_status() -> dict[str, bool]:
    return {"configured": intervals_icu.is_configured()}


@app.get("/api/intervals/wellness")
async def intervals_wellness(days: int = 90, start: Optional[str] = None, end: Optional[str] = None) -> list[dict[str, Any]]:
    end_date = _parse_date(end)
    start_date = _parse_date(start) if start else end_date - timedelta(days=days)
    try:
        return await intervals_icu.get_wellness_range(start_date, end_date)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"intervals.icu error: {exc}") from exc


@app.get("/api/trends/pr-markers")
async def pr_markers(start: str, end: str) -> dict[str, dict[str, Any]]:
    return personal_records.pr_markers_by_date(start, end)


class GoalModel(BaseModel):
    id: Optional[str] = None
    title: str
    category: str  # e.g. "Cat 2" — a Coggan category target
    duration_label: str  # e.g. "5min power" — which power-curve zone this targets
    target_watts: Optional[float] = None
    target_date: Optional[date_] = None
    notes: str = ""


@app.get("/api/goals")
async def list_goals() -> list[dict[str, Any]]:
    return local_store.list_goals()


@app.post("/api/goals")
async def save_goal(payload: GoalModel) -> dict[str, Any]:
    data = payload.model_dump()
    if data.get("target_date"):
        data["target_date"] = data["target_date"].isoformat()
    return local_store.save_goal(data)


@app.delete("/api/goals/{goal_id}")
async def delete_goal(goal_id: str) -> dict[str, bool]:
    local_store.delete_goal(goal_id)
    return {"ok": True}


class GearModel(BaseModel):
    id: Optional[str] = None
    name: str
    type: str  # bike | wheelset | chain | tires | other
    install_date: Optional[date_] = None
    # Starting/offset mileage the athlete types in (e.g. "this bike already had
    # 3400km on it"). Distance from assigned activities is summed on top of
    # this at read time — see services/gear.py.
    accumulated_distance_km: float = 0
    # Activity types this gear is auto-assigned to when a ride has no explicit
    # assignment, e.g. ["road_biking"] — saves per-ride clicking.
    default_for_types: list[str] = []
    notes: str = ""


@app.get("/api/gear")
async def list_gear() -> list[dict[str, Any]]:
    return gear_service.with_distances(await _all_activities())


@app.post("/api/gear")
async def save_gear(payload: GearModel) -> dict[str, Any]:
    data = payload.model_dump()
    if data.get("install_date"):
        data["install_date"] = data["install_date"].isoformat()
    return local_store.save_gear(data)


@app.delete("/api/gear/{gear_id}")
async def delete_gear(gear_id: str) -> dict[str, bool]:
    local_store.delete_gear(gear_id)
    return {"ok": True}


@app.post("/api/activities/import")
async def import_activity(file: UploadFile) -> dict[str, Any]:
    if not activity_import.is_supported(file.filename or ""):
        raise HTTPException(status_code=400, detail="Unsupported file type — use .fit, .gpx, or .tcx")
    content = await file.read()
    try:
        record = activity_import.parse_activity_file(file.filename, content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Couldn't parse {file.filename}: {exc}") from exc
    return local_store.save_imported_activity(record)


class ExportRequest(BaseModel):
    start: date_
    end: date_
    categories: list[str]
    format: str = "json"  # json | csv


@app.post("/api/export")
async def export_data(payload: ExportRequest) -> Response:
    unknown = set(payload.categories) - set(export_service.CATEGORIES)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown categories: {sorted(unknown)}")
    content, filename, media_type = export_service.build_export(
        payload.categories, payload.start.isoformat(), payload.end.isoformat(), payload.format
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class AeroProfileModel(BaseModel):
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    position: str = "relaxed"  # relaxed | aero | tt
    wheelset_depth_mm: Optional[float] = None
    frame_type: str = "neutral"  # aero | neutral | endurance | tt


@app.get("/api/aero-profile")
async def get_aero_profile() -> dict[str, Any]:
    return local_store.get_aero_profile()


@app.post("/api/aero-profile")
async def save_aero_profile(payload: AeroProfileModel) -> dict[str, Any]:
    return local_store.save_aero_profile(payload.model_dump())


class WorkoutStep(BaseModel):
    duration_sec: int
    target_type: str  # steady | range | ramp
    target_low_pct_ftp: float
    target_high_pct_ftp: Optional[float] = None


class WorkoutModel(BaseModel):
    id: Optional[str] = None
    name: str
    description: str = ""
    steps: list[WorkoutStep]


@app.get("/api/workouts")
async def list_workouts() -> list[dict[str, Any]]:
    return local_store.list_workouts()


@app.post("/api/workouts")
async def save_workout(payload: WorkoutModel) -> dict[str, Any]:
    return local_store.save_workout(payload.model_dump())


@app.delete("/api/workouts/{workout_id}")
async def delete_workout(workout_id: str) -> dict[str, bool]:
    local_store.delete_workout(workout_id)
    return {"ok": True}


@app.get("/api/workouts/wednesday-template")
async def wednesday_template() -> dict[str, Any]:
    block_week = local_store.get_block_week()
    return {
        "name": f"Wednesday intervals (block week {block_week})",
        "description": "Auto-generated from your training plan — edit freely.",
        "steps": wednesday_workout_steps(block_week),
    }


@app.post("/api/workouts/export-zwo")
async def export_zwo(payload: WorkoutModel) -> Response:
    zwo = to_zwo(payload.model_dump())
    filename = "".join(c if c.isalnum() else "_" for c in payload.name) + ".zwo"
    return Response(
        content=zwo,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


@app.get("/api/coach/followups")
async def followups() -> list[str]:
    return claude_analyzer.SUGGESTED_FOLLOWUPS


@app.post("/api/coach/analyze")
async def coach_analyze(date: Optional[str] = None) -> dict[str, str]:
    snapshot_dict = await snapshot(date)
    snapshot_obj = DailyHealthSnapshot.model_validate(snapshot_dict)
    latest = local_store.get_latest_weight()
    weight_kg = latest[1] if latest else None
    try:
        reply = await asyncio.to_thread(claude_analyzer.analyze_day, snapshot_obj, weight_kg)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"reply": reply}


@app.post("/api/coach/chat")
async def coach_chat(req: ChatRequest, date: Optional[str] = None) -> dict[str, str]:
    snapshot_dict = await snapshot(date)
    snapshot_obj = DailyHealthSnapshot.model_validate(snapshot_dict)
    latest = local_store.get_latest_weight()
    weight_kg = latest[1] if latest else None
    history = [{"role": m.role, "content": m.content} for m in req.messages]
    try:
        reply = await asyncio.to_thread(claude_analyzer.chat_reply, history, snapshot_obj, weight_kg)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"reply": reply}


# Serves the built frontend (frontend/dist, produced by `npm run build`) from
# the same container/origin as the API in production, so the deployed app
# needs no CORS config and no separate frontend host. Mounted last so it
# never shadows an /api/* route above — and note app.mount() bypasses the
# app-level verify_token dependency entirely (it's a raw ASGI sub-app, not a
# FastAPI path operation), which is required: the browser can't attach a
# Firebase token before the login page's own JS has even loaded.
_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True), name="frontend")
