"""Is the athlete due for an FTP test, and is today a good day for it?

Two separate questions, deliberately kept apart: *due* is about how stale the
number is, *ready* is about whether today would produce a representative
result. Being due doesn't make a fatigued Tuesday a good test day.

This also closes the loop on the trajectory forecast, which currently can't
project anything useful because there are only two tests on record — rather
than just reporting that gap, this says when to fix it.
"""
from __future__ import annotations

from datetime import date as date_
from typing import Any, Optional

from database import local_store
from services.readiness import NON_NEGOTIABLE_WEEKDAY

# Six weeks is the conventional retest interval — long enough for a training
# block to have moved the number, short enough that the FTP driving your zones
# isn't badly stale.
_RETEST_INTERVAL_DAYS = 42
_DUE_SOON_DAYS = 7

# Form (TSB) above this means rested enough for a representative maximal
# effort. Testing deep in the hole measures fatigue, not fitness.
_MIN_FORM_TO_TEST = -10


def assess(form: Optional[float] = None, block_week: Optional[int] = None, today: Optional[date_] = None) -> dict[str, Any]:
    today = today or date_.today()
    history = local_store.get_ftp_history()
    block_week = block_week if block_week is not None else local_store.get_block_week()

    if not history:
        return {
            "due": True,
            "days_since_test": None,
            "message": "No FTP test on record — one would anchor your zones and your trajectory forecast.",
            "ready_today": None,
        }

    last = history[-1]
    days_since = (today - date_.fromisoformat(last["date"])).days
    days_until_due = _RETEST_INTERVAL_DAYS - days_since
    due = days_until_due <= 0

    reasons_against = []
    if today.weekday() == NON_NEGOTIABLE_WEEKDAY:
        reasons_against.append("today is the team ride")
    if form is not None and form < _MIN_FORM_TO_TEST:
        reasons_against.append(f"Form is {form:.0f} — too fatigued for a representative result")
    if block_week in (1, 2, 3) and form is None:
        # Without Form data, block week is the only fatigue proxy available.
        reasons_against.append(f"you're in block week {block_week} (loading) — test after a recovery week")

    ready_today = due and not reasons_against

    if not due:
        message = (
            f"Last tested {days_since} days ago ({last['date']}, {last['ftp_w']}W). "
            f"Next test due in {days_until_due} days."
        )
        if days_until_due <= _DUE_SOON_DAYS:
            message += " Worth planning it into the end of this block."
    elif ready_today:
        message = (
            f"Due for a test — last one was {days_since} days ago ({last['ftp_w']}W), and today looks like a good day "
            f"for it{f' (Form {form:.0f})' if form is not None else ''}."
        )
    else:
        message = (
            f"Overdue by {abs(days_until_due)} days (last test {last['date']}, {last['ftp_w']}W), but not today — "
            + " and ".join(reasons_against)
            + "."
        )

    if len(history) < 3:
        message += (
            f" You have {len(history)} test{'s' if len(history) != 1 else ''} logged; a third unlocks the "
            "trajectory forecast."
        )

    return {
        "due": due,
        "ready_today": ready_today,
        "days_since_test": days_since,
        "days_until_due": days_until_due,
        "last_test": last,
        "test_count": len(history),
        "message": message,
    }
