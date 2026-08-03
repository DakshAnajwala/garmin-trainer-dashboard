"""The deterministic workout-type catalog: five session shapes, each a fixed
prescription in %FTP (and cadence for overgearing), scaled to watts once the
athlete's FTP is known.

This is the "type becomes structured steps" half of the day-planner feature.
Deliberately NOT an AI call: every type here always produces a valid, bounded
workout — with the Anthropic key currently invalid, this is what keeps "Let my
coach plan for me" functional at all. The AI layer (a later piece) only picks
*which* type to suggest and writes the rationale; it never invents the numbers.

Ranges below reflect commonly-cited zone conventions (Coggan-style %FTP bands)
for each session's physiological target — not this athlete's personal test
data, which the app doesn't have per-type performance for yet.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

#: Every type the day-planner can choose from — both the UI and the AI layer
#: enumerate this list rather than a hardcoded set, so there is exactly one
#: place that defines "what a workout type is."
WORKOUT_TYPES = ["vo2max", "lactate_threshold", "overgearing", "anaerobic", "endurance"]

_LABELS = {
    "vo2max": "VO2max intervals",
    "lactate_threshold": "Lactate threshold intervals",
    "overgearing": "Overgearing / torque work",
    "anaerobic": "Anaerobic capacity intervals",
    "endurance": "Endurance ride",
}

#: What each type targets, in plain language — surfaced in the rationale so a
#: recommendation reads as coaching, not a label.
_TARGETS = {
    "vo2max": "aerobic ceiling and repeatability of hard efforts",
    "lactate_threshold": "the power you can hold for 20-60min — your FTP itself",
    "overgearing": "muscular torque and force production, independent of your aerobic system",
    "anaerobic": "short, very hard efforts and the anaerobic capacity above VO2max",
    "endurance": "aerobic base and fat-burning efficiency at low intensity",
}


@dataclass
class GeneratedWorkout:
    session_type: str
    title: str
    detail: str
    duration_min: int
    target_watts_low: Optional[int]
    target_watts_high: Optional[int]
    steps: list[dict]


def _watts(ftp: Optional[float], pct: float) -> Optional[int]:
    return round(ftp * pct / 100) if ftp else None


def _interval_steps(
    reps: int, work_min: int, rest_min: int, pct_low: float, pct_high: float,
    warmup_min: int = 10, cooldown_min: int = 10, cadence: Optional[tuple[int, int]] = None,
) -> list[dict]:
    steps = [{"duration_sec": warmup_min * 60, "target_type": "steady", "target_low_pct_ftp": 0.55}]
    for _ in range(reps):
        work = {
            "duration_sec": work_min * 60, "target_type": "steady",
            "target_low_pct_ftp": round(pct_low / 100, 3),
            "target_high_pct_ftp": round(pct_high / 100, 3) if pct_high != pct_low else None,
        }
        if cadence:
            work["cadence_low_rpm"], work["cadence_high_rpm"] = cadence
        steps.append(work)
        steps.append({"duration_sec": rest_min * 60, "target_type": "steady", "target_low_pct_ftp": 0.5})
    steps.append({"duration_sec": cooldown_min * 60, "target_type": "steady", "target_low_pct_ftp": 0.55})
    return steps


# --- Per-type generators ------------------------------------------------------
#
# Each takes ftp_watts (for the human-readable detail text) and a 0..1
# `intensity` knob so the week-aware planner (a later piece) can nudge a
# session slightly easier/harder without inventing a new template — e.g. a
# below-par readiness day gets intensity=0.0 (bottom of the range) rather than
# a different workout entirely.


def _vo2max(ftp_watts: Optional[float], intensity: float) -> GeneratedWorkout:
    reps = 4 + round(intensity * 2)  # 4-6 reps
    pct_low, pct_high = 106, 120
    steps = _interval_steps(reps, 4, 4, pct_low, pct_high)
    low, high = _watts(ftp_watts, pct_low), _watts(ftp_watts, pct_high)
    watt_text = f"{low}-{high}W" if low and high else "watts TBD — log a weigh-in / FTP test"
    return GeneratedWorkout(
        "intervals", _LABELS["vo2max"],
        f"{reps} x 4min @ {watt_text}, 4min easy recovery between reps. Targets {_TARGETS['vo2max']}.",
        duration_min=round(sum(s["duration_sec"] for s in steps) / 60),
        target_watts_low=low, target_watts_high=high, steps=steps,
    )


def _lactate_threshold(ftp_watts: Optional[float], intensity: float) -> GeneratedWorkout:
    reps = 2 if intensity < 0.5 else 3
    work_min = 15 if intensity < 0.5 else 20
    pct_low, pct_high = 88, 95
    steps = _interval_steps(reps, work_min, 8, pct_low, pct_high)
    low, high = _watts(ftp_watts, pct_low), _watts(ftp_watts, pct_high)
    watt_text = f"{low}-{high}W" if low and high else "watts TBD — log a weigh-in / FTP test"
    return GeneratedWorkout(
        "intervals", _LABELS["lactate_threshold"],
        f"{reps} x {work_min}min @ {watt_text}, 8min easy recovery between reps. Targets {_TARGETS['lactate_threshold']}.",
        duration_min=round(sum(s["duration_sec"] for s in steps) / 60),
        target_watts_low=low, target_watts_high=high, steps=steps,
    )


def _overgearing(ftp_watts: Optional[float], intensity: float) -> GeneratedWorkout:
    reps = 3 + round(intensity)  # 3-4 reps
    pct_low, pct_high = 95, 100  # at or just below FTP — same zone as threshold
    cadence = (40, 60)
    steps = _interval_steps(reps, 8, 6, pct_low, pct_high, cadence=cadence)
    low, high = _watts(ftp_watts, pct_low), _watts(ftp_watts, pct_high)
    watt_text = f"{low}-{high}W" if low and high else "watts TBD — log a weigh-in / FTP test"
    return GeneratedWorkout(
        "intervals", _LABELS["overgearing"],
        (
            f"{reps} x 8min @ {watt_text} but at only {cadence[0]}-{cadence[1]}rpm (a heavy gear), "
            f"6min easy spin recovery between reps. Same power zone as a threshold interval — the low "
            f"cadence is the whole point. Targets {_TARGETS['overgearing']}."
        ),
        duration_min=round(sum(s["duration_sec"] for s in steps) / 60),
        target_watts_low=low, target_watts_high=high, steps=steps,
    )


def _anaerobic(ftp_watts: Optional[float], intensity: float) -> GeneratedWorkout:
    reps = 6 + round(intensity * 4)  # 6-10 reps
    work_sec = 30 if intensity < 0.5 else 45
    pct_low, pct_high = 120, 150
    steps = [{"duration_sec": 600, "target_type": "steady", "target_low_pct_ftp": 0.55}]
    for _ in range(reps):
        steps.append({
            "duration_sec": work_sec, "target_type": "steady",
            "target_low_pct_ftp": round(pct_low / 100, 3), "target_high_pct_ftp": round(pct_high / 100, 3),
        })
        steps.append({"duration_sec": 240, "target_type": "steady", "target_low_pct_ftp": 0.5})
    steps.append({"duration_sec": 600, "target_type": "steady", "target_low_pct_ftp": 0.55})
    low, high = _watts(ftp_watts, pct_low), _watts(ftp_watts, pct_high)
    watt_text = f"{low}-{high}W" if low and high else "watts TBD — log a weigh-in / FTP test"
    return GeneratedWorkout(
        "intervals", _LABELS["anaerobic"],
        f"{reps} x {work_sec}s @ {watt_text}, 4min easy recovery between reps. Targets {_TARGETS['anaerobic']}.",
        duration_min=round(sum(s["duration_sec"] for s in steps) / 60),
        target_watts_low=low, target_watts_high=high, steps=steps,
    )


def _endurance(ftp_watts: Optional[float], intensity: float) -> GeneratedWorkout:
    duration_min = 75 + round(intensity * 45)  # 75-120min
    pct_low, pct_high = 60, 75
    steps = [{
        "duration_sec": duration_min * 60, "target_type": "steady" if pct_low == pct_high else "range",
        "target_low_pct_ftp": round(pct_low / 100, 3), "target_high_pct_ftp": round(pct_high / 100, 3),
    }]
    low, high = _watts(ftp_watts, pct_low), _watts(ftp_watts, pct_high)
    watt_text = f"{low}-{high}W" if low and high else "watts TBD — log a weigh-in / FTP test"
    return GeneratedWorkout(
        "endurance", _LABELS["endurance"],
        f"{duration_min}min steady @ {watt_text}. Targets {_TARGETS['endurance']}.",
        duration_min=duration_min, target_watts_low=low, target_watts_high=high, steps=steps,
    )


_GENERATORS = {
    "vo2max": _vo2max,
    "lactate_threshold": _lactate_threshold,
    "overgearing": _overgearing,
    "anaerobic": _anaerobic,
    "endurance": _endurance,
}


def build(workout_type: str, ftp_watts: Optional[float], intensity: float = 0.5) -> GeneratedWorkout:
    """The one entry point: type name + FTP (+ optional 0..1 intensity knob) ->
    a fully-formed, structured workout. Raises for any type outside the
    catalog — the AI layer must never be able to request something this
    function doesn't recognize."""
    if workout_type not in _GENERATORS:
        raise ValueError(f"Unknown workout type '{workout_type}'. Must be one of {WORKOUT_TYPES}.")
    intensity = max(0.0, min(1.0, intensity))
    return _GENERATORS[workout_type](ftp_watts, intensity)


def label_for(workout_type: str) -> str:
    return _LABELS.get(workout_type, workout_type)
