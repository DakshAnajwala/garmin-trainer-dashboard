"""The deterministic half of "Let my coach plan for me": choosing a workout
TYPE from the athlete's real signals, and checking whether the chosen day is a
good place to put it — both without any AI call, so the feature works even
while the Anthropic key is invalid.

Two independent jobs:
  - `decide_type()`: what should this session be, given the athlete's weakest
    zone, a race's demand gap (if one exists), and the week's own current
    load? This is "decide for me".
  - `check_placement()`: is THIS day a reasonable place for a hard session?
    Reuses plan_reflow's own rules (no back-to-back hard days, the Saturday
    team ride is terrain not a slot) rather than re-deriving them — spacing
    logic belongs in exactly one place.

Both return a reason string alongside their answer. A recommendation with no
visible "why" is a black box; this app's standing rule (readiness advisory,
adaptive periodization, plan reflow) is to always show the reasoning and let
the athlete approve or override it, and this is no exception.
"""
from __future__ import annotations

from datetime import date as date_, timedelta
from typing import Any, Optional

from services.plan_reflow import _HARD_TYPES
from services.workout_types import WORKOUT_TYPES

#: Which CATALOG types (vo2max, lactate_threshold, ...) count as "hard" for
#: stacking/spacing purposes. Deliberately a separate set from plan_reflow's
#: _HARD_TYPES: that one classifies STORED session_type values ("intervals",
#: "long_ride", "team_ride"); this one classifies the day-planner's own type
#: vocabulary. Conflating the two was a real bug caught in testing — every
#: catalog type maps to session_type "intervals" except endurance, so checking
#: a catalog type against _HARD_TYPES silently always returned False.
_HARD_WORKOUT_TYPES = set(WORKOUT_TYPES) - {"endurance"}

#: Coggan row label -> the catalog type that targets that duration's system.
#: The 5s/"Neuromuscular" row has no matching type in the catalog (true sprint
#: power isn't one of the five prescriptions) so it falls back to anaerobic,
#: the closest thing the catalog actually offers — noted in the reason string
#: rather than silently presented as a perfect match.
_COGGAN_ROW_TO_TYPE = {
    "Neuromuscular": "anaerobic",
    "Anaerobic Capacity": "anaerobic",
    "VO2max": "vo2max",
    "Functional Threshold": "lactate_threshold",
}

#: route_demand.gap_report demand type -> the catalog type that addresses it.
_GAP_TYPE_TO_WORKOUT = {
    "sustained_climb": "lactate_threshold",
    "repeated_surges": "anaerobic",
    "durability": "endurance",
}


def _match_coggan_row(weakest_zone_label: Optional[str]) -> Optional[str]:
    if not weakest_zone_label:
        return None
    for prefix, workout_type in _COGGAN_ROW_TO_TYPE.items():
        if weakest_zone_label.startswith(prefix):
            return workout_type
    return None


def _week_has_hard_session(planned_this_week: dict[str, dict[str, Any]]) -> bool:
    return any(w.get("session_type") in _HARD_TYPES for w in planned_this_week.values())


def decide_type(
    weakest_zone_label: Optional[str],
    gap_report: Optional[list[dict[str, Any]]],
    planned_this_week: dict[str, dict[str, Any]],
) -> tuple[str, str]:
    """Returns (workout_type, reason). Priority, most concrete evidence first:

    1. A race's demand gap — a real upcoming event's shortfall beats a generic
       power-curve comparison, since it's tied to an actual goal with a date.
    2. The weakest Coggan zone — always available once weight+FTP are logged,
       independent of whether a race is configured.
    3. If the week already has a hard session and neither signal picked
       something new, fall back to endurance rather than stacking a second
       hard day on top of whatever the other signal chose.
    """
    if gap_report:
        worst_gap = next((g for g in gap_report if g["status"] == "gap"), None)
        if worst_gap and worst_gap["type"] in _GAP_TYPE_TO_WORKOUT:
            workout_type = _GAP_TYPE_TO_WORKOUT[worst_gap["type"]]
            reason = f"Your race demand report shows a real gap here: {worst_gap['demand'][:90]}"
            return _avoid_stacking(workout_type, reason, planned_this_week)

    matched = _match_coggan_row(weakest_zone_label)
    if matched:
        note = (
            " (closest match — the app doesn't have a true sprint-power prescription)"
            if weakest_zone_label.startswith("Neuromuscular")
            else ""
        )
        reason = f"Your weakest zone on the power profile is {weakest_zone_label}{note}."
        return _avoid_stacking(matched, reason, planned_this_week)

    return "endurance", "No weakness signal available yet (log your weight and an FTP test) — defaulting to endurance."


def _avoid_stacking(workout_type: str, reason: str, planned_this_week: dict[str, dict[str, Any]]) -> tuple[str, str]:
    if workout_type in _HARD_WORKOUT_TYPES and _week_has_hard_session(planned_this_week):
        return "endurance", (
            f"{reason} Normally this would suggest {workout_type.replace('_', ' ')}, but the week already "
            "has a hard session — stacking a second one on top of it isn't a good trade. Endurance instead."
        )
    return workout_type, reason


def check_placement(
    target_date: date_,
    planned_this_week: dict[str, dict[str, Any]],
    workout_type: str,
) -> Optional[str]:
    """None = no concern. Otherwise a one-line warning to show before the
    athlete confirms placing a hard session on this day.

    Mirrors plan_reflow's own spacing rule (no back-to-back hard days) rather
    than reintroducing a second definition of it — if that rule ever changes,
    it only needs to change in one place.
    """
    if workout_type not in _HARD_WORKOUT_TYPES:
        return None  # endurance/rest can go anywhere

    for offset in (-1, 1):
        neighbor = (target_date + timedelta(days=offset)).isoformat()
        neighbor_session = planned_this_week.get(neighbor)
        if neighbor_session and neighbor_session.get("session_type") in _HARD_TYPES:
            day_word = "yesterday" if offset == -1 else "tomorrow"
            return (
                f"{day_word.capitalize()} ({neighbor}) already has {neighbor_session.get('title', 'a hard session')} "
                "planned — back-to-back hard days cut into recovery. Consider a different day or an easier type."
            )

    if target_date.weekday() == 5:  # Saturday — the non-negotiable team ride's day
        return (
            "Saturday is the team ride. This won't replace it, but adding another hard session the same day "
            "stacks load on top of a day that's already non-negotiable."
        )

    return None
