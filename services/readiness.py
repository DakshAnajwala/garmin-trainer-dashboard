"""Rule-based train/rest recommendation.

Built on top of Garmin's own Training Readiness score (which already factors
HRV, sleep, recovery time, ACWR, stress history) rather than reinventing that
scoring — the value added here is layering this specific athlete's fixed
weekly schedule and limiter (1-5min power) on top of Garmin's number.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_
from typing import Optional

from garmin_mcp.schemas import DailyHealthSnapshot

# date.weekday(): Monday=0 ... Sunday=6
WEEKLY_SCHEDULE = {
    0: "Full rest day",
    1: "Base or a fast ride, depending on feel",
    2: "Intervals — VO2max/anaerobic/over-unders (your limiter-focus day)",
    3: "Base",
    4: "Easy base or full rest",
    5: "Long base = your non-negotiable team ride (steady effort)",
    6: "Long ride (4-4.5h) incl. a 90min all-out block ~45kph",
}
NON_NEGOTIABLE_WEEKDAY = 5  # Saturday
LIMITER_WEEKDAY = 2  # Wednesday


@dataclass
class ReadinessVerdict:
    verdict: str  # "REST" | "EASY" | "TRAIN" | "HARD" | "UNKNOWN"
    color: str
    headline: str
    detail: str
    scheduled_session: str


def compute_verdict(
    snapshot: DailyHealthSnapshot, for_date: Optional[date_] = None, traveling_note: Optional[str] = None
) -> ReadinessVerdict:
    for_date = for_date or snapshot.date
    weekday = for_date.weekday()
    scheduled_session = WEEKLY_SCHEDULE.get(weekday, "Unscheduled")

    readiness = snapshot.training_readiness
    score = readiness.readiness_score if readiness else None

    if score is None:
        verdict, color, headline = "UNKNOWN", "gray", "No readiness data yet"
        detail = "Garmin hasn't produced a Training Readiness score for today — check back once your watch syncs."
    elif score < 25:
        verdict, color, headline = "REST", "red", "Recovery day — back off"
        detail = _fatigue_detail(snapshot)
    elif score < 50:
        verdict, color, headline = "EASY", "orange", "Keep it easy today"
        detail = _fatigue_detail(snapshot)
    elif score < 75:
        verdict, color, headline = "TRAIN", "green", "Good to train as planned"
        detail = "Readiness looks solid — proceed with today's scheduled session."
    else:
        verdict, color, headline = "HARD", "green", "Green light for a hard/key session"
        detail = "Readiness is high — a good day to push the limiter (1-5min power) if that's on the plan."

    if weekday == NON_NEGOTIABLE_WEEKDAY and verdict in ("REST", "EASY"):
        detail += (
            " Your Saturday team ride is non-negotiable — don't skip it. Instead: sit in more, "
            "avoid pulling on the front, skip optional surges, and treat today as damage control "
            "rather than a training stimulus."
        )
    if weekday == LIMITER_WEEKDAY and verdict in ("REST", "EASY"):
        detail += (
            " Today's plan is VO2max/anaerobic intervals (your limiter). Given low readiness, consider "
            "cutting the rep count or swapping to endurance instead of forcing the full session."
        )

    # Adds context, doesn't change the verdict itself — jet lag can genuinely
    # depress HRV/RHR/sleep scores the same way real overreaching does, but
    # silently softening the *severity* on a declared travel day risks
    # masking a real problem that happens to coincide with travel. A caveat
    # the athlete can weigh is safer than the app deciding for them.
    if traveling_note and verdict in ("REST", "EASY"):
        detail += (
            f" You're traveling ({traveling_note}) — some of this may be jet lag/travel disruption rather than "
            "training fatigue. Worth weighing that against how you actually feel, not just the score."
        )

    return ReadinessVerdict(verdict, color, headline, detail, scheduled_session)


def _fatigue_detail(snapshot: DailyHealthSnapshot) -> str:
    notes = []
    hrv = snapshot.hrv
    if hrv and hrv.last_night_avg_ms is not None and hrv.baseline_low_ms is not None:
        if hrv.last_night_avg_ms < hrv.baseline_low_ms:
            notes.append(f"HRV ({hrv.last_night_avg_ms}ms) is below your balanced baseline ({hrv.baseline_low_ms}ms)")
    rhr = snapshot.resting_heart_rate
    if rhr and rhr.resting_hr_bpm is not None:
        notes.append(f"resting HR is {rhr.resting_hr_bpm}bpm today")
    if not notes:
        return "Garmin's Training Readiness score is low today — take it easy."
    return (
        "Signals: " + "; ".join(notes) + ". Your own overreaching flags are elevated RHR + "
        "appetite change — watch for those too."
    )
