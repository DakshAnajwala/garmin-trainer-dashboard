"""Deterministic weekly session-prescription algorithm.

Targets the athlete's identified limiter (1-5min power / anaerobic capacity)
on the fixed Wednesday interval day, progresses load across a 4-week block
(week 4 = recovery), and downgrades a day's prescription when today's
readiness verdict is low. Never touches the non-negotiable Saturday slot.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date as date_
from typing import Optional

from services.readiness import LIMITER_WEEKDAY, NON_NEGOTIABLE_WEEKDAY

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


@dataclass
class SessionPrescription:
    weekday: int
    day_name: str
    session_type: str  # rest | endurance | intervals | team_ride | long_ride | endurance_swap | rest_swap
    title: str
    detail: str
    duration_min: Optional[int] = None
    target_watts_low: Optional[int] = None
    target_watts_high: Optional[int] = None


# Wednesday VO2max/anaerobic progression across a 4-week block.
_WEDNESDAY_PROGRESSION = {
    1: {"reps": 5, "work_min": 3, "rest_min": 3, "pct_low": 106, "pct_high": 115, "label": "VO2max intervals"},
    2: {"reps": 6, "work_min": 3, "rest_min": 3, "pct_low": 108, "pct_high": 118, "label": "VO2max intervals"},
    3: {"reps": 5, "work_min": 2, "rest_min": 2, "pct_low": 120, "pct_high": 135, "label": "Anaerobic capacity intervals"},
    4: {"reps": 4, "work_min": 3, "rest_min": 4, "pct_low": 100, "pct_high": 105, "label": "Recovery-week openers"},
}


def _watts(ftp: Optional[float], pct: float) -> Optional[int]:
    return round(ftp * pct / 100) if ftp else None


def _wednesday_session(ftp_watts: Optional[float], block_week: int) -> SessionPrescription:
    plan = _WEDNESDAY_PROGRESSION.get(block_week, _WEDNESDAY_PROGRESSION[1])
    low, high = _watts(ftp_watts, plan["pct_low"]), _watts(ftp_watts, plan["pct_high"])
    watt_text = f"{low}-{high}W" if low and high else "watts TBD (log a weigh-in / wait for FTP estimate)"
    return SessionPrescription(
        weekday=LIMITER_WEEKDAY,
        day_name="Wednesday",
        session_type="intervals",
        title=plan["label"],
        detail=(
            f"{plan['reps']} x {plan['work_min']}min @ {watt_text}, {plan['rest_min']}min easy recovery "
            f"between reps. Targets your limiter (1-5min power / anaerobic durability)."
        ),
        duration_min=plan["reps"] * (plan["work_min"] + plan["rest_min"]) + 15,
        target_watts_low=low,
        target_watts_high=high,
    )


def _endurance_session(weekday: int, day_name: str, title: str, duration_min: int, ftp_watts: Optional[float]) -> SessionPrescription:
    low, high = _watts(ftp_watts, 60), _watts(ftp_watts, 75)
    watt_text = f"{low}-{high}W" if low and high else "watts TBD"
    return SessionPrescription(
        weekday=weekday,
        day_name=day_name,
        session_type="endurance",
        title=title,
        detail=f"Zone 2 endurance, {watt_text}, {duration_min}min.",
        duration_min=duration_min,
        target_watts_low=low,
        target_watts_high=high,
    )


def build_week_plan(ftp_watts: Optional[float], block_week: int) -> list[SessionPrescription]:
    """The full 7-day skeleton for the given block week (1-4, 4 = recovery)."""
    long_low, long_high = _watts(ftp_watts, 65), _watts(ftp_watts, 90)
    long_watt_text = f"{long_low}-{long_high}W" if long_low and long_high else "watts TBD"

    plans = [
        SessionPrescription(0, "Monday", "rest", "Full rest", "No structured session — full recovery day."),
        _endurance_session(1, "Tuesday", "Base or fast ride (feel-dependent)", 75, ftp_watts),
        _wednesday_session(ftp_watts, block_week),
        _endurance_session(3, "Thursday", "Base", 75, ftp_watts),
        SessionPrescription(
            4, "Friday", "rest", "Easy base or full rest",
            "Optional easy Zone 1-2 spin, 30-45min, or full rest — feel-dependent.",
        ),
        SessionPrescription(
            NON_NEGOTIABLE_WEEKDAY, "Saturday", "team_ride", "Non-negotiable team ride",
            "Steady group effort. Non-negotiable — attend regardless of readiness; manage intensity, don't skip.",
        ),
        SessionPrescription(
            6, "Sunday", "long_ride", "Long ride + 90min sustained block",
            f"4-4.5h total, Zone 2 endurance ({long_watt_text}) with a 90min sustained hard block at ~45kph.",
            duration_min=270,
            target_watts_low=long_low,
            target_watts_high=long_high,
        ),
    ]

    if block_week == 4:
        plans = [
            replace(p, duration_min=round(p.duration_min * 0.7), detail=p.detail + " (Recovery week — volume cut ~30%.)")
            if p.session_type in ("endurance", "long_ride") and p.duration_min
            else p
            for p in plans
        ]
    return plans


def wednesday_workout_steps(block_week: int) -> list[dict]:
    """Structured (steady/ramp step) workout for the current block-week's
    Wednesday session, exportable via services/workout_export.to_zwo. Reps
    come straight from _WEDNESDAY_PROGRESSION; warmup/cooldown are fixed."""
    plan = _WEDNESDAY_PROGRESSION.get(block_week, _WEDNESDAY_PROGRESSION[1])
    steps = [{"duration_sec": 600, "target_type": "steady", "target_low_pct_ftp": 0.55}]
    for _ in range(plan["reps"]):
        steps.append(
            {"duration_sec": plan["work_min"] * 60, "target_type": "steady", "target_low_pct_ftp": round(plan["pct_low"] / 100, 2)}
        )
        steps.append({"duration_sec": plan["rest_min"] * 60, "target_type": "steady", "target_low_pct_ftp": 0.5})
    steps.append({"duration_sec": 600, "target_type": "steady", "target_low_pct_ftp": 0.55})
    return steps


def todays_prescription(
    for_date: date_, ftp_watts: Optional[float], block_week: int, readiness_verdict: Optional[str] = None
) -> SessionPrescription:
    week_plan = build_week_plan(ftp_watts, block_week)
    today = next(p for p in week_plan if p.weekday == for_date.weekday())

    if readiness_verdict in ("REST", "EASY") and today.session_type == "intervals":
        low, high = _watts(ftp_watts, 55), _watts(ftp_watts, 68)
        watt_text = f"{low}-{high}W" if low and high else "watts TBD"
        return SessionPrescription(
            today.weekday, today.day_name, "endurance_swap",
            "Readiness low — swapped to easy endurance",
            f"Original plan was {today.title}, but today's readiness is low. Swap to easy Zone 1-2 spin, "
            f"{watt_text}, 45-60min. Revisit the limiter session once readiness recovers.",
            duration_min=50, target_watts_low=low, target_watts_high=high,
        )
    if readiness_verdict == "REST" and today.session_type in ("endurance", "long_ride"):
        return SessionPrescription(
            today.weekday, today.day_name, "rest_swap", "Readiness very low — consider resting instead",
            f"Original plan was {today.title}. Given today's readiness, consider a full rest day or a short "
            "easy spin instead.",
        )
    return today
