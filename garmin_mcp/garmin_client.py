"""Stdio MCP client for the @nicolasvegam/garmin-connect-mcp server.

Tool names and response shapes below were verified live against a real
Garmin account (see garmin_mcp/schemas.py docstring) — several tools return
lists instead of single objects, and require date *ranges* rather than a
single date. Re-verify with `--call <tool>` if you ever switch servers.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from contextlib import AsyncExitStack
from datetime import date as date_, timedelta
from typing import Any, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from config.settings import settings
from garmin_mcp.schemas import (
    BodyBatteryData,
    CyclingFTPData,
    DailyHealthSnapshot,
    EnduranceScoreData,
    HRVData,
    LactateThresholdData,
    RespirationData,
    RestingHeartRateData,
    SleepData,
    StressData,
    TrainingLoadData,
    TrainingReadinessData,
    VO2MaxData,
    WeightData,
)

logger = logging.getLogger(__name__)

# Verified against github.com/Nicolasvegam/garmin-connect-mcp — confirm again with
# --list-tools if you switch servers, since these names aren't part of any MCP standard.
TOOL_HRV = "get_hrv"
TOOL_RESTING_HR = "get_resting_heart_rate"
TOOL_SLEEP = "get_sleep_data"
TOOL_BODY_BATTERY = "get_body_battery"
TOOL_TRAINING_STATUS = "get_training_status"
TOOL_TRAINING_READINESS = "get_training_readiness"
TOOL_WEIGHT = "get_daily_weigh_ins"
TOOL_RESPIRATION = "get_respiration"
TOOL_STRESS = "get_stress"
TOOL_CYCLING_FTP = "get_cycling_ftp"
TOOL_LACTATE_THRESHOLD = "get_lactate_threshold"
TOOL_HRV_RANGE = "get_hrv_range"
TOOL_TRAINING_READINESS_RANGE = "get_training_readiness_range"
TOOL_ENDURANCE_SCORE = "get_endurance_score"
TOOL_ACTIVITIES = "get_activities"
TOOL_ACTIVITY_SPLITS = "get_activity_splits"
TOOL_ACTIVITY_DETAILS = "get_activity_details"


class GarminMCPClient:
    """Async context manager wrapping a single stdio MCP session."""

    def __init__(
        self,
        command: Optional[str] = None,
        args: Optional[list[str]] = None,
        env: Optional[dict[str, str]] = None,
    ) -> None:
        self._command = command or settings.garmin_mcp_command
        self._args = args if args is not None else settings.garmin_mcp_args_list
        self._env = env if env is not None else settings.garmin_mcp_env
        self._session: Optional[ClientSession] = None
        self._exit_stack = AsyncExitStack()

    async def __aenter__(self) -> "GarminMCPClient":
        await self.connect()
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.close()

    async def connect(self) -> None:
        server_params = StdioServerParameters(command=self._command, args=self._args, env=self._env)
        read, write = await self._exit_stack.enter_async_context(stdio_client(server_params))
        self._session = await self._exit_stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        logger.info("Connected to Garmin MCP server: %s %s", self._command, " ".join(self._args))

    async def close(self) -> None:
        await self._exit_stack.aclose()
        self._session = None

    async def list_tools(self) -> list[str]:
        assert self._session is not None, "call connect() first"
        result = await self._session.list_tools()
        return [tool.name for tool in result.tools]

    async def _call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        if self._session is None:
            raise RuntimeError("Not connected — use `async with GarminMCPClient() as client:`")
        result = await self._session.call_tool(tool_name, arguments)
        if result.isError:
            raise RuntimeError(f"MCP tool '{tool_name}' returned an error: {result.content}")
        return self._extract_json(result.content)

    @staticmethod
    def _extract_json(content: list[Any]) -> Any:
        for block in content:
            if getattr(block, "type", None) == "text":
                try:
                    return json.loads(block.text)
                except json.JSONDecodeError:
                    continue
        raise ValueError("Tool result did not contain parseable JSON text content")

    async def get_hrv(self, for_date: Optional[date_] = None) -> HRVData:
        for_date = for_date or date_.today()
        data = await self._call_tool(TOOL_HRV, {"date": for_date.isoformat()})
        summary = data.get("hrvSummary") or {}
        baseline = summary.get("baseline") or {}
        return HRVData(
            date=for_date,
            last_night_avg_ms=summary.get("lastNightAvg"),
            last_night_high_ms=summary.get("lastNight5MinHigh"),
            weekly_avg_ms=summary.get("weeklyAvg"),
            baseline_low_ms=baseline.get("balancedLow"),
            baseline_high_ms=baseline.get("balancedUpper"),
            status=summary.get("status"),
        )

    async def get_resting_heart_rate(self, for_date: Optional[date_] = None) -> RestingHeartRateData:
        for_date = for_date or date_.today()
        data = await self._call_tool(TOOL_RESTING_HR, {"date": for_date.isoformat()})
        readings = ((data.get("allMetrics") or {}).get("metricsMap") or {}).get(
            "WELLNESS_RESTING_HEART_RATE"
        ) or []
        # This endpoint has no built-in 7-day average — left None here; compute it
        # client-side once local history accumulates (see database/local_store.py).
        return RestingHeartRateData(
            date=for_date,
            resting_hr_bpm=readings[-1]["value"] if readings else None,
            seven_day_avg_bpm=None,
        )

    async def get_sleep(self, for_date: Optional[date_] = None) -> SleepData:
        for_date = for_date or date_.today()
        data = await self._call_tool(TOOL_SLEEP, {"date": for_date.isoformat()})
        dto = data.get("dailySleepDTO") or {}
        overall_score = ((dto.get("sleepScores") or {}).get("overall") or {}).get("value")
        return SleepData(
            date=for_date,
            sleep_score=overall_score,
            total_sleep_seconds=dto.get("sleepTimeSeconds"),
            deep_sleep_seconds=dto.get("deepSleepSeconds"),
            light_sleep_seconds=dto.get("lightSleepSeconds"),
            rem_sleep_seconds=dto.get("remSleepSeconds"),
            awake_seconds=dto.get("awakeSleepSeconds"),
            avg_sleep_stress=dto.get("avgSleepStress"),
            resting_hr_during_sleep=data.get("restingHeartRate"),
        )

    async def get_body_battery(self, for_date: Optional[date_] = None) -> BodyBatteryData:
        for_date = for_date or date_.today()
        data = await self._call_tool(
            TOOL_BODY_BATTERY, {"startDate": for_date.isoformat(), "endDate": for_date.isoformat()}
        )
        entry = data[0] if isinstance(data, list) and data else {}
        return BodyBatteryData(date=for_date, charged=entry.get("charged"), drained=entry.get("drained"))

    async def get_training_load(self, for_date: Optional[date_] = None) -> TrainingLoadData:
        for_date = for_date or date_.today()
        data = await self._call_tool(TOOL_TRAINING_STATUS, {"date": for_date.isoformat()})
        latest_by_device = ((data.get("mostRecentTrainingStatus") or {}).get("latestTrainingStatusData") or {})
        device_status = next(iter(latest_by_device.values()), {})
        acute_dto = device_status.get("acuteTrainingLoadDTO") or {}
        phrase = device_status.get("trainingStatusFeedbackPhrase")
        status = phrase.rsplit("_", 1)[0] if phrase and phrase.rsplit("_", 1)[-1].isdigit() else phrase
        return TrainingLoadData(
            date=for_date,
            acute_load=acute_dto.get("dailyTrainingLoadAcute"),
            chronic_load=acute_dto.get("dailyTrainingLoadChronic"),
            acwr=acute_dto.get("dailyAcuteChronicWorkloadRatio"),
            acwr_status=acute_dto.get("acwrStatus"),
            status=status,
        )

    async def get_vo2_max(self, for_date: Optional[date_] = None) -> VO2MaxData:
        """Sourced from get_training_status's mostRecentVO2Max — the standalone get_vo2max
        tool filters strictly by date and is usually empty since VO2max only updates
        periodically, not daily."""
        for_date = for_date or date_.today()
        data = await self._call_tool(TOOL_TRAINING_STATUS, {"date": for_date.isoformat()})
        vo2 = data.get("mostRecentVO2Max") or {}
        generic = vo2.get("generic") or {}
        cycling = vo2.get("cycling") or {}
        return VO2MaxData(
            date=for_date,
            vo2_max_cycling=cycling.get("vo2MaxPreciseValue") or cycling.get("vo2MaxValue"),
            vo2_max_generic=generic.get("vo2MaxPreciseValue") or generic.get("vo2MaxValue"),
            fitness_age=generic.get("fitnessAge"),
        )

    async def get_training_readiness(self, for_date: Optional[date_] = None) -> TrainingReadinessData:
        for_date = for_date or date_.today()
        data = await self._call_tool(TOOL_TRAINING_READINESS, {"date": for_date.isoformat()})
        # Returns a list of intraday readings (most recent first); take the latest.
        latest = data[0] if isinstance(data, list) and data else {}
        return TrainingReadinessData(
            date=for_date,
            readiness_score=latest.get("score"),
            level=latest.get("level"),
            feedback=latest.get("feedbackShort") or latest.get("feedbackLong"),
            sleep_score=latest.get("sleepScore"),
            hrv_weekly_average=latest.get("hrvWeeklyAverage"),
            acute_load=latest.get("acuteLoad"),
        )

    async def get_weight(self, for_date: Optional[date_] = None) -> WeightData:
        for_date = for_date or date_.today()
        data = await self._call_tool(TOOL_WEIGHT, {"date": for_date.isoformat()})
        entries = data.get("dateWeightList") or []
        if entries:
            entry = entries[-1]
        else:
            total_avg = data.get("totalAverage") or {}
            entry = total_avg if total_avg.get("weight") is not None else None
        if entry is None:
            raise ValueError(f"No weigh-in recorded in Garmin Connect for/near {for_date}")
        raw_weight = entry["weight"]
        # Garmin's raw API reports weight in grams; convert if the value is implausible as kg.
        weight_kg = raw_weight / 1000 if raw_weight > 300 else raw_weight
        return WeightData(
            date=for_date,
            weight_kg=weight_kg,
            bmi=entry.get("bmi"),
            body_fat_percent=entry.get("bodyFat"),
            muscle_mass_kg=(entry.get("muscleMass") / 1000 if entry.get("muscleMass") else None),
        )

    async def get_respiration(self, for_date: Optional[date_] = None) -> RespirationData:
        for_date = for_date or date_.today()
        data = await self._call_tool(TOOL_RESPIRATION, {"date": for_date.isoformat()})
        return RespirationData(
            date=for_date,
            avg_waking_breaths_per_min=data.get("avgWakingRespirationValue"),
            avg_sleep_breaths_per_min=data.get("avgSleepRespirationValue"),
            lowest_breaths_per_min=data.get("lowestRespirationValue"),
            highest_breaths_per_min=data.get("highestRespirationValue"),
        )

    async def get_stress(self, for_date: Optional[date_] = None) -> StressData:
        for_date = for_date or date_.today()
        data = await self._call_tool(TOOL_STRESS, {"date": for_date.isoformat()})
        return StressData(
            date=for_date,
            avg_stress_level=data.get("avgStressLevel"),
            max_stress_level=data.get("maxStressLevel"),
        )

    async def get_cycling_ftp(self, for_date: Optional[date_] = None) -> CyclingFTPData:
        for_date = for_date or date_.today()
        data = await self._call_tool(TOOL_CYCLING_FTP, {})
        return CyclingFTPData(
            date=for_date,
            ftp_watts=data.get("functionalThresholdPower"),
            source=data.get("biometricSourceType"),
        )

    async def get_lactate_threshold(self, for_date: Optional[date_] = None) -> LactateThresholdData:
        """Current-value-only, like cycling_ftp — the date arg doesn't filter
        history. Response is a list of records per activity type; we want the
        one with heartRateCycling set (note Garmin's real field is genuinely
        spelled "hearRate" for the running variant)."""
        for_date = for_date or date_.today()
        data = await self._call_tool(TOOL_LACTATE_THRESHOLD, {"date": for_date.isoformat()})
        cycling_entry = next((r for r in (data or []) if r.get("heartRateCycling") is not None), {})
        return LactateThresholdData(date=for_date, threshold_hr_cycling=cycling_entry.get("heartRateCycling"))

    async def get_endurance_score(self, for_date: Optional[date_] = None, window_days: int = 6) -> EnduranceScoreData:
        """Returned null on this account during testing (2026-07-13) — see
        EnduranceScoreData docstring. `avg` is the best-guess field name."""
        for_date = for_date or date_.today()
        start = for_date - timedelta(days=window_days)
        data = await self._call_tool(
            TOOL_ENDURANCE_SCORE, {"startDate": start.isoformat(), "endDate": for_date.isoformat()}
        )
        return EnduranceScoreData(date=for_date, score=data.get("avg"))

    async def get_activities(self, limit: int = 20) -> list[dict[str, Any]]:
        """Summary list for the workout history browser. Outdoor rides have no
        power fields (no power meter yet); indoor_cycling activities (KICKR) do."""
        data = await self._call_tool(TOOL_ACTIVITIES, {"limit": limit})
        records = []
        for a in data or []:
            records.append(
                {
                    "activity_id": a.get("activityId"),
                    "name": a.get("activityName"),
                    "type": (a.get("activityType") or {}).get("typeKey"),
                    "start_time_local": a.get("startTimeLocal"),
                    "duration_sec": a.get("duration"),
                    "distance_m": a.get("distance"),
                    "avg_hr": a.get("averageHR"),
                    "max_hr": a.get("maxHR"),
                    "calories": a.get("calories"),
                    "elevation_gain_m": a.get("elevationGain"),
                    "avg_power_w": a.get("avgPower"),
                    "max_power_w": a.get("maxPower"),
                    "norm_power_w": a.get("normPower"),
                    # Recording device, not the bike itself — verified against
                    # real data that the same device (e.g. a watch/head unit)
                    # records both indoor KICKR sessions and outdoor rides, so
                    # this can't reliably mean "which bike." Still a real,
                    # useful optional signal if your device usage happens to
                    # correlate with which bike you ride.
                    "device_id": a.get("deviceId"),
                }
            )
        return records

    async def get_activity_details(self, activity_id: int) -> list[dict[str, Any]]:
        """Raw per-sample time series for the ride-segment selector. Verified shape:
        metricDescriptors defines a {key: index} column map, activityDetailMetrics is
        a list of {"metrics": [values...]} rows indexed by that map. Field availability
        differs indoor (directPower/directBikeCadence, no GPS) vs outdoor (directElevation/
        directLatitude/directLongitude, no power without a meter)."""
        data = await self._call_tool(TOOL_ACTIVITY_DETAILS, {"activityId": activity_id})
        descriptors = data.get("metricDescriptors") or []
        index_of = {d["key"]: d["metricsIndex"] for d in descriptors}

        def _get(vals: list[Any], key: str) -> Optional[float]:
            idx = index_of.get(key)
            return vals[idx] if idx is not None and idx < len(vals) else None

        samples = []
        for row in data.get("activityDetailMetrics") or []:
            vals = row.get("metrics") or []
            samples.append(
                {
                    "elapsed_sec": _get(vals, "sumElapsedDuration"),
                    "distance_m": _get(vals, "sumDistance"),
                    "power_w": _get(vals, "directPower"),
                    "hr_bpm": _get(vals, "directHeartRate"),
                    "speed_mps": _get(vals, "directSpeed"),
                    "elevation_m": _get(vals, "directElevation"),
                    "cadence_rpm": _get(vals, "directBikeCadence"),
                    "lat": _get(vals, "directLatitude"),
                    "lon": _get(vals, "directLongitude"),
                }
            )
        return samples

    async def get_activity_splits(self, activity_id: int) -> list[dict[str, Any]]:
        """Lap-level summaries — a coarser complement to get_activity_details."""
        data = await self._call_tool(TOOL_ACTIVITY_SPLITS, {"activityId": activity_id})
        laps = (data or {}).get("lapDTOs") or []
        return [
            {
                "lap_index": lap.get("lapIndex"),
                "duration_sec": lap.get("duration"),
                "distance_m": lap.get("distance"),
                "avg_power_w": lap.get("averagePower"),
                "max_power_w": lap.get("maxPower"),
                "norm_power_w": lap.get("normalizedPower"),
                "avg_hr": lap.get("averageHR"),
                "max_hr": lap.get("maxHR"),
                "avg_speed_mps": lap.get("averageSpeed"),
            }
            for lap in laps
        ]

    async def get_hrv_history(
        self, days: int = 30, start_date: Optional[date_] = None, end_date: Optional[date_] = None
    ) -> list[dict[str, Any]]:
        """For the Trends tab's rolling HRV baseline chart. Pass start_date/end_date for an
        explicit range (e.g. from a calendar picker), or just `days` for a "last N days" window."""
        end = end_date or date_.today()
        start = start_date or (end - timedelta(days=days))
        data = await self._call_tool(TOOL_HRV_RANGE, {"startDate": start.isoformat(), "endDate": end.isoformat()})
        records = []
        for day in data or []:
            summary = ((day.get("data") or {}).get("hrvSummary")) or {}
            baseline = summary.get("baseline") or {}
            records.append(
                {
                    "date": day.get("date"),
                    "last_night_avg_ms": summary.get("lastNightAvg"),
                    "weekly_avg_ms": summary.get("weeklyAvg"),
                    "baseline_low_ms": baseline.get("balancedLow"),
                    "baseline_high_ms": baseline.get("balancedUpper"),
                }
            )
        return records

    async def get_training_readiness_history(
        self, days: int = 30, start_date: Optional[date_] = None, end_date: Optional[date_] = None
    ) -> list[dict[str, Any]]:
        """For the Trends tab's readiness score trend. Pass start_date/end_date for an
        explicit range, or just `days` for a "last N days" window."""
        end = end_date or date_.today()
        start = start_date or (end - timedelta(days=days))
        data = await self._call_tool(
            TOOL_TRAINING_READINESS_RANGE, {"startDate": start.isoformat(), "endDate": end.isoformat()}
        )
        records = []
        for day in data or []:
            readings = day.get("data") or []
            latest = readings[0] if readings else {}
            records.append(
                {"date": day.get("date"), "readiness_score": latest.get("score"), "level": latest.get("level")}
            )
        return records

    async def get_daily_snapshot(self, for_date: Optional[date_] = None) -> DailyHealthSnapshot:
        """Fetch every metric for one date, degrading gracefully per-metric on failure."""
        for_date = for_date or date_.today()
        fetchers = {
            "hrv": self.get_hrv,
            "resting_heart_rate": self.get_resting_heart_rate,
            "sleep": self.get_sleep,
            "body_battery": self.get_body_battery,
            "training_load": self.get_training_load,
            "vo2_max": self.get_vo2_max,
            "training_readiness": self.get_training_readiness,
            "weight": self.get_weight,
            "respiration": self.get_respiration,
            "stress": self.get_stress,
            "cycling_ftp": self.get_cycling_ftp,
            "endurance_score": self.get_endurance_score,
            "lactate_threshold": self.get_lactate_threshold,
        }
        results = await asyncio.gather(
            *(fn(for_date) for fn in fetchers.values()), return_exceptions=True
        )

        snapshot_fields: dict[str, Any] = {"date": for_date}
        for field_name, result in zip(fetchers.keys(), results):
            if isinstance(result, Exception):
                logger.warning("Failed to fetch '%s' for %s: %s", field_name, for_date, result)
                snapshot_fields[field_name] = None
            else:
                snapshot_fields[field_name] = result
        return DailyHealthSnapshot.model_validate(snapshot_fields)


async def _main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Manually exercise the Garmin MCP client")
    parser.add_argument("--list-tools", action="store_true", help="Print available tool names, then exit")
    parser.add_argument(
        "--call", type=str, default=None,
        help="Call a raw tool by name and print its UNPARSED JSON — use this to inspect the "
        "real response shape before trusting the Pydantic field mapping in this file",
    )
    parser.add_argument("--date", type=str, default=None, help="ISO date to fetch (default: today)")
    args = parser.parse_args()

    for_date = date_.fromisoformat(args.date) if args.date else None

    async with GarminMCPClient() as client:
        if args.list_tools:
            print("Available MCP tools on this server:")
            for name in await client.list_tools():
                print(f"  - {name}")
            return

        if args.call:
            raw = await client._call_tool(args.call, {"date": (for_date or date_.today()).isoformat()})
            print(json.dumps(raw, indent=2))
            return

        snapshot = await client.get_daily_snapshot(for_date)
        print(snapshot.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
