"""Materialize the weekly template into real, dated, editable planned sessions.

The calendar used to *paint* the algorithm's 7-day template onto every week —
computed on the fly, identical every week, impossible to edit. This turns one
click into stored objects you own: generate fills the viewed week, then each
day is yours to edit, swap, or clear (intervals.icu-style).

Non-destructive by design: generate never overwrites a day you've already
planned or edited. It fills the gaps and reports what it skipped, so
regenerating after you've tweaked Wednesday doesn't wipe your tweak. Clearing a
day and regenerating is the way to get the template back.

`source` on each session records where it came from ("generated" vs "custom"),
so the UI can show which days are the algorithm's suggestion and which you've
made your own — and so a future "reset to suggested" can tell them apart.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date as date_, timedelta
from typing import Any, Optional

from services.training_plan import build_week_plan, wednesday_workout_steps


def _monday_of(any_day: date_) -> date_:
    return any_day - timedelta(days=any_day.weekday())


def _session_to_planned(prescription: Any, date_str: str, block_week: int) -> dict[str, Any]:
    """One template SessionPrescription -> a stored planned-workout object.

    Structured steps are attached where the template defines them (the
    Wednesday intervals session), so "open in Builder" has something real to
    edit rather than a bare title. Endurance/rest days carry no steps — they're
    a target range, not an interval structure, and inventing fake steps for
    them would just be noise.
    """
    p = asdict(prescription)
    planned: dict[str, Any] = {
        "date": date_str,
        "session_type": p["session_type"],
        "title": p["title"],
        "detail": p["detail"],
        "duration_min": p.get("duration_min"),
        "target_watts_low": p.get("target_watts_low"),
        "target_watts_high": p.get("target_watts_high"),
        "source": "generated",
        "steps": [],
    }
    if p["session_type"] == "intervals":
        planned["steps"] = wednesday_workout_steps(block_week)
    return planned


def generate_week(
    view_day: date_,
    ftp_watts: Optional[float],
    block_week: int,
    existing_dates: set[str],
) -> dict[str, Any]:
    """Build the planned sessions for the week containing `view_day`.

    Returns {"created": {date: workout}, "skipped": [dates]}. Days already in
    `existing_dates` are left untouched — that's the non-destructive contract.
    The caller persists `created`; this function stays pure so it's trivially
    testable and never surprises anyone by writing to the store itself.
    """
    monday = _monday_of(view_day)
    week_plan = {prescription.weekday: prescription for prescription in build_week_plan(ftp_watts, block_week)}

    created: dict[str, Any] = {}
    skipped: list[str] = []
    for offset in range(7):
        day = monday + timedelta(days=offset)
        date_str = day.isoformat()
        prescription = week_plan.get(day.weekday())
        if prescription is None:
            continue
        if date_str in existing_dates:
            skipped.append(date_str)
            continue
        created[date_str] = _session_to_planned(prescription, date_str, block_week)

    return {
        "created": created,
        "skipped": skipped,
        "week_start": monday.isoformat(),
        "week_end": (monday + timedelta(days=6)).isoformat(),
    }
