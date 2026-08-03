"""The Brief: one card, one sentence, instead of "open five tabs and stare."

Answers two questions only — what does today call for, and what's the one
thing that actually changed since yesterday — rather than surfacing every
metric and making the athlete find the signal themselves.

A same-day PR (new FTP test, new lactate-threshold HR) always wins the
headline slot: it's rarer and more decision-relevant than any day-to-day
wobble. Below that, day-over-day deltas are compared using a per-metric
"notable" threshold rather than raw magnitude, since 3bpm on resting HR
matters far more than 3ms on HRV — comparing raw numbers would make HRV
(which naturally swings a lot) drown out RHR (which barely moves unless
something's wrong).
"""
from __future__ import annotations

from datetime import date as date_, timedelta
from typing import Any, Optional

from database import local_store
from services import personal_records

# (label, snapshot path, unit, notable-if-abs-delta-at-least, higher_is_better)
_METRIC_CHECKS = [
    ("Resting HR", ("resting_heart_rate", "resting_hr_bpm"), "bpm", 3, False),
    ("HRV", ("hrv", "last_night_avg_ms"), "ms", 15, True),
    ("Sleep score", ("sleep", "sleep_score"), "", 15, True),
    ("Body Battery (charged)", ("body_battery", "charged"), "", 20, True),
]


def _get(snapshot: dict[str, Any], path: tuple[str, str]) -> Optional[float]:
    section = snapshot.get(path[0])
    return section.get(path[1]) if section else None


def _weight_delta(today: date_) -> Optional[dict[str, Any]]:
    history = local_store.get_weight_history(limit_days=14)
    if len(history) < 2:
        return None
    (prev_date, prev_kg), (last_date, last_kg) = history[-2], history[-1]
    delta = round(last_kg - prev_kg, 1)
    if abs(delta) < 0.3 or last_date != today.isoformat():
        return None  # only surface it the day it was actually logged
    direction = "up" if delta > 0 else "down"
    return {"label": "Weight", "text": f"Weight is {direction} {abs(delta)}kg since your last weigh-in ({prev_date})."}


def build(today_snapshot: dict[str, Any], yesterday_snapshot: Optional[dict[str, Any]], today: date_) -> dict[str, Any]:
    # 1. Same-day PRs always win — rarer and more decision-relevant than a
    # routine day-to-day wobble in HRV or sleep.
    pr_markers = personal_records.pr_markers_by_date(today.isoformat(), today.isoformat())
    today_prs = pr_markers.get(today.isoformat())
    if today_prs:
        if today_prs.get("new_ftp_watts"):
            return {"headline": f"🎉 New FTP: {today_prs['new_ftp_watts']}W — your best test yet.", "kind": "pr"}
        if today_prs.get("new_lactate_threshold_hr"):
            return {
                "headline": f"🎉 New lactate-threshold HR: {today_prs['new_lactate_threshold_hr']}bpm.",
                "kind": "pr",
            }

    # 2. A same-day weigh-in change, if notable.
    weight_note = _weight_delta(today)
    if weight_note:
        return {"headline": weight_note["text"], "kind": "weight"}

    # 3. Otherwise, the day-over-day metric that moved the most relative to
    # what's "notable" for that specific metric.
    if not yesterday_snapshot:
        return {"headline": "First day of data — check back tomorrow for a real comparison.", "kind": "none"}

    best = None
    for label, path, unit, threshold, higher_is_better in _METRIC_CHECKS:
        today_val, yesterday_val = _get(today_snapshot, path), _get(yesterday_snapshot, path)
        if today_val is None or yesterday_val is None:
            continue
        delta = today_val - yesterday_val
        exceedance = abs(delta) / threshold  # >=1 means it cleared the notable bar
        if exceedance >= 1 and (best is None or exceedance > best["exceedance"]):
            good = (delta > 0) == higher_is_better
            direction = "up" if delta > 0 else "down"
            best = {
                "exceedance": exceedance,
                "text": f"{label} is {direction} {abs(round(delta, 1))}{unit} vs yesterday" + (" — nice." if good else "."),
            }

    if best:
        return {"headline": best["text"], "kind": "delta"}
    return {"headline": "Nothing stands out vs yesterday — a steady, unremarkable day.", "kind": "none"}
