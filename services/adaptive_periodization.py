"""Adaptive periodization: recommends whether to advance, hold, or step back
the 4-week block, from what the trailing week actually delivered — rather
than the athlete manually guessing when to re-cut the block.

The block controller has a target (progressive overload across weeks 1-3,
recovery on week 4); this asks whether the trailing week actually absorbed
that target, using three real signals already in the app:

- Downgrade days: days the static weekly template called for hard work
  (intervals/long_ride) but readiness forced an easy/rest swap — i.e., the
  plan and reality diverged for a *legitimate* reason.
- Missed days: readiness was fine, the plan called for a hard session, but
  no matching activity was actually logged that day — the session simply
  didn't happen. Counted the same as a downgrade for the hold/advance
  decision (the load didn't land either way), but described separately and
  deliberately without guilt language — a missed session is a rebalancing
  input, not a mark against the athlete. (Whatever caused the gap — illness,
  life, a bad day — is exactly what this controller already exists to
  absorb without cascading into next week.)
- ACWR / Form: Garmin's acute:chronic load ratio (always available) and,
  if connected, intervals.icu Form — the same signals adaptive_load.py
  already uses for the daily advisory, reused here as a weekly trend.

Same principle as adaptive_load.py and apply_constraints: this is a visible
recommendation with an explicit "why", not a silent rewrite. The athlete (or
whoever's cutting the block) approves the change with one action.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_, timedelta
from typing import Any, Optional

from garmin_mcp.schemas import DailyHealthSnapshot
from services.readiness import compute_verdict
from services.training_plan import build_week_plan

_HARD_TYPES = {"intervals", "long_ride"}
_CYCLING_ACTIVITY_TYPES = {"road_biking", "indoor_cycling", "virtual_ride", "cycling"}
_LOOKBACK_DAYS = 7

# A logged ride doesn't need to hit the planned duration exactly to count as
# "the session happened" — a session cut short by half is still a session,
# just possibly an incomplete one. Below this fraction, treat it as missed.
_MIN_DURATION_FRACTION = 0.5

# Same conventions as adaptive_load.py's daily advisory, applied to the
# week's most recent reading rather than a single day.
_ACWR_HIGH = 1.5
_FORM_LOW = -25


@dataclass
class PeriodizationRecommendation:
    current_block_week: int
    recommended_block_week: int
    downgrade_days: int
    missed_days: int
    days_analyzed: int
    reason: str

    @property
    def should_change(self) -> bool:
        return self.recommended_block_week != self.current_block_week

    @property
    def adjusted_days(self) -> int:
        return self.downgrade_days + self.missed_days


def _was_completed(activities_by_date: dict[str, list[dict[str, Any]]], d: date_, planned_duration_min: Optional[int]) -> bool:
    activities = activities_by_date.get(d.isoformat(), [])
    for a in activities:
        if a.get("type") not in _CYCLING_ACTIVITY_TYPES:
            continue
        if not planned_duration_min:
            return True  # no planned duration to compare against — any ride that day counts
        actual_min = (a.get("duration_sec") or 0) / 60
        if actual_min >= planned_duration_min * _MIN_DURATION_FRACTION:
            return True
    return False


def _count_adjusted_days(
    snapshots_by_date: dict[str, dict[str, Any]],
    activities_by_date: dict[str, list[dict[str, Any]]],
    current_block_week: int,
    ftp_watts: Optional[float],
    today: date_,
) -> tuple[int, int, int]:
    """How many of the last _LOOKBACK_DAYS had a hard session on the weekly
    template that either (a) readiness downgraded, or (b) simply wasn't
    logged as completed. Only counts days that were actually fetched (a day
    never opened has no snapshot and is silently skipped, not assumed good
    or bad)."""
    week_plan = {p.weekday: p for p in build_week_plan(ftp_watts, current_block_week)}
    downgrades = 0
    missed = 0
    analyzed = 0
    for offset in range(1, _LOOKBACK_DAYS + 1):
        d = today - timedelta(days=offset)
        snapshot_dict = snapshots_by_date.get(d.isoformat())
        if not snapshot_dict:
            continue
        analyzed += 1
        planned = week_plan.get(d.weekday())
        if not planned or planned.session_type not in _HARD_TYPES:
            continue
        try:
            snapshot_obj = DailyHealthSnapshot.model_validate(snapshot_dict)
        except Exception:
            continue
        verdict = compute_verdict(snapshot_obj, d)
        if verdict.verdict in ("REST", "EASY"):
            downgrades += 1  # legitimate — readiness itself called for backing off
        elif not _was_completed(activities_by_date, d, planned.duration_min):
            missed += 1  # readiness was fine, but the session didn't happen anyway
    return downgrades, missed, analyzed


def _adjustment_note(downgrades: int, missed: int) -> str:
    parts = []
    if downgrades:
        parts.append(f"{downgrades} downgraded by readiness")
    if missed:
        parts.append(f"{missed} missed (no session logged)")
    return " and ".join(parts) if parts else "none"


def recommend(
    current_block_week: int,
    snapshots_by_date: dict[str, dict[str, Any]],
    ftp_watts: Optional[float],
    latest_acwr: Optional[float],
    latest_acwr_status: Optional[str],
    latest_form: Optional[float],
    activities_by_date: Optional[dict[str, list[dict[str, Any]]]] = None,
    today: Optional[date_] = None,
) -> PeriodizationRecommendation:
    today = today or date_.today()
    downgrades, missed, analyzed = _count_adjusted_days(
        snapshots_by_date, activities_by_date or {}, current_block_week, ftp_watts, today
    )
    adjusted = downgrades + missed

    overloaded = (latest_acwr is not None and latest_acwr >= _ACWR_HIGH) or (
        latest_form is not None and latest_form <= _FORM_LOW
    )

    if analyzed == 0:
        return PeriodizationRecommendation(
            current_block_week, current_block_week, downgrades, missed, analyzed,
            "Not enough recent days fetched to judge the trend yet — holding at the current block week.",
        )

    if current_block_week == 4:
        # Week 4 is the recovery week by design; the question is only
        # whether it's safe to start a fresh block or extend recovery.
        if adjusted >= 2 or overloaded:
            return PeriodizationRecommendation(
                4, 4, downgrades, missed, analyzed,
                f"Recovery week, but {_adjustment_note(downgrades, missed)} hard session(s) still didn't land as "
                "planned, and/or load is still elevated — holding another recovery week rather than starting a "
                "fresh block on top of fatigue.",
            )
        return PeriodizationRecommendation(
            4, 1, downgrades, missed, analyzed,
            f"Recovery week completed cleanly (0 sessions off-plan out of {analyzed} analyzed) — "
            "recommend starting a fresh block at week 1.",
        )

    if adjusted >= 2 or overloaded:
        load_note = (
            f"ACWR {latest_acwr:.2f} ({latest_acwr_status or 'elevated'})" if latest_acwr is not None
            else (f"Form {latest_form:.0f}" if latest_form is not None else "load trending high")
        )
        return PeriodizationRecommendation(
            current_block_week, current_block_week, downgrades, missed, analyzed,
            f"{_adjustment_note(downgrades, missed)} of this block's hard session(s) in the last {analyzed} day(s) "
            f"analyzed, and {load_note} — the prescribed load hasn't actually landed yet. Recommend holding "
            f"at block week {current_block_week} rather than progressing on top of it. A missed session isn't a "
            "mark against you — it's exactly the kind of thing this recommendation exists to absorb rather than "
            "let cascade into next week.",
        )

    if adjusted == 0:
        next_week = min(current_block_week + 1, 4)
        return PeriodizationRecommendation(
            current_block_week, next_week, downgrades, missed, analyzed,
            f"Every hard session in the last {analyzed} day(s) analyzed landed as prescribed, with no "
            f"load flags — recommend progressing to block week {next_week}.",
        )

    return PeriodizationRecommendation(
        current_block_week, current_block_week, downgrades, missed, analyzed,
        f"{_adjustment_note(downgrades, missed)} out of {analyzed} analyzed — mixed week. Recommend holding at "
        f"block week {current_block_week} rather than progressing on a partial signal.",
    )
