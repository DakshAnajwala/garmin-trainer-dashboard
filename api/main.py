"""FastAPI backend for the React frontend — wraps the existing Garmin MCP
client, local storage, and Claude coaching service behind a REST API.

Run with: uvicorn api.main:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict
from datetime import date as date_, timedelta
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from auth.firebase_auth import verify_token
from config.athlete_profile import FTP_TEST_FACTOR, POWER_CURVE_SECONDS, POWER_CURVE_UNVERIFIED
from config.settings import settings
from database import backup, firestore_db, local_store
from garmin_mcp.garmin_client import GarminMCPClient
from garmin_mcp.schemas import DailyHealthSnapshot
from services import activity_import
from services import activity_quality
from services import adaptive_load
from services import adaptive_periodization
from services import brief as brief_service
from services import claude_analyzer
from services import duplicate_detection
from services import coggan
from services import export as export_service
from services import ftp as ftp_service
from services import ftp_test
from services import gear as gear_service
from services import intervals_icu, personal_records, ride_analysis, rider_profile, sample_cleaning, trajectory
from services import app_settings, athlete as athlete_service, power_calibration, power_curve
from services import ai_day_planner, custom_model, data_query, day_planner, model_backtest, physiology_model, plan_generator, plan_reflow, route_demand
from services import training_compliance
from services import workout_types
from services.readiness import compute_verdict
from services.training_plan import (
    apply_constraints,
    build_week_plan,
    todays_prescription,
    travel_window_for,
    wednesday_workout_steps,
)
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
    travel_window = travel_window_for(target_date, local_store.get_constraints())
    traveling_note = f"{travel_window['start']} to {travel_window['end']}" if travel_window else None
    verdict = compute_verdict(snapshot_obj, target_date, traveling_note)
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
    measured = _measured_ftp()
    current = ftp_service.current_ftp(garmin_ftp_watts, measured)
    merged = power_curve.merged_curve()
    return {
        # Best-known power per duration: the self-reported config bests merged
        # with what rides actually measured (excluded rides filtered out).
        "power_curve": {d: p["watts"] for d, p in merged.items()},
        "power_curve_detail": {str(d): p for d, p in merged.items()},
        "power_curve_unverified": list(POWER_CURVE_UNVERIFIED),
        "measured_ftp": measured,
        "rides_analyzed": len(power_curve.cached_rides()),
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


@app.get("/api/plan/adaptive-recommendation")
async def adaptive_recommendation() -> dict[str, Any]:
    """Whether the trailing week actually absorbed the current block's
    prescribed load — a recommendation to advance/hold/step back, not an
    automatic change. See services/adaptive_periodization.py."""
    current_block_week = local_store.get_block_week()
    snapshot_dict = await snapshot(None)
    ftp_watts = _resolved_ftp_watts(snapshot_dict)
    load = snapshot_dict.get("training_load") or {}
    form = await _recent_form()
    activities_by_day = await activities_by_date(
        (date_.today() - timedelta(days=8)).isoformat(), date_.today().isoformat()
    )

    rec = adaptive_periodization.recommend(
        current_block_week,
        local_store.get_all_snapshots(),
        ftp_watts,
        load.get("acwr"),
        load.get("acwr_status"),
        form,
        activities_by_day,
    )
    return {
        "current_block_week": rec.current_block_week,
        "recommended_block_week": rec.recommended_block_week,
        "should_change": rec.should_change,
        "downgrade_days": rec.downgrade_days,
        "missed_days": rec.missed_days,
        "days_analyzed": rec.days_analyzed,
        "reason": rec.reason,
    }


def _measured_ftp() -> Optional[dict[str, Any]]:
    """FTP implied by the best *unexcluded* measured 20min. Recomputed from raw
    samples each call, so excluding a bad ride moves it immediately."""
    return power_curve.estimate_ftp(power_curve.measured_all_time(), FTP_TEST_FACTOR)


def _resolved_ftp_watts(snapshot_dict: dict[str, Any]) -> Optional[float]:
    garmin_ftp_watts = (snapshot_dict.get("cycling_ftp") or {}).get("ftp_watts")
    return ftp_service.current_ftp(garmin_ftp_watts, _measured_ftp())["ftp_watts"]


@app.get("/api/plan/compliance")
async def plan_compliance() -> dict[str, Any]:
    """This week's distance against the team's 300km/week minimum — separate
    from the Saturday team ride itself. See services/training_compliance.py."""
    return training_compliance.week_distance_km()


@app.get("/api/plan/week")
async def week_plan(date: Optional[str] = None) -> list[dict[str, Any]]:
    snapshot_dict = await snapshot(date)
    ftp_watts = _resolved_ftp_watts(snapshot_dict)
    block_week = local_store.get_block_week()
    anchor = _parse_date(date)
    monday = anchor - timedelta(days=anchor.weekday())
    constraints = local_store.get_constraints()
    plans = build_week_plan(ftp_watts, block_week)
    return [asdict(apply_constraints(p, monday + timedelta(days=p.weekday), constraints)) for p in plans]


class ConstraintsModel(BaseModel):
    race_date: Optional[date_] = None
    travel_windows: list[dict[str, str]] = []  # [{"start": iso, "end": iso, "note": str}]


@app.get("/api/constraints")
async def get_constraints() -> dict[str, Any]:
    return local_store.get_constraints()


@app.post("/api/constraints")
async def save_constraints(payload: ConstraintsModel) -> dict[str, Any]:
    data = payload.model_dump()
    if data.get("race_date"):
        data["race_date"] = data["race_date"].isoformat()
    return local_store.save_constraints(data)


def _todays_prescription_with_constraints(
    target_date: date_, ftp_watts: Optional[float], block_week: int, verdict: Optional[str]
):
    prescription = todays_prescription(target_date, ftp_watts, block_week, verdict)
    return apply_constraints(prescription, target_date, local_store.get_constraints())


async def _load_advisory(snapshot_dict: dict[str, Any]) -> dict[str, Any]:
    load = snapshot_dict.get("training_load") or {}
    form = await _recent_form()
    return adaptive_load.assess(load.get("acwr"), load.get("acwr_status"), form)


@app.get("/api/plan/today")
async def today_plan(date: Optional[str] = None) -> dict[str, Any]:
    target_date = _parse_date(date)
    readiness_data = await readiness(date)
    ftp_watts = _resolved_ftp_watts(readiness_data["snapshot"])
    block_week = local_store.get_block_week()
    verdict = readiness_data["verdict"]
    prescription = _todays_prescription_with_constraints(
        target_date, ftp_watts, block_week, verdict["verdict"]
    )
    result = asdict(prescription)
    result["load_advisory"] = await _load_advisory(readiness_data["snapshot"])

    # One line that says *why this session*: the score, the block, and whether
    # readiness changed anything — the reasoning, not just the output.
    score = (readiness_data["snapshot"].get("training_readiness") or {}).get("readiness_score")
    swapped = prescription.session_type in ("endurance_swap", "rest_swap")
    result["rationale"] = (
        f"Readiness {verdict['verdict']}"
        + (f" (score {score})" if score is not None else "")
        + f", block week {block_week}: "
        + (f"downgraded today to {prescription.title}." if swapped else f"{prescription.title} as planned.")
    )
    result["decision"] = local_store.get_prescription_log().get(target_date.isoformat())
    return result


class PrescriptionDecision(BaseModel):
    decision: str  # accepted | overridden
    reason: str = ""


# --- Settings -------------------------------------------------------------------


@app.get("/api/athlete")
async def get_athlete() -> dict[str, Any]:
    """Who you are, physiologically: what you declared and what the app worked
    out from your rides. Two halves of one question, so one endpoint."""
    model = local_store.get_physiology_model() or physiology_model.compute()
    snapshot_dict = await snapshot(None)
    return {
        "declared": athlete_service.declared_profile(),
        "model": model,
        "phenotype": rider_profile.classify(_resolved_ftp_watts(snapshot_dict)),
    }


@app.get("/api/settings")
async def get_settings() -> dict[str, Any]:
    """Everything the Settings tab shows. Secret *values* are never included —
    only whether each is configured (see services/app_settings.py).

    Physiology deliberately isn't here — it moved to /api/athlete. It only lived
    in Settings because Settings was where config went; it's identity, not
    configuration.
    """
    return {
        "secrets": app_settings.secrets_status(),
        "excluded_config": app_settings.EXCLUDED_CONFIG,
        "intervals": {
            "configured": intervals_icu.is_configured(),
            "athlete_id": intervals_icu.athlete_id(),  # not sensitive: a public account number
            "athlete_id_source": "app" if local_store.get_app_config().get("intervals_athlete_id") else "env",
        },
        "sync": {
            "firestore_available": firestore_db.available(),
            "synced_keys": sorted(local_store._SYNCED_KEYS),
            "note": (
                "Synced keys follow you across devices. Garmin-derived caches (snapshots, activity "
                "details) stay local — they're re-fetchable and would blow Firestore's 1MiB/doc cap."
            ),
        },
        "backups": backup.list_backups(),
        "env_only": {"anthropic_model": settings.anthropic_model},
    }


class SecretRequest(BaseModel):
    value: str


@app.post("/api/settings/secrets/{name}")
async def set_secret(name: str, payload: SecretRequest) -> dict[str, Any]:
    try:
        return app_settings.set_secret(name, payload.value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/settings/secrets/{name}")
async def revoke_secret(name: str) -> dict[str, Any]:
    try:
        return app_settings.revoke_secret(name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class IntervalsConfig(BaseModel):
    athlete_id: str


@app.post("/api/settings/intervals")
async def set_intervals_athlete(payload: IntervalsConfig) -> dict[str, Any]:
    """The athlete ID was an env-only field, so connecting intervals.icu used to
    mean editing .env and restarting. Storing it makes the connection
    configurable from the app; env stays the fallback."""
    athlete_id = payload.athlete_id.strip()
    if athlete_id and not athlete_id.isdigit():
        raise HTTPException(status_code=400, detail="intervals.icu athlete ID is numeric (find it in your profile URL).")
    local_store.set_app_config("intervals_athlete_id", athlete_id)
    return {"configured": intervals_icu.is_configured(), "athlete_id": intervals_icu.athlete_id()}


@app.post("/api/settings/resync")
async def resync_to_cloud() -> dict[str, Any]:
    """Push local synced keys up to Firestore, overwriting what's there.

    Needed after restoring a backup: _load() lets Firestore win for synced keys,
    so a restored file is invisible until it's pushed back up. This was buried
    in scripts/backups.py, where you'd only find it if you already knew.
    """
    if not firestore_db.available():
        raise HTTPException(status_code=400, detail="Firestore isn't configured — nothing to sync to.")
    synced = local_store.resync_file_to_cloud()
    return {"ok": True, "keys_pushed": sorted(synced.keys())}


# --- F6: inspectable / overridable / programmable model -----------------------


@app.get("/api/model")
async def get_model(recompute: bool = False) -> dict[str, Any]:
    model = None if recompute else local_store.get_physiology_model()
    return model or physiology_model.compute()


class ModelOverrideRequest(BaseModel):
    name: str
    value: Optional[float] = None  # None clears the override
    locked: bool = True
    reason: str = ""


@app.post("/api/model/override")
async def set_model_override(payload: ModelOverrideRequest) -> dict[str, Any]:
    """Set/lock (or clear) a parameter, with the advisory backtest run on the
    change — advice attached, never a gate."""
    if payload.name not in physiology_model.PARAM_BOUNDS:
        raise HTTPException(status_code=400, detail=f"Unknown parameter '{payload.name}'")
    advisory = None
    if payload.value is not None:
        lo, hi = physiology_model.PARAM_BOUNDS[payload.name]
        if not (lo <= payload.value <= hi):
            raise HTTPException(status_code=400, detail=f"'{payload.name}' must be within [{lo}, {hi}]")
        current = physiology_model.effective_values()
        advisory = model_backtest.evaluate_change({**current, payload.name: payload.value}, current)
    local_store.set_model_override(payload.name, payload.value, payload.locked, payload.reason)
    return {"model": physiology_model.compute(), "advisory": advisory}


@app.get("/api/model/export")
async def export_model() -> Response:
    """The portable model: params with provenance, overrides, and FTP history —
    yours to take elsewhere, not just raw ride files."""
    model = local_store.get_physiology_model() or physiology_model.compute()
    payload = {
        "physiology_model": model,
        "overrides": local_store.get_model_overrides(),
        "ftp_history": local_store.get_ftp_history(),
        "exported_at": date_.today().isoformat(),
    }
    return Response(
        content=json.dumps(payload, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="physiology_model.json"'},
    )


class CustomAlgoConfig(BaseModel):
    endpoint_url: str
    api_key: str


@app.get("/api/model/custom-algo")
async def custom_algo_status() -> dict[str, Any]:
    return custom_model.status()


@app.post("/api/model/custom-algo")
async def custom_algo_configure(payload: CustomAlgoConfig) -> dict[str, Any]:
    try:
        return custom_model.configure(payload.endpoint_url, payload.api_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/model/custom-algo")
async def custom_algo_revoke() -> dict[str, Any]:
    return custom_model.revoke()


@app.post("/api/model/custom-algo/propose")
async def custom_algo_propose() -> dict[str, Any]:
    try:
        return await asyncio.to_thread(custom_model.propose)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class CustomAlgoApply(BaseModel):
    proposed: dict[str, float]


@app.post("/api/model/custom-algo/apply")
async def custom_algo_apply(payload: CustomAlgoApply) -> dict[str, Any]:
    try:
        return custom_model.apply(payload.proposed)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# --- F1: race events + demand profiles -----------------------------------------


@app.get("/api/events")
async def list_events() -> list[dict[str, Any]]:
    out = []
    for e in local_store.list_race_events():
        profile = local_store.get_demand_profile(e["id"])
        out.append({**e, "has_profile": profile is not None,
                    "gap_summary": [g["status"] for g in (profile or {}).get("gap_report", [])]})
    return out


@app.post("/api/events")
async def create_event(
    file: UploadFile,
    name: str,
    date: str,
    rider_mass_kg: float,
    bike_kit_kg: float = 9.0,
) -> dict[str, Any]:
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Route file over 10MB — that's not a route.")
    try:
        points = route_demand.parse_route(content, file.filename or "route.gpx")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    event = {
        "id": str(int(time.time() * 1000)),
        "name": name, "date": date,
        "rider_mass_kg": rider_mass_kg, "bike_kit_kg": bike_kit_kg,
        "conditions_override": None,
    }
    local_store.save_race_event(event)
    local_store.save_event_route(event["id"], points)
    profile = await asyncio.to_thread(route_demand.recompute_event, event)
    return {"event": event, "profile": profile}


class EventUpdate(BaseModel):
    rider_mass_kg: Optional[float] = None
    bike_kit_kg: Optional[float] = None
    conditions_override: Optional[dict[str, Any]] = None  # {temp_c, humidity_pct, source}


@app.post("/api/events/{event_id}/recompute")
async def recompute_event(event_id: str, payload: EventUpdate) -> dict[str, Any]:
    event = next((e for e in local_store.list_race_events() if e["id"] == event_id), None)
    if not event:
        raise HTTPException(status_code=404, detail="No such event")
    for field in ("rider_mass_kg", "bike_kit_kg", "conditions_override"):
        value = getattr(payload, field)
        if value is not None:
            event[field] = value
    local_store.save_race_event(event)
    return await asyncio.to_thread(route_demand.recompute_event, event)


@app.get("/api/events/{event_id}/demand")
async def event_demand(event_id: str) -> dict[str, Any]:
    profile = local_store.get_demand_profile(event_id)
    if not profile:
        raise HTTPException(status_code=404, detail="No demand profile computed yet")
    return profile


@app.delete("/api/events/{event_id}")
async def delete_event(event_id: str) -> dict[str, bool]:
    local_store.delete_race_event(event_id)
    return {"ok": True}


# --- F8: plan reflow + pins ------------------------------------------------------


@app.get("/api/plan/reflow")
async def plan_reflow_endpoint(date: Optional[str] = None) -> dict[str, Any]:
    target_date = _parse_date(date)
    snapshot_dict = await snapshot(None)
    ftp_watts = _resolved_ftp_watts(snapshot_dict)
    monday = target_date - timedelta(days=target_date.weekday())
    acts = await activities_by_date(monday.isoformat(), (monday + timedelta(days=6)).isoformat())
    return plan_reflow.reflow_week(
        ftp_watts,
        local_store.get_block_week(),
        acts,
        local_store.get_constraints(),
        local_store.get_plan_pins(),
        target_date,
    )


class PinRequest(BaseModel):
    date: str
    pinned: bool
    reason: str = ""


@app.post("/api/plan/pins")
async def set_pin(payload: PinRequest) -> dict[str, Any]:
    local_store.set_plan_pin(payload.date, payload.pinned, payload.reason)
    return {"pins": local_store.get_plan_pins()}


# --- F5: ask-your-own-data --------------------------------------------------------


class DataQuery(BaseModel):
    q: str


@app.post("/api/query")
async def query_data(payload: DataQuery) -> dict[str, Any]:
    if not payload.q.strip():
        raise HTTPException(status_code=400, detail="Empty query")
    return await asyncio.to_thread(data_query.answer, payload.q)


@app.post("/api/plan/today/decision")
async def log_today_decision(payload: PrescriptionDecision, date: Optional[str] = None) -> dict[str, Any]:
    """Accept, or override-with-why. The why is the valuable part: a pattern of
    overrides is the plan being told it's wrong about something."""
    if payload.decision not in ("accepted", "overridden"):
        raise HTTPException(status_code=400, detail="decision must be 'accepted' or 'overridden'")
    if payload.decision == "overridden" and not payload.reason.strip():
        raise HTTPException(status_code=400, detail="an override needs a reason — that's the signal the plan learns from")
    target_date = _parse_date(date)
    local_store.log_prescription_decision(target_date.isoformat(), payload.decision, payload.reason)
    return {"ok": True, "logged": local_store.get_prescription_log()[target_date.isoformat()]}


