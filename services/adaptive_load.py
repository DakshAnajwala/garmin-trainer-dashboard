"""Adaptive load advisory: flags when recent training load suggests pulling
back, without silently rewriting the plan.

A real training plan shouldn't rewrite itself with no visible trace of what
changed or why — that's the same reasoning as [[apply_constraints]]'s
race-taper note. This is a visible suggestion surfaced alongside the
prescription, not a mutation of it. The athlete (or the plan) decides what
to do with it.

Garmin's own acute:chronic workload ratio (ACWR) is the primary signal
since it's always available from a snapshot, no intervals.icu required.
Form (from intervals.icu, if connected) is a secondary, richer signal —
this is the same TSB-style number the PMC chart already shows.
"""
from __future__ import annotations

from typing import Any, Optional

# ACWR bands are the widely-cited Gabbett sports-science convention: the
# "sweet spot" is roughly 0.8-1.3; above ~1.5 injury/overreaching risk rises
# sharply; well below 0.8 suggests detraining. Not Garmin-specific — Garmin
# just supplies the raw number.
_ACWR_HIGH = 1.5
_ACWR_LOW = 0.8

# Form more negative than this is generally read as overreaching territory.
_FORM_LOW = -25


def assess(acwr: Optional[float], acwr_status: Optional[str], form: Optional[float]) -> dict[str, Any]:
    if acwr is not None and acwr >= _ACWR_HIGH:
        return {
            "flagged": True,
            "severity": "warning",
            "message": (
                f"Acute:chronic load ratio is {acwr:.2f} (Garmin: {acwr_status or 'elevated'}) — "
                "ramping faster than your recent average. Worth considering an easier week rather than "
                "pushing the full prescription."
            ),
        }
    if form is not None and form <= _FORM_LOW:
        return {
            "flagged": True,
            "severity": "warning",
            "message": (
                f"Form is {form:.0f} — deep in overreaching territory. Consider pulling back this week's "
                "intensity even if the plan calls for a hard session."
            ),
        }
    if acwr is not None and acwr <= _ACWR_LOW:
        return {
            "flagged": True,
            "severity": "info",
            "message": (
                f"Acute:chronic load ratio is {acwr:.2f} (Garmin: {acwr_status or 'low'}) — load has "
                "dropped well below your recent average. Fine after a planned recovery week; if not, this is room to push."
            ),
        }
    return {"flagged": False, "severity": "info", "message": None}
