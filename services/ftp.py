"""Current-FTP resolution.

Priority, strongest evidence first:

1. **Manual test log** — the athlete's stated convention (FTP = 0.95 x best
   20min) applied to a deliberate, maximal 20min effort. Source of truth.
2. **Measured 20min** — the same convention applied to the best 20min block
   found in actual ride data. Ranked below a manual test on purpose: the best
   20min inside an ordinary ride is almost always submaximal (verified on real
   data — a stop-start interval ride measured 187W against a 219.4W tested
   FTP), so it is evidence, not a test result. It still outranks Garmin's
   estimate, because it's the athlete's own convention on the athlete's own
   power data rather than a proprietary black box.
3. **Garmin's auto-estimate** — last resort when nothing else exists.

`alternatives` always reports every candidate, so a lower-ranked source that
disagrees is visible rather than silently discarded — and so excluding a
miscalibrated ride visibly moves the measured number.
"""
from __future__ import annotations

from typing import Any, Optional

from database import local_store


def current_ftp(
    garmin_ftp_watts: Optional[float] = None, measured: Optional[dict[str, Any]] = None
) -> dict:
    alternatives = {
        "manual": None,
        "measured_20min": measured,
        "garmin_estimate": {"ftp_watts": garmin_ftp_watts} if garmin_ftp_watts else None,
    }

    latest = local_store.get_latest_manual_ftp()
    if latest:
        alternatives["manual"] = {"ftp_watts": latest["ftp_w"], "date": latest["date"]}
        return {
            "ftp_watts": latest["ftp_w"],
            "source": "manual",
            "date": latest["date"],
            "alternatives": alternatives,
        }
    if measured:
        return {
            "ftp_watts": measured["ftp_watts"],
            "source": "measured_20min",
            "date": measured.get("date"),
            "alternatives": alternatives,
        }
    if garmin_ftp_watts:
        return {
            "ftp_watts": garmin_ftp_watts,
            "source": "garmin_estimate",
            "date": None,
            "alternatives": alternatives,
        }
    return {"ftp_watts": None, "source": None, "date": None, "alternatives": alternatives}