@app.get("/api/brief")
async def brief(date: Optional[str] = None) -> dict[str, Any]:
    """One card: what today calls for, and the one thing that changed since
    yesterday — instead of open-five-tabs-and-stare."""
    target_date = _parse_date(date)
    readiness_data = await readiness(date)
    yesterday_dict = local_store.get_snapshot(target_date - timedelta(days=1), max_age_seconds=None)

    block_week = local_store.get_block_week()
    ftp_watts = _resolved_ftp_watts(readiness_data["snapshot"])
    prescription = _todays_prescription_with_constraints(
        target_date, ftp_watts, block_week, readiness_data["verdict"]["verdict"]
    )
    the_brief = brief_service.build(readiness_data["snapshot"], yesterday_dict, target_date)

    return {
        "verdict": readiness_data["verdict"],
        "today_session": prescription.title,
        "brief": the_brief,
        "load_advisory": await _load_advisory(readiness_data["snapshot"]),
    }


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
    exclusions = local_store.get_power_exclusions()
    return [
        {
            **a,
            **activity_quality.assess(a),
            "hidden": str(a.get("activity_id")) in hidden,
            "gear_id": gear_service.resolve_gear_id(a, assignments, gear),
            "gear_assigned_explicitly": str(a.get("activity_id")) in assignments,
            "power_excluded": bool(
                (exclusions.get(str(a.get("activity_id"))) or {}).get("excluded")
            ),
            "power_segments_excluded": len(
                (exclusions.get(str(a.get("activity_id"))) or {}).get("ranges") or []
            ),
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


@app.get("/api/activities/devices")
async def activity_devices() -> list[dict[str, Any]]:
    """Distinct recording devices seen in recent activities, for the gear
    auto-claim UI. Just Garmin's raw deviceId — no friendly device name is
    exposed by the MCP client — so a sample activity is included to help
    tell devices apart."""
    activities = await _all_activities()
    by_device: dict[str, dict[str, Any]] = {}
    for a in activities:
        device_id = a.get("device_id")
        if not device_id:
            continue
        key = str(device_id)
        entry = by_device.setdefault(key, {"device_id": key, "count": 0, "sample_name": a.get("name"), "sample_date": a.get("start_time_local")})
        entry["count"] += 1
    return sorted(by_device.values(), key=lambda e: e["count"], reverse=True)


@app.get("/api/activities/duplicates")
async def duplicate_activities() -> list[dict[str, Any]]:
    """Groups of activities that look like the same ride recorded twice
    (head unit + phone, or a re-import of something Garmin already has).
    Resolution is a client choice — this only flags candidates."""
    activities = await _all_activities()
    return duplicate_detection.find_duplicates(activities)


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


class DebriefRequest(BaseModel):
    text: str


@app.get("/api/activities/{activity_id}/debrief")
async def get_ride_debrief(activity_id: str) -> dict[str, Optional[str]]:
    return {"text": local_store.get_ride_debrief(activity_id)}


@app.post("/api/activities/{activity_id}/debrief")
async def save_ride_debrief(activity_id: str, payload: DebriefRequest) -> dict[str, bool]:
    local_store.save_ride_debrief(activity_id, payload.text)
    return {"ok": True}


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
    debrief_text = local_store.get_ride_debrief(str(activity_id))
    try:
        reply = await asyncio.to_thread(
            claude_analyzer.analyze_ride,
            activity,
            splits,
            ride_analysis.decoupling(samples),
            ftp_watts,
            debrief_text,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"reply": reply}


@app.get("/api/trajectory")
async def trajectory_endpoint(forecast_days: int = 365) -> dict[str, Any]:
    return trajectory.build(forecast_days=forecast_days)


async def _recent_form() -> Optional[float]:
    """Most recent Form (TSB) from intervals.icu, or None if it's not
    connected or the request fails — callers treat None as "signal
    unavailable", not as an error.

    Cached, because this is a network round-trip to intervals.icu that four
    endpoints (`/api/ftp-test-status`, `/api/plan/today`, `/api/brief`,
    `/api/plan/adaptive-recommendation`) each paid in full: measured at
    1.5-2.0s per call, it was the single slowest thing in the app and the
    dominant cost of loading the Power page.

    Form is a rolling training-load metric that moves on the scale of days —
    a 15-minute TTL (the same one today's Garmin snapshot uses) is far finer
    than the signal actually changes, so this costs no freshness worth having.

    Cached through the existing metric-day store, so it survives a restart and
    follows the same "disposable, re-fetchable, local-only" rules as the rest
    of the Garmin/intervals caches. The value is wrapped in a dict because a
    bare None is indistinguishable from "not cached" — and "intervals.icu says
    you have no Form data" is a real answer worth caching, not a miss.
    """
    if not intervals_icu.is_configured():
        return None

    cached = local_store.get_metric_day("intervals_form", date_.today(), max_age_seconds=_TODAY_TTL_SECONDS)
    if cached is not None:
        return cached.get("form")

    try:
        recent = await intervals_icu.get_wellness_range(date_.today() - timedelta(days=7), date_.today())
        with_form = [r for r in recent if r.get("form") is not None]
        form = with_form[-1]["form"] if with_form else None
    except Exception:
        # Don't cache failures: a transient intervals.icu blip shouldn't blind
        # the load advisory for the next 15 minutes.
        return None

    local_store.save_metric_day("intervals_form", date_.today(), {"form": form})
    return form


@app.get("/api/ftp-test-status")
async def ftp_test_status() -> dict[str, Any]:
    """Form comes from intervals.icu when it's connected — it's the best
    available read on whether today would produce a representative test.
    Without it, the assessment falls back to block week."""
    return ftp_test.assess(form=await _recent_form())


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
    speed/HR/gradient for a user-selected portion of the ride).

    Cleaned once here, before caching, so every consumer (decoupling, zones,
    route map, segment selector) gets the cleaned series without needing its
    own defensive logic — see services/sample_cleaning.py."""
    cached = local_store.get_activity_details(activity_id)
    if cached is not None:
        return cached
    try:
        async with GarminMCPClient() as client:
            samples = await client.get_activity_details(activity_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Garmin MCP error: {exc}") from exc
    samples, _report = sample_cleaning.clean(samples)
    local_store.save_activity_details(activity_id, samples)
    return samples


class PowerExclusionRequest(BaseModel):
    excluded: Optional[bool] = None
    reason: Optional[str] = None
    ranges: Optional[list[dict[str, int]]] = None


@app.get("/api/activities/{activity_id}/power-exclusion")
async def get_power_exclusion(activity_id: int) -> dict[str, Any]:
    """Current exclusion state plus any calibration red flags worth a prompt.

    The flags are suggestions only — nothing here excludes anything on its own.
    """
    samples = local_store.get_activity_details(activity_id) or []
    known_max = max(POWER_CURVE_SECONDS.values()) if POWER_CURVE_SECONDS else None
    return {
        **local_store.get_power_exclusion(str(activity_id)),
        "suggestions": power_calibration.inspect(samples, known_max),
    }


@app.post("/api/activities/{activity_id}/power-exclusion")
async def set_power_exclusion(activity_id: int, payload: PowerExclusionRequest) -> dict[str, Any]:
    """Exclude a ride's power (or brushed segments of it) from the power curve
    and FTP. Only aggregation is affected — the raw samples are untouched, so
    re-including restores the previous curve exactly, and distance/duration/HR
    never move either way."""
    return local_store.set_power_exclusion(
        str(activity_id),
        excluded=payload.excluded,
        reason=payload.reason,
        ranges=payload.ranges,
    )


@app.get("/api/calendar")
async def calendar(start: str, end: str) -> dict[str, dict[str, Any]]:
    """Month-view data: completed activities (real, from Garmin) + the athlete's
    actual dated plan.

    The "planned" chip now comes from stored planned_workouts, not a repeating
    template. That means the calendar starts EMPTY — a day only has a planned
    session once it's been generated or built, exactly like intervals.icu.
    (The old behaviour painted the same weekly template onto every week, which
    looked like a plan but couldn't be edited and was the same every week.)"""
    start_date = _parse_date(start)
    end_date = _parse_date(end)
    activities = await activities_by_date(start, end)
    planned = local_store.get_planned_workouts(start, end)

    result: dict[str, dict[str, Any]] = {}
    d = start_date
    while d <= end_date:
        iso = d.isoformat()
        result[iso] = {
            "activities": activities.get(iso, []),
            "planned": planned.get(iso),
        }
        d += timedelta(days=1)
    return result


class PlannedWorkoutModel(BaseModel):
    # rest | endurance | intervals | team_ride | long_ride | strength | sick | note | custom
    session_type: str = "endurance"
    title: str
    detail: str = ""
    duration_min: Optional[int] = None
    target_watts_low: Optional[int] = None
    target_watts_high: Optional[int] = None
    steps: list[WorkoutStep] = []
    source: str = "custom"
    #: Strength sessions only. Carried on the planned session so "mark as done"
    #: can write a /api/strength entry with the focus the suggestion actually
    #: chose, instead of defaulting everything to full_body and losing the
    #: weakness targeting the moment the athlete completes it.
    strength_log_type: Optional[str] = None


@app.get("/api/planned")
async def get_planned(start: str, end: str) -> dict[str, Any]:
    return local_store.get_planned_workouts(start, end)


@app.put("/api/planned/{plan_date}")
async def save_planned(plan_date: str, payload: PlannedWorkoutModel) -> dict[str, Any]:
    """Create or edit the planned session for a single day. Full structured
    object, so 'open in Builder' can round-trip reps/watts."""
    _parse_date(plan_date)  # validate the date shape before storing under it
    return local_store.save_planned_workout(plan_date, payload.model_dump())


@app.delete("/api/planned/{plan_date}")
async def clear_planned(plan_date: str) -> dict[str, Any]:
    removed = local_store.delete_planned_workout(plan_date)
    return {"ok": True, "removed": removed is not None}


@app.post("/api/planned/generate-week")
async def generate_planned_week(day: Optional[str] = None) -> dict[str, Any]:
    """Fill the week containing `day` (default: today) with the algorithm's
    suggested sessions. Non-destructive: days you've already planned are left
    alone and reported as skipped."""
    view_day = _parse_date(day)
    snapshot_dict = await snapshot(None)
    ftp_watts = _resolved_ftp_watts(snapshot_dict)
    block_week = local_store.get_block_week()

    monday = view_day - timedelta(days=view_day.weekday())
    existing = local_store.planned_dates_in_week(monday.isoformat(), (monday + timedelta(days=6)).isoformat())

    result = plan_generator.generate_week(view_day, ftp_watts, block_week, existing)
    for date_str, workout in result["created"].items():
        local_store.save_planned_workout(date_str, workout)
    return result


# --- "Let my coach plan for me" — deterministic type catalog + day-planner ------


async def _weakest_coggan_zone() -> Optional[str]:
    snapshot_dict = await snapshot(None)
    ftp_watts = _resolved_ftp_watts(snapshot_dict)
    latest_weight = local_store.get_latest_weight()
    weight_kg = latest_weight[1] if latest_weight else None
    if not weight_kg:
        return None
    merged = power_curve.merged_curve()
    profile = coggan.build_profile(weight_kg, ftp_watts, {d: p["watts"] for d, p in merged.items()})
    return profile.get("weakest_zone")


def _nearest_race_gap_report() -> Optional[list[dict[str, Any]]]:
    """The soonest upcoming event with a computed demand profile, or None.
    Picking the nearest race (not just any) is deliberate: a shortfall against
    an event three months out is a lower-priority signal than one two weeks away."""
    events = sorted(
        (e for e in local_store.list_race_events() if e.get("date", "") >= date_.today().isoformat()),
        key=lambda e: e["date"],
    )
    for event in events:
        profile = local_store.get_demand_profile(event["id"])
        if profile and profile.get("gap_report"):
            return profile["gap_report"]
    return None


@app.get("/api/planned/workout-types")
async def workout_type_catalog() -> dict[str, Any]:
    """The catalog the day-planner UI offers — one place defines what a
    'type' is, per services/workout_types.py."""
    return {
        "types": [{"key": t, "label": workout_types.label_for(t)} for t in workout_types.WORKOUT_TYPES],
    }


class DayPlanRequest(BaseModel):
    workout_type: Optional[str] = None  # None = "decide for me"


@app.post("/api/planned/{plan_date}/coach-plan")
async def coach_plan_day(plan_date: str, payload: DayPlanRequest) -> dict[str, Any]:
    """The deterministic half of 'Let my coach plan for me': build a
    structured workout for this day, either the requested type or the type
    chosen from the athlete's biggest weakness + this week's current load.

    Returns a PREVIEW — nothing is saved here. The frontend shows the workout
    and its rationale/placement warning, and only PUTs it to /api/planned/{date}
    once the athlete confirms, same as every other visible-recommendation
    surface in this app (readiness advisory, adaptive periodization, reflow).
    """
    target_date = _parse_date(plan_date)
    snapshot_dict = await snapshot(None)
    ftp_watts = _resolved_ftp_watts(snapshot_dict)

    monday = target_date - timedelta(days=target_date.weekday())
    planned_this_week = local_store.get_planned_workouts(monday.isoformat(), (monday + timedelta(days=6)).isoformat())

    requested_type = payload.workout_type
    if requested_type is not None and requested_type not in workout_types.WORKOUT_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown workout type '{requested_type}'.")

    weakest = await _weakest_coggan_zone()
    gap_report = _nearest_race_gap_report()
    deterministic_type, deterministic_reason = (
        (requested_type, None) if requested_type else day_planner.decide_type(weakest, gap_report, planned_this_week)
    )

    # AI layer: re-ranks the deterministic pick (or explains an explicit
    # request) and writes a warmer rationale. Never blocks — any failure
    # (missing/invalid key, network error, unparseable response) falls back to
    # the deterministic type/reason untouched, which is why decide_type() ran
    # first and unconditionally above.
    week_summary = (
        ", ".join(f"{d}: {w.get('title')}" for d, w in sorted(planned_this_week.items())) or "nothing planned yet"
    )
    enriched = ai_day_planner.enrich(
        deterministic_type, deterministic_reason or "", week_summary, weakest, requested_type,
    )
    workout_type = enriched["type"]
    reason = enriched["reason"]

    generated = workout_types.build(workout_type, ftp_watts)
    placement_warning = day_planner.check_placement(target_date, planned_this_week, workout_type)

    return {
        "workout_type": workout_type,
        "reason": reason,
        "placement_warning": placement_warning,
        "ai_used": enriched["ai_used"],
        "ai_unavailable_message": enriched["ai_unavailable_message"],
        "workout": {
            "session_type": generated.session_type,
            "title": generated.title,
            "detail": generated.detail,
            "duration_min": generated.duration_min,
            "target_watts_low": generated.target_watts_low,
            "target_watts_high": generated.target_watts_high,
            "steps": generated.steps,
            "source": "coach",
        },
    }


def _option_payload(option: day_planner.SuggestedOption) -> dict[str, Any]:
    """One suggestion, serialized.

    `workout` is a complete PlannedWorkoutModel body on purpose: "add to
    calendar" is then a plain PUT /api/planned/{date} of exactly what was
    previewed, with no second endpoint that could drift from what the athlete
    was actually shown.
    """
    return {
        "kind": option.kind,
        "exclusive_with": option.exclusive_with,
        "workout_type": option.workout_type,
        "title": option.title,
        "detail": option.detail,
        "reason": option.reason,
        "duration_min": option.duration_min,
        "placement_warning": option.placement_warning,
        "strength_focus": option.strength_focus,
        "strength_log_type": option.strength_log_type,
        "workout": {
            "session_type": option.session_type,
            "title": option.title,
            "detail": option.detail,
            "duration_min": option.duration_min,
            "target_watts_low": option.target_watts_low,
            "target_watts_high": option.target_watts_high,
            "steps": option.steps,
            "source": "coach",
            "strength_log_type": option.strength_log_type,
        },
    }


@app.get("/api/planned/{plan_date}/suggestions")
async def day_suggestions(plan_date: str, ai: bool = False) -> dict[str, Any]:
    """"What should I do today?" — three options for one day.

    Deterministic by default. `ai=true` lets the AI layer rewrite the leading
    option's rationale in the coach's voice; it can only re-rank within the
    existing catalog and never invents a type, so the three options are the
    same three either way. Everything still works with the Anthropic key
    invalid, which is the whole reason the deterministic layer exists.

    Returns previews only — nothing is saved until the athlete PUTs one.
    """
    target_date = _parse_date(plan_date)
    snapshot_dict = await snapshot(plan_date)
    ftp_watts = _resolved_ftp_watts(snapshot_dict)

    monday = target_date - timedelta(days=target_date.weekday())
    planned_this_week = local_store.get_planned_workouts(
        monday.isoformat(), (monday + timedelta(days=6)).isoformat()
    )

    snapshot_obj = DailyHealthSnapshot.model_validate(snapshot_dict)
    travel_window = travel_window_for(target_date, local_store.get_constraints())
    traveling_note = f"{travel_window['start']} to {travel_window['end']}" if travel_window else None
    verdict = compute_verdict(snapshot_obj, target_date, traveling_note)

    weakest = await _weakest_coggan_zone()
    gap_report = _nearest_race_gap_report()
    options = day_planner.compose_three_options(
        weakest, gap_report, planned_this_week, verdict.verdict, target_date, ftp_watts,
    )

    ai_used, ai_message = False, None
    if ai:
        # Only the leading bike option is enriched. The other two exist to give
        # the athlete a real choice; letting the AI re-pick them as well would
        # let it collapse three options into variations on one.
        lead = next((o for o in options if o.kind == "bike" and o.workout_type), None)
        if lead is not None:
            week_summary = (
                ", ".join(f"{d}: {w.get('title')}" for d, w in sorted(planned_this_week.items()))
                or "nothing planned yet"
            )
            # This is a real Anthropic call (multiple seconds) for one line of
            # rewritten prose. Cached by everything the prompt actually depends
            # on, so re-opening the same day's suggestions doesn't re-pay that
            # cost — same TTL as the rest of today's data, since the inputs
            # (readiness, this week's sessions) can change during the day.
            cache_key = f"ai_daysuggest:{target_date.isoformat()}:{lead.workout_type}:{weakest}:{week_summary}"
            cached_ai = local_store.get_cached_query(cache_key)
            # A successful enrichment is cached for the rest of today's TTL; a
            # FAILED one (invalid key, network error, rate limit) is cached only
            # briefly — long enough that repeatedly clicking "write this up"
            # with a broken key doesn't re-pay a multi-second failed network
            # round trip each time, short enough that fixing the key during the
            # day starts working again without a backend restart.
            cache_ttl = _TODAY_TTL_SECONDS if (cached_ai and cached_ai.get("ai_used")) else 60
            if cached_ai and time.time() - cached_ai.get("cached_at", 0) < cache_ttl:
                enriched = cached_ai
            else:
                enriched = ai_day_planner.enrich(
                    lead.workout_type, lead.reason, week_summary, weakest, lead.workout_type,
                )
                local_store.cache_query(cache_key, enriched)
            ai_used = enriched["ai_used"]
            ai_message = enriched["ai_unavailable_message"]
            if ai_used:
                lead.reason = enriched["reason"]

    return {
        "date": target_date.isoformat(),
        "weakest_zone": weakest,
        "weakest_zone_caveat": day_planner.soft_row_caveat(weakest),
        "readiness_verdict": verdict.verdict,
        "traveling": traveling_note,
        "ai_used": ai_used,
        "ai_unavailable_message": ai_message,
        "options": [_option_payload(o) for o in options],
    }


@app.get("/api/coggan-profile")
async def coggan_profile_endpoint(date: Optional[str] = None) -> dict[str, Any]:
    snapshot_dict = await snapshot(date)
    ftp_watts = _resolved_ftp_watts(snapshot_dict)
    latest_weight = local_store.get_latest_weight()
    weight_kg = latest_weight[1] if latest_weight else None
    merged = power_curve.merged_curve()
    watts_by_duration = {d: p["watts"] for d, p in merged.items()}
    profile = coggan.build_profile(weight_kg, ftp_watts, watts_by_duration)
    profile["curve"] = coggan.build_curve(weight_kg, ftp_watts, watts_by_duration)
    profile["curve"]["provenance"] = {str(d): p for d, p in merged.items()}

    # Time-windowed series for the power-profile grid. Recent windows are
    # measured-rides-only: the self-reported config bests carry no date, so
    # they can't honestly be attributed to "the last 42 days" — only All time
    # can include them. That asymmetry is surfaced in the grid's legend rather
    # than papered over.
    today = date_.today()
    exclusions = local_store.get_power_exclusions()
    rides = power_curve.cached_rides()
    windows: dict[str, dict[int, float]] = {}
    for label, days in (("42 days", 42), ("84 days", 84)):
        cutoff = (today - timedelta(days=days)).isoformat()
        recent = [r for r in rides if r.get("date") and r["date"] >= cutoff]
        curve = power_curve.all_time_curve(recent, exclusions)
        windows[label] = {d: p["watts"] for d, p in curve.items() if p.get("reliable")}
    windows["All time"] = watts_by_duration

    profile["grid"] = coggan.build_grid(weight_kg, ftp_watts, windows)
    profile["grid"]["window_note"] = (
        "42/84-day windows come from rides this app has cached samples for; All time also includes your "
        "self-reported career bests, which carry no date and so can't be windowed."
    )
    profile["rider_type"] = rider_profile.classify(ftp_watts)
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


@app.get("/api/undo-log")
async def undo_log() -> list[dict[str, Any]]:
    return local_store.list_undo_log()


@app.post("/api/undo-log/{undo_id}/restore")
async def restore_undo(undo_id: str) -> dict[str, Any]:
    restored = local_store.restore_from_undo(undo_id)
    if restored is None:
        raise HTTPException(status_code=404, detail="Nothing to restore — already restored, or too old.")
    return {"ok": True, "item": restored}


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
    # Recording device IDs (Garmin's real deviceId) this gear auto-claims,
    # checked before default_for_types. Identifies the watch/head unit used,
    # not the bike — only useful if device usage happens to correlate with
    # which bike you ride. See services/gear.py.
    default_for_device_ids: list[str] = []
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
    # Optional cadence target — most steps have none (power is the target and
    # cadence is free), but overgearing/torque work is defined BY its cadence:
    # same %FTP as a threshold interval, distinguished only by pedaling slow.
    # Nullable and defaulted so every existing stored/exported workout is
    # unaffected; only new overgearing-type steps populate it.
    cadence_low_rpm: Optional[int] = None
    cadence_high_rpm: Optional[int] = None


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


@app.post("/api/coach/chat/stream")
async def coach_chat_stream(req: ChatRequest, date: Optional[str] = None) -> StreamingResponse:
    """Server-sent events carrying Claude's reply as it's generated.

    The non-streaming /api/coach/chat stays as-is: it's what the ride-debrief
    and analyze-day paths use, and it's the fallback the chat UI drops to if
    this stream fails, so a streaming problem degrades to a working chat rather
    than a broken one.
    """
    snapshot_dict = await snapshot(date)
    snapshot_obj = DailyHealthSnapshot.model_validate(snapshot_dict)
    latest = local_store.get_latest_weight()
    weight_kg = latest[1] if latest else None
    history = [{"role": m.role, "content": m.content} for m in req.messages]

    async def events():
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def produce():
            # The Anthropic SDK's stream is blocking, so it runs off the event
            # loop and hands deltas back through the queue.
            try:
                for delta in claude_analyzer.chat_reply_stream(history, snapshot_obj, weight_kg):
                    loop.call_soon_threadsafe(queue.put_nowait, {"delta": delta})
            except Exception as exc:
                loop.call_soon_threadsafe(queue.put_nowait, {"error": str(exc)})
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        asyncio.get_running_loop().run_in_executor(None, produce)
        while True:
            item = await queue.get()
            if item is None:
                break
            yield f"data: {json.dumps(item)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
