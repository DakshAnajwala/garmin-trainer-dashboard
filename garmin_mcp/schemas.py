"""Pydantic models for Garmin Connect health & training metrics.

Nearly every field is Optional because Garmin data has real gaps (no HRV
without a compatible device overnight, no VO2 max update that day, a rest
day with no training load, etc). Consumers must handle `None`, not assume
every field is populated.

Status/level fields are plain strings, not enums — real data returned values
(e.g. "STRAINED_4") that weren't in the enum guessed before live verification,
so these are deliberately left free-form rather than risk validation crashes.
"""
from __future__ import annotations

from datetime import date as date_
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class HRVData(BaseModel):
    date: date_
    last_night_avg_ms: Optional[int] = Field(default=None, description="Last night's average overnight HRV, ms")
    last_night_high_ms: Optional[int] = None
    weekly_avg_ms: Optional[int] = None
    baseline_low_ms: Optional[int] = None
    baseline_high_ms: Optional[int] = None
    status: Optional[str] = None


class RestingHeartRateData(BaseModel):
    date: date_
    resting_hr_bpm: Optional[int] = Field(default=None, ge=25, le=120)
    seven_day_avg_bpm: Optional[int] = Field(default=None, ge=25, le=120)


class SleepData(BaseModel):
    date: date_
    sleep_score: Optional[int] = Field(default=None, ge=0, le=100)
    total_sleep_seconds: Optional[int] = Field(default=None, ge=0)
    deep_sleep_seconds: Optional[int] = Field(default=None, ge=0)
    light_sleep_seconds: Optional[int] = Field(default=None, ge=0)
    rem_sleep_seconds: Optional[int] = Field(default=None, ge=0)
    awake_seconds: Optional[int] = Field(default=None, ge=0)
    avg_sleep_stress: Optional[int] = None
    resting_hr_during_sleep: Optional[int] = None

    @property
    def total_sleep_hours(self) -> Optional[float]:
        return round(self.total_sleep_seconds / 3600, 2) if self.total_sleep_seconds is not None else None


class BodyBatteryData(BaseModel):
    date: date_
    charged: Optional[int] = Field(default=None, ge=0, le=100)
    drained: Optional[int] = Field(default=None, ge=0, le=100)


class TrainingLoadData(BaseModel):
    date: date_
    acute_load: Optional[float] = Field(default=None, ge=0, description="Garmin's daily acute training load")
    chronic_load: Optional[float] = Field(default=None, ge=0, description="Garmin's daily chronic training load")
    acwr: Optional[float] = Field(default=None, ge=0, description="Acute:chronic workload ratio")
    acwr_status: Optional[str] = None
    status: Optional[str] = Field(default=None, description="Garmin's training status feedback phrase, e.g. STRAINED")

    @field_validator("acwr")
    @classmethod
    def _sanity_check_acwr(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v > 5:
            raise ValueError("ACWR > 5 is almost certainly a unit/parse error, not real training data")
        return v


class VO2MaxData(BaseModel):
    date: date_
    vo2_max_cycling: Optional[float] = Field(default=None, ge=20, le=90)
    vo2_max_generic: Optional[float] = Field(default=None, ge=20, le=90)
    fitness_age: Optional[int] = Field(default=None, ge=10, le=100)


class TrainingReadinessData(BaseModel):
    date: date_
    readiness_score: Optional[int] = Field(default=None, ge=0, le=100)
    level: Optional[str] = None
    feedback: Optional[str] = None
    sleep_score: Optional[int] = None
    hrv_weekly_average: Optional[int] = None
    acute_load: Optional[float] = None


class WeightData(BaseModel):
    """A single weigh-in. Central to dynamic W/kg tracking — this is the denominator."""

    date: date_
    weight_kg: float = Field(ge=25, le=200)
    bmi: Optional[float] = None
    body_fat_percent: Optional[float] = Field(default=None, ge=0, le=70)
    muscle_mass_kg: Optional[float] = None


class RespirationData(BaseModel):
    date: date_
    avg_waking_breaths_per_min: Optional[float] = Field(default=None, ge=4, le=40)
    avg_sleep_breaths_per_min: Optional[float] = Field(default=None, ge=4, le=40)
    lowest_breaths_per_min: Optional[float] = Field(default=None, ge=4, le=40)
    highest_breaths_per_min: Optional[float] = Field(default=None, ge=4, le=40)


class StressData(BaseModel):
    date: date_
    avg_stress_level: Optional[int] = Field(default=None, ge=-1, le=100)
    max_stress_level: Optional[int] = Field(default=None, ge=-1, le=100)


class CyclingFTPData(BaseModel):
    """Garmin's own auto-detected FTP estimate — a cross-check against manual 20min tests."""

    date: date_
    ftp_watts: Optional[float] = Field(default=None, ge=50, le=600)
    source: Optional[str] = Field(default=None, description="Garmin's biometricSourceType, e.g. CHANGE_LOG")


class EnduranceScoreData(BaseModel):
    """Garmin's endurance score. Returned null for this account during initial
    testing (2026-07-13) — field mapping (`avg`) is a best guess from the one
    shape observed; re-verify with --call once Garmin populates real data."""

    date: date_
    score: Optional[float] = Field(default=None, ge=0, le=1000)


class LactateThresholdData(BaseModel):
    """Garmin's current cycling lactate-threshold HR estimate — a "current value
    only" endpoint like cycling_ftp, not a historical range. Note the source
    field is genuinely spelled "hearRate" (missing t) in Garmin's raw API."""

    date: date_
    threshold_hr_cycling: Optional[int] = Field(default=None, ge=80, le=220)


class DailyHealthSnapshot(BaseModel):
    """Everything pulled for a single calendar date, bundled for the dashboard/coach."""

    date: date_
    hrv: Optional[HRVData] = None
    resting_heart_rate: Optional[RestingHeartRateData] = None
    sleep: Optional[SleepData] = None
    body_battery: Optional[BodyBatteryData] = None
    training_load: Optional[TrainingLoadData] = None
    vo2_max: Optional[VO2MaxData] = None
    training_readiness: Optional[TrainingReadinessData] = None
    weight: Optional[WeightData] = None
    respiration: Optional[RespirationData] = None
    stress: Optional[StressData] = None
    cycling_ftp: Optional[CyclingFTPData] = None
    endurance_score: Optional[EnduranceScoreData] = None
    lactate_threshold: Optional[LactateThresholdData] = None
