"""Plan reflow: the week is a controller toward the target, not a static
calendar with red X's.

When a key session is missed (or blocked by declared travel/illness), the
remaining days of the week rebalance around it: the missed work moves to the
nearest eligible day, easy days absorb the displacement, and everything else
stays put. Each change is one plain line — what moved, where, why. There is
deliberately no concept of "incomplete" here; a session that couldn't happen
is a scheduling input, not a mark against the athlete (same stance as
adaptive_periodization's missed-day handling).

Hard rules the reflow must never violate:
- **Pinned days don't move.** A pin is the athlete saying "this day is what it
  is" — reflow plans around pins, never through them.
- **The Saturday team ride neither moves nor absorbs anything** — it's the
  standing non-negotiable, and reflow treats it as terrain, not as a slot.
- **No back-to-back hard days.** A moved key session may not land adjacent to
  another hard day (intervals / long ride / team ride) — redistributing load
  without respecting recovery is just a different way of breaking the athlete.
- **Travel/illness days can't receive sessions.**

Like every derived output in this app, a reflow result carries its input
snapshot (what was missed, what was pinned, which constraints applied), so
"why did my week change" always has an inspectable answer.
"""
from __future__ import annotations

import time
from dataclasses import asdict
from datetime import date as date_, timedelta
from typing import Any, Optional

from database import local_store
from services.adaptive_periodization import _CYCLING_ACTIVITY_TYPES, _MIN_DURATION_FRACTION
from services.training_plan import SessionPrescription, build_week_plan, travel_window_for

_HARD_TYPES = {"intervals", "long_ride", "team_ride"}
#: Which missed sessions are worth moving (the team ride can't be "moved" —
#: it exists on Saturday or not at all).
_MOVABLE_KEY_TYPES = ["intervals", "long_ride"]


def _week_dates(today: date_) -> list[date_]:
    monday = today - timedelta(days=today.weekday())
    return [monday + timedelta(days=i) for i in range(7)]


def _was_completed(activities_by_date: dict[str, list], d: date_, planned: SessionPrescription) -> bool:
    for a in activities_by_date.get(d.isoformat(), []):
        if a.get("type") not in _CYCLING_ACTIVITY_TYPES:
            continue
        if not planned.duration_min:
            return True
        if (a.get("duration_sec") or 0) / 60 >= planned.duration_min * _MIN_DURATION_FRACTION:
            return True
    return False


def _blocked(d: date_, constraints: dict) -> Optional[str]:
    window = travel_window_for(d, constraints)
    if window:
        return window.get("note") or "travel"
    for w in constraints.get("illness_windows", []):
        if w.get("start") and w.get("end") and w["start"] <= d.isoformat() <= w["end"]:
            return w.get("note") or "illness"
    return None


def reflow_week(
    ftp_watts: Optional[float],
    block_week: int,
    activities_by_date: dict[str, list],
    constraints: dict,
    pins: dict[str, Any],
    today: Optional[date_] = None,
) -> dict[str, Any]:
    """Rebalance the current week around reality. Returns the adjusted week,
    the one-line change log, and the input snapshot."""
    today = today or date_.today()
    dates = _week_dates(today)
    template = {p.weekday: p for p in build_week_plan(ftp_watts, block_week)}

    # Start from the template, day by day.
    week: dict[str, dict[str, Any]] = {}
    for d in dates:
        plan = template[d.weekday()]
        week[d.isoformat()] = {
            "date": d.isoformat(),
            "day_name": plan.day_name,
            "session": asdict(plan),
            "pinned": d.isoformat() in pins,
            "blocked": _blocked(d, constraints),
            "in_past": d < today,
        }

    changes: list[str] = []
    missed: list[tuple[date_, SessionPrescription]] = []

    # 1. What key work already failed to happen this week?
    for d in dates:
        plan = template[d.weekday()]
        if plan.session_type not in _MOVABLE_KEY_TYPES:
            continue
        if d < today and not _was_completed(activities_by_date, d, plan):
            missed.append((d, plan))
        elif d >= today and week[d.isoformat()]["blocked"]:
            missed.append((d, plan))
            changes.append(
                f"{plan.day_name}'s {plan.title} can't happen as scheduled ({week[d.isoformat()]['blocked']}) — looking for a new slot."
            )

    # 2. Which remaining days could receive a moved session?
    def hard_on(d: date_) -> bool:
        """Only real load counts for recovery spacing: a past hard day that was
        missed produced no fatigue, so it must not block its neighbours —
        otherwise a missed Wednesday makes Thursday untouchable for no reason."""
        entry = week.get(d.isoformat())
        if not entry or entry["session"]["session_type"] not in _HARD_TYPES:
            return False
        if entry["in_past"]:
            plan = template[d.weekday()]
            return _was_completed(activities_by_date, d, plan)
        return True

    def eligible(d: date_) -> bool:
        entry = week[d.isoformat()]
        if entry["in_past"] or entry["pinned"] or entry["blocked"]:
            return False
        if entry["session"]["session_type"] in _HARD_TYPES:
            return False  # never displace other key work
        return not (hard_on(d - timedelta(days=1)) or hard_on(d + timedelta(days=1)))

    # 3. Place missed sessions, intervals first (the limiter session is the
    #    week's highest-value work).
    for origin, plan in sorted(missed, key=lambda m: _MOVABLE_KEY_TYPES.index(m[1].session_type)):
        target = next((d for d in dates if d >= today and eligible(d)), None)
        origin_entry = week.get(origin.isoformat())
        if target is None:
            changes.append(
                f"{plan.day_name}'s {plan.title} has no eligible day left this week "
                "(pins, travel and recovery spacing all respected) — absorbed, not owed. "
                "Next week's recommendation will account for it."
            )
            continue
        displaced = week[target.isoformat()]["session"]
        week[target.isoformat()]["session"] = {**asdict(plan), "weekday": target.weekday(), "day_name": week[target.isoformat()]["day_name"]}
        week[target.isoformat()]["moved_from"] = origin.isoformat()
        reason = origin_entry["blocked"] if origin_entry and origin_entry["blocked"] else "didn't happen"
        changes.append(
            f"Moved {plan.title} from {plan.day_name} to {week[target.isoformat()]['day_name']} "
            f"({reason}); it replaces {displaced['title']}."
        )
        if origin >= today:
            week[origin.isoformat()]["session"] = {
                **asdict(template[origin.weekday()]),
                "session_type": "rest_swap",
                "title": "Freed by reflow",
                "detail": f"Original {plan.title} moved to {week[target.isoformat()]['day_name']}.",
            }

    result = {
        "week": [week[d.isoformat()] for d in dates],
        "changes": changes or ["Week is on track — nothing needed to move."],
        "inputs_snapshot": {
            "today": today.isoformat(),
            "block_week": block_week,
            "ftp_watts": ftp_watts,
            "missed": [(d.isoformat(), p.session_type) for d, p in missed],
            "pins": {k: v.get("reason", "") for k, v in pins.items()},
            "travel_windows": constraints.get("travel_windows", []),
            "illness_windows": constraints.get("illness_windows", []),
        },
        "computed_at": time.time(),
    }
    return result
