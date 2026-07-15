"""Current-FTP resolution.

Manual test log takes priority (project convention: FTP = 0.95 x best 20min
power). Garmin's own auto-estimate is only a fallback
for when no manual test has been logged yet, since the athlete's stated
convention treats manual tests as the source of truth.
"""
from __future__ import annotations

from typing import Optional

from database import local_store


def current_ftp(garmin_ftp_watts: Optional[float] = None) -> dict:
    latest = local_store.get_latest_manual_ftp()
    if latest:
        return {"ftp_watts": latest["ftp_w"], "source": "manual", "date": latest["date"]}
    if garmin_ftp_watts:
        return {"ftp_watts": garmin_ftp_watts, "source": "garmin_estimate", "date": None}
    return {"ftp_watts": None, "source": None, "date": None}
