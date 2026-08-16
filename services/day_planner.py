"""The deterministic half of "Let my coach plan for me": choosing a workout
TYPE from the athlete's real signals, and checking whether the chosen day is a
good place to put it — both without any AI call, so the feature works even
while the Anthropic key is invalid.

Independent jobs, smallest first:
  - `decide_type()`: what should this session be, given the athlete's weakest
    zone, a race's demand gap (if one exists), and the week's own current
    load? This is "decide for me".
  - `check_placement()`: is THIS day a reasonable place for a hard session?
    Reuses plan_reflow's own rules (no back-to-back hard days, the Saturday
    team ride is terrain not a slot) rather than re-deriving them — spacing
    logic belongs in exactly one place.
  - `suggest_strength_focus()`: the gym half of the same question. The weakest
    zone decides WHAT to train; a separate load cap decides HOW MUCH, so a
    weakness-targeted session survives a bad readiness day at lower volume
    instead of disappearing.
  - `compose_three_options()`: "what should I do today?" — the three answers,
    with the week's fixed points (Monday rest, Saturday team ride) and today's
    readiness gating everything else.

Both return a reason string alongside their answer. A recommendation with no
visible "why" is a black box; this app's standing rule (readiness advisory,
adaptive periodization, plan reflow) is to always show the reasoning and let
the athlete approve or override it, and this is no exception.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_, timedelta
from typing import Any, Optional

from services import workout_types
from services.plan_reflow import _HARD_TYPES
from services.readiness import NON_NEGOTIABLE_WEEKDAY
from services.workout_types import WORKOUT_TYPES

#: The fixed points in this athlete's week (see the athlete profile). Monday is
#: a full rest day and Saturday is the non-negotiable team ride — suggestions
#: have to plan around both rather than pretending every day is a blank slate.
_REST_WEEKDAY = 0  # Monday
_LONG_RIDE_WEEKDAY = 6  # Sunday

#: Which CATALOG types (vo2max, lactate_threshold, ...) count as "hard" for
#: stacking/spacing purposes. Deliberately a separate set from plan_reflow's
#: _HARD_TYPES: that one classifies STORED session_type values ("intervals",
#: "long_ride", "team_ride"); this one classifies the day-planner's own type
#: vocabulary. Conflating the two was a real bug caught in testing — every
#: catalog type maps to session_type "intervals" except endurance, so checking
#: a catalog type against _HARD_TYPES silently always returned False.
_HARD_WORKOUT_TYPES = set(WORKOUT_TYPES) - {"endurance"}

#: Coggan row label -> the catalog type that targets that duration's system.
#: Every row now has a real prescription. The Neuromuscular row used to fall
#: back to `anaerobic` and say so in the reason string, which meant the most
#: likely weakness for a sprinter-leaning amateur was the one the app couldn't
#: actually train; services/workout_types.py gained a sprint template to close
#: that, so this map no longer needs an apology in it.
_COGGAN_ROW_TO_TYPE = {
    "Neuromuscular": "neuromuscular",
    "Anaerobic Capacity": "anaerobic",
    "VO2max": "vo2max",
    "Functional Threshold": "lactate_threshold",
}

#: Rows whose underlying number is known to be soft, and the caveat to attach
#: to any suggestion built on them. Both come from services/coggan.py's own
#: mapping comments: the 5min figure is self-reported as a non-maximal effort,
#: and the threshold row reads from FTP rather than a measured 20min. A
#: weakness that is really a measurement gap should be said out loud, not
#: silently trained as though it were real.
_SOFT_ROW_CAVEATS = {
    "VO2max": (
        "Worth knowing: your 5min number is self-reported as not a maximal effort, so this row may be "
        "understated rather than genuinely weak. A proper 5min test would tell you which."
    ),
    "Functional Threshold": (
        "Worth knowing: this row reads from your current FTP, not a fresh maximal 20min — if your FTP "
        "estimate is stale, so is this comparison."
    ),
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


def soft_row_caveat(weakest_zone_label: Optional[str]) -> Optional[str]:
    """The measurement caveat for a weakest-zone row, or None if the number is
    trustworthy. Public because the suggestions endpoint surfaces it as its own
    field as well as inline in the reason string."""
    if not weakest_zone_label:
        return None
    for prefix, caveat in _SOFT_ROW_CAVEATS.items():
        if weakest_zone_label.startswith(prefix):
            return caveat
    return None


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
        reason = f"Your weakest zone on the power profile is {weakest_zone_label}."
        caveat = soft_row_caveat(weakest_zone_label)
        if caveat:
            reason = f"{reason} {caveat}"
        return _avoid_stacking(matched, reason, planned_this_week)

    return "endurance", "No weakness signal available yet (log your weight and an FTP test) — defaulting to endurance."


def _avoid_stacking(workout_type: str, reason: str, planned_this_week: dict[str, dict[str, Any]]) -> tuple[str, str]:
    if workout_type in _HARD_WORKOUT_TYPES and _week_has_hard_session(planned_this_week):
        return "endurance", (
            f"{reason} Normally this would suggest {workout_type.replace('_', ' ')}, but the week already "
            "has a hard session — stacking a second one on top of it isn't a good trade. Endurance instead."
        )
    return workout_type, reason


# --- Strength ----------------------------------------------------------------
#
# The gym half of a suggestion. Same premise as the bike half: a sprinter's gap
# and a threshold rider's gap do not call for the same session, so the weakest
# Coggan row drives the prescription rather than a generic "do some strength".
#
# HARD FRAMING RULE, do not relax: this app assumes the athlete is trying to ADD
# absolute power and mass, not cut to a race weight — W/kg is tracked against
# today's logged weight for exactly that reason, and athlete_profile's
# floor_weight_kg exists as a guard rail against advice drifting the wrong way.
# No strength text may be framed around losing weight, leanness, or "getting
# lighter". Frame everything as force, absolute power and durability.

#: How hard the gym session is allowed to be today, hardest first. A cap is a
#: ceiling on the prescription below, never a change of focus — the weakness
#: still decides WHAT you train, the cap only decides HOW MUCH.
_LOAD_CAPS = ("full", "maintenance", "mobility")

#: Focus -> the /api/strength session_type vocabulary, so a planned session can
#: be logged as a completed one without the athlete re-picking anything.
_FOCUS_TO_LOG_TYPE = {
    "max_strength": "lower_body",
    "heavy_lower": "lower_body",
    "support": "full_body",
    "maintenance": "full_body",
    "general": "full_body",
    "mobility": "core",
}


def _hard_bike_adjacent(target_date: date_, planned_this_week: dict[str, dict[str, Any]]) -> Optional[str]:
    """The date of a hard bike session on this day or either side of it, if any.
    Heavy lifting stacked next to hard intervals costs more than it returns."""
    for offset in (-1, 0, 1):
        day = (target_date + timedelta(days=offset)).isoformat()
        session = planned_this_week.get(day)
        if session and session.get("session_type") in _HARD_TYPES:
            return day
    return None


def strength_load_cap(
    readiness_verdict: Optional[str],
    target_date: date_,
    planned_this_week: dict[str, dict[str, Any]],
) -> tuple[str, Optional[str]]:
    """Returns (cap, why). Ordered most-restrictive-first: the first condition
    that fires wins, so a bad readiness day is never talked back up into heavy
    lifting by a later rule."""
    if readiness_verdict in ("REST", "EASY"):
        return "mobility", (
            f"Readiness says {readiness_verdict} today, so this is mobility and core only — "
            "loading heavy on a day your body is already asking for a break buys nothing."
        )

    clash = _hard_bike_adjacent(target_date, planned_this_week)
    if clash:
        when = "today" if clash == target_date.isoformat() else f"on {clash}"
        return "maintenance", (
            f"There's a hard bike session {when}, so keep this to maintenance volume — heavy lifting "
            "either side of hard intervals competes with them for the same recovery."
        )

    if target_date.weekday() == NON_NEGOTIABLE_WEEKDAY - 1:
        return "maintenance", (
            "Tomorrow is the team ride. Keep this light — arriving pre-fatigued is the one way "
            "to make a non-negotiable day go badly."
        )

    return "full", None


def suggest_strength_focus(
    weakest_zone_label: Optional[str],
    readiness_verdict: Optional[str] = None,
    target_date: Optional[date_] = None,
    planned_this_week: Optional[dict[str, dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Weakest power-curve zone -> what to actually do in the gym.

    Returns a dict with title / detail / reason / focus / log_type / duration_min
    / cap. Deterministic and side-effect free, mirroring decide_type() so the
    two can sit next to each other as parallel suggestions.
    """
    planned_this_week = planned_this_week or {}
    cap, cap_reason = (
        strength_load_cap(readiness_verdict, target_date, planned_this_week)
        if target_date is not None
        else ("full", None)
    )

    # The mobility cap replaces the prescription outright rather than scaling
    # it — there is no light version of a 4x3 @ 85% 1RM worth doing.
    if cap == "mobility":
        return {
            "focus": "mobility",
            "title": "Mobility & core only",
            "detail": (
                "15-20min: hip flexor and thoracic openers, glute bridges, dead-bug, side plank. "
                "Nothing loaded, nothing to failure — this is circulation and position work."
            ),
            "reason": cap_reason,
            "log_type": _FOCUS_TO_LOG_TYPE["mobility"],
            "duration_min": 20,
            "cap": cap,
        }

    label = weakest_zone_label or ""
    if label.startswith("Neuromuscular"):
        focus, title = "max_strength", "Max-strength & explosive work"
        detail = (
            "Trap-bar deadlift or back squat 4x3-5 at roughly 85% of your 1RM (or RPE 8 — 2 reps left "
            "in reserve); box jumps or jump squats 3x5; single-leg step-ups 3x6/leg. Full recovery "
            "between sets, low reps, never to failure."
        )
        why = (
            "A 15s sprint is force-limited before it is aerobically limited, so the ceiling on your "
            "weakest zone is how much force you can put into the pedals — which is trained in the gym "
            "at least as directly as on the bike."
        )
        duration = 50
    elif label.startswith("Anaerobic Capacity"):
        focus, title = "heavy_lower", "Heavy lower body & trunk"
        detail = (
            "Back squat 4x5 at roughly 80% 1RM (or RPE 8); Bulgarian split squat 3x8/leg; "
            "Pallof press or other anti-rotation core 3x10/side."
        )
        why = (
            "Repeated one-minute efforts draw on a force reserve. Raise the reserve and each surge "
            "costs a smaller fraction of your maximum, which is what lets you make the next one."
        )
        duration = 50
    elif label.startswith("VO2max"):
        focus, title = "support", "Posterior chain & core support"
        detail = (
            "Romanian deadlift 3x10 moderate load; single-leg glute bridge 3x10/leg; plank and "
            "dead-bug. Controlled tempo, submaximal throughout — leave the gym feeling like you "
            "could have done more."
        )
        why = (
            "VO2max gains come from the bike. The gym's job against this weakness is to hold your "
            "position and keep you injury-free without stealing recovery from the intervals that "
            "actually move the number."
        )
        duration = 35
    elif label.startswith("Functional Threshold"):
        focus, title = "maintenance", "Strength maintenance, low fatigue cost"
        detail = (
            "Goblet squat 2x12-15 light; single-arm row 2x12; glute bridge 2x15. Keep the whole "
            "thing under 30min and well clear of your next threshold session."
        )
        why = (
            "Threshold is built by consistent time on the bike. Against this weakness the gym's only "
            "job is to not get in the way of that."
        )
        duration = 30
    else:
        focus, title = "general", "General full-body strength"
        detail = (
            "Squat, a hip hinge, a row and an overhead press — 2-3 sets of 8-10 at a moderate load, "
            "none of them to failure."
        )
        why = (
            "No weakness signal yet — log a weigh-in and an FTP test and this becomes specific. "
            "General maintenance in the meantime."
        )
        duration = 40

    # The maintenance cap keeps the FOCUS but pulls the load down, so a
    # weakness-targeted session survives a busy week instead of vanishing.
    if cap == "maintenance":
        detail = (
            f"Scaled back today: same focus, about half the volume, and nothing above RPE 7 "
            f"(3+ reps in reserve). Full version: {detail}"
        )
        why = f"{why} {cap_reason}"
        duration = max(20, duration // 2)

    return {
        "focus": focus,
        "title": title,
        "detail": detail,
        "reason": why,
        "log_type": _FOCUS_TO_LOG_TYPE[focus],
        "duration_min": duration,
        "cap": cap,
    }


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


# --- "What should I do today?" — the three-option composer ---------------------


@dataclass
class SuggestedOption:
    """One of the three answers to "what should I do today?".

    `kind` and `exclusive_with` carry the relationship between options, which
    the UI needs and can't infer: two bike options are alternatives to each
    other, but a strength option is additive — accepting both a ride and a gym
    session for the same day is a legitimate answer, not a conflict.
    """

    kind: str  # bike | strength | rest | note
    exclusive_with: list[str]
    title: str
    detail: str
    reason: str
    session_type: str = "custom"  # the stored PlannedWorkoutModel session_type
    workout_type: Optional[str] = None  # catalog type; bike options only
    duration_min: Optional[int] = None
    target_watts_low: Optional[int] = None
    target_watts_high: Optional[int] = None
    steps: list[dict] = field(default_factory=list)
    strength_focus: Optional[str] = None
    strength_log_type: Optional[str] = None
    placement_warning: Optional[str] = None


def _bike_option(
    workout_type: str,
    reason: str,
    ftp_watts: Optional[float],
    target_date: date_,
    planned_this_week: dict[str, dict[str, Any]],
    intensity: float = 0.5,
) -> SuggestedOption:
    generated = workout_types.build(workout_type, ftp_watts, intensity)
    return SuggestedOption(
        kind="bike",
        exclusive_with=["bike", "rest"],
        title=generated.title,
        detail=generated.detail,
        reason=reason,
        session_type=generated.session_type,
        workout_type=workout_type,
        duration_min=generated.duration_min,
        target_watts_low=generated.target_watts_low,
        target_watts_high=generated.target_watts_high,
        steps=generated.steps,
        placement_warning=check_placement(target_date, planned_this_week, workout_type),
    )


def _strength_option(
    weakest_zone_label: Optional[str],
    readiness_verdict: Optional[str],
    target_date: date_,
    planned_this_week: dict[str, dict[str, Any]],
) -> SuggestedOption:
    s = suggest_strength_focus(weakest_zone_label, readiness_verdict, target_date, planned_this_week)
    return SuggestedOption(
        kind="strength",
        exclusive_with=["strength"],  # additive: pairs with a ride on the same day
        title=s["title"],
        detail=s["detail"],
        reason=s["reason"],
        session_type="strength",
        duration_min=s["duration_min"],
        strength_focus=s["focus"],
        strength_log_type=s["log_type"],
    )


def _recovery_spin(ftp_watts: Optional[float], reason: str) -> SuggestedOption:
    """Not a catalog type on purpose: the catalog's easiest session is an
    endurance ride at 60-75% FTP, which is a training stimulus. This is the
    absence of one — spinning to move blood, nothing more."""
    watts = f"{round(ftp_watts * 0.45)}-{round(ftp_watts * 0.6)}W" if ftp_watts else "very easy"
    return SuggestedOption(
        kind="bike",
        exclusive_with=["bike", "rest"],
        title="Recovery spin",
        detail=(
            f"40min easy at {watts}. Flat, small gear, high cadence. If it feels like training, "
            "it's too hard — the point is to finish fresher than you started."
        ),
        reason=reason,
        session_type="endurance",
        workout_type=None,
        duration_min=40,
        steps=[{"duration_sec": 2400, "target_type": "range",
                "target_low_pct_ftp": 0.45, "target_high_pct_ftp": 0.6}],
    )


def _rest_option(reason: str) -> SuggestedOption:
    return SuggestedOption(
        kind="rest", exclusive_with=["bike", "rest"],
        title="Full rest", detail="No structured session. Eat, sleep, let the work you've already done land.",
        reason=reason, session_type="rest", duration_min=0,
    )


def _team_ride_option() -> SuggestedOption:
    """Saturday. Offered so the day isn't blank, NOT as a decision to make —
    the team ride is non-negotiable, so nothing here may propose replacing,
    downgrading or skipping it. Effort management only."""
    return SuggestedOption(
        kind="bike", exclusive_with=["bike"],
        title="Team ride (non-negotiable)",
        detail=(
            "The weekly club ride. Ride it as it comes. If you're carrying fatigue, manage it inside the "
            "ride — sit in on the hard sections, take fewer turns — and take it out of Sunday's intensity "
            "afterwards rather than out of today."
        ),
        reason="Saturday is your team ride. It's a fixed point in the week, so today plans around it, not over it.",
        session_type="team_ride", duration_min=None,
    )


def _long_ride_option() -> SuggestedOption:
    """Sunday's own fixed session from the athlete profile: 4-4.5h including a
    90min block at ~45kph. Deliberately unstructured — a 4h outdoor ride with a
    long sustained block isn't usefully described as a list of %FTP steps."""
    return SuggestedOption(
        kind="bike", exclusive_with=["bike", "rest"],
        title="Long ride with a sustained block",
        detail=(
            "4-4.5h, with a 90min block at around 45kph inside it. Ride the block as one continuous "
            "effort rather than surging — the point is sustained speed, not average power."
        ),
        reason="Sunday is your long day, and the 90min block is where most of its training value sits.",
        session_type="long_ride", duration_min=270,
    )


def _note_option(title: str, detail: str, reason: str) -> SuggestedOption:
    return SuggestedOption(
        kind="note", exclusive_with=[],  # a note never conflicts with anything
        title=title, detail=detail, reason=reason, session_type="note", duration_min=None,
    )


def _contrast_type(primary_type: str) -> tuple[str, str]:
    """The second bike option: a genuine alternative, never a repeat of the
    first. Every catalog type maps to something different from itself, so the
    two options can't collide."""
    if primary_type in ("anaerobic", "neuromuscular"):
        return "lactate_threshold", (
            "A longer, steadier alternative to the session above — still productive, but it asks for "
            "sustained effort rather than repeated maximal ones."
        )
    if primary_type == "endurance":
        return "lactate_threshold", (
            "If you'd rather make today count for something specific, threshold work is the highest-value "
            "session that isn't chasing a named weakness."
        )
    return "endurance", (
        "A lower-intensity alternative to the session above — same day, easier legs, and it still "
        "builds the aerobic base everything else sits on."
    )


def compose_three_options(
    weakest_zone_label: Optional[str],
    gap_report: Optional[list[dict[str, Any]]],
    planned_this_week: dict[str, dict[str, Any]],
    readiness_verdict: Optional[str],
    target_date: date_,
    ftp_watts: Optional[float],
) -> list[SuggestedOption]:
    """Exactly three options for one day, in priority order.

    Pure: every input is passed in, nothing is fetched, so the whole decision
    tree is directly testable. The gates run before anything else because they
    can invalidate the premise of a hard suggestion entirely — there is no
    point ranking interval types for a Monday.
    """
    weekday = target_date.weekday()
    strength = _strength_option(weakest_zone_label, readiness_verdict, target_date, planned_this_week)

    # --- Gate 0: the week's fixed structure -----------------------------------
    if weekday == NON_NEGOTIABLE_WEEKDAY:
        return [
            _team_ride_option(),
            strength,
            _note_option(
                "Log how the team ride went",
                "Drop an RPE and a line on how the ride felt. It's the only record of a day the app "
                "can't second-guess, and it's what makes next week's advice better.",
                "The team ride is fixed, so today's useful choice isn't what to do — it's what to record.",
            ),
        ]

    if weekday == _REST_WEEKDAY:
        primary_type, primary_reason = decide_type(weakest_zone_label, gap_report, planned_this_week)
        moved = _bike_option(primary_type, primary_reason, ftp_watts, target_date, planned_this_week)
        moved.reason = f"If you're moving your rest day this week: {moved.reason}"
        return [
            _rest_option(
                "Monday is your scheduled full rest day. Taking it is the session — the adaptation from "
                "last week happens now, not during it."
            ),
            strength,
            moved,
        ]

    # --- Gate 1: readiness ----------------------------------------------------
    if readiness_verdict in ("REST", "EASY"):
        parked_type, parked_reason = decide_type(weakest_zone_label, gap_report, planned_this_week)
        parked = _bike_option(parked_type, parked_reason, ftp_watts, target_date, planned_this_week)
        parked.reason = (
            f"This is what you'd do on a good day — parked, not cancelled. {parked.reason}"
        )
        first = (
            _rest_option(
                "Readiness says REST. Nothing you gain from training through this outweighs what it costs."
            )
            if readiness_verdict == "REST"
            else _recovery_spin(
                ftp_watts,
                "Readiness says EASY. Moving is fine today; loading isn't — keep it genuinely light.",
            )
        )
        return [first, strength, parked]

    # --- Normal day -----------------------------------------------------------
    primary_type, primary_reason = decide_type(weakest_zone_label, gap_report, planned_this_week)
    primary = _bike_option(primary_type, primary_reason, ftp_watts, target_date, planned_this_week)

    if _week_has_hard_session(planned_this_week):
        # decide_type has already downgraded the primary to endurance here, so
        # the contrast must be easier still — offering a second hard type would
        # undo the stacking rule that just fired.
        contrast = _recovery_spin(
            ftp_watts,
            "Your week already has a hard session in it, so the honest second option today is less, not more.",
        )
    elif weekday == _LONG_RIDE_WEEKDAY:
        contrast = _long_ride_option()
    else:
        contrast_type, contrast_reason = _contrast_type(primary_type)
        contrast = _bike_option(contrast_type, contrast_reason, ftp_watts, target_date, planned_this_week)

    return [primary, contrast, strength]
