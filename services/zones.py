"""Time-in-zone for a ride, from the cached per-sample series.

The dashboard prescribes zones but has never checked whether they were
actually ridden — "you planned 75min of Z2 and spent 40% of it in Z3" is the
gap this closes.

Samples are ~1/sec but not guaranteed evenly spaced, so time per zone is
summed from the gap between consecutive `elapsed_sec` values rather than by
counting samples. Counting would silently mis-weight any ride with recording
gaps or smart-recording.
"""
from __future__ import annotations

from typing import Any, Optional

from config.athlete_profile import LTHR_BPM
from config.zones import HR_ZONES, POWER_ZONES

# Ignore absurd gaps (paused ride, tunnel, device asleep) rather than
# attributing an hour of "Z1" to a single stopped sample.
_MAX_SAMPLE_GAP_SEC = 30


def _zone_for(value: float, zones: list[tuple[str, float, float]], reference: float) -> Optional[str]:
    fraction = value / reference
    for name, low, high in zones:
        if low <= fraction < high:
            return name
    return zones[-1][0] if fraction >= zones[-1][1] else None


def _accumulate(
    samples: list[dict[str, Any]], key: str, zones: list[tuple[str, float, float]], reference: float
) -> dict[str, float]:
    totals = {name: 0.0 for name, _, _ in zones}
    previous_elapsed = None
    for sample in samples:
        elapsed = sample.get("elapsed_sec")
        value = sample.get(key)
        if elapsed is None:
            continue
        if previous_elapsed is not None and value:
            gap = elapsed - previous_elapsed
            if 0 < gap <= _MAX_SAMPLE_GAP_SEC:
                zone = _zone_for(value, zones, reference)
                if zone:
                    totals[zone] += gap
        previous_elapsed = elapsed
    return totals


def _as_rows(totals: dict[str, float]) -> list[dict[str, Any]]:
    total = sum(totals.values())
    return [
        {
            "zone": name,
            "seconds": round(seconds),
            "minutes": round(seconds / 60, 1),
            "pct": round((seconds / total) * 100, 1) if total else 0.0,
        }
        for name, seconds in totals.items()
    ]


def time_in_zone(samples: list[dict[str, Any]], ftp_watts: Optional[float]) -> dict[str, Any]:
    if not samples:
        return {"power": None, "hr": None, "reason": "No sample data for this ride."}

    power = None
    if ftp_watts and any(s.get("power_w") is not None for s in samples):
        rows = _as_rows(_accumulate(samples, "power_w", POWER_ZONES, ftp_watts))
        if any(r["seconds"] for r in rows):
            power = {"rows": rows, "reference": f"{round(ftp_watts)}W FTP"}

    hr = None
    if any(s.get("hr_bpm") for s in samples):
        rows = _as_rows(_accumulate(samples, "hr_bpm", HR_ZONES, LTHR_BPM))
        if any(r["seconds"] for r in rows):
            hr = {"rows": rows, "reference": f"{LTHR_BPM}bpm threshold HR"}

    return {
        "power": power,
        "hr": hr,
        "reason": None if (power or hr) else "No power or heart-rate data on this ride.",
    }
