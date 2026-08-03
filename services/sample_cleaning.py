"""Cleans per-sample ride data before it reaches any downstream calculation
(decoupling, zones, route map, segment selector).

Two independent problems, handled separately because they have different
failure modes and different fixes:

- **Sensor glitches** (a GPS teleport, an impossible power spike) are noise
  that should be *removed*, not trusted or smoothed — a single bad point can
  wreck a mean-max power curve or all-time PR forever if it's ever averaged
  or maxed over.
- **Short dropouts** (HR/cadence/power missing for a few seconds) are gaps
  in otherwise-good data and should be *interpolated*, not removed — removing
  samples shifts every subsequent elapsed_sec-based calculation, whereas
  interpolating a short gap keeps the timeline intact for decoupling/zone
  math that assumes even, gapless coverage.

Applied once, at the same point activity_details gets cached (see
api/main.py's activity_details endpoint) — so the fix lands in the cache
itself and every consumer (decoupling, zones, route map, segment analyzer)
benefits without each one needing its own defensive logic.
"""
from __future__ import annotations

import math
from typing import Any, Optional

# No sensor on the market reads genuine sustained power this high — a value
# above this is a glitch, not a hard sprint. (World-record standing-start
# sprints peak somewhere in the 2000-2500W range for elite track sprinters.)
_MAX_PLAUSIBLE_POWER_W = 3000

# ~230km/h — well beyond any bike, so a computed speed above this between
# consecutive GPS fixes means the fix itself teleported, not that the rider
# briefly went very fast.
_MAX_PLAUSIBLE_SPEED_MPS = 65.0

_EARTH_RADIUS_M = 6371000

# Only interpolate gaps this short; a longer dropout is a real recording gap
# that shouldn't be invented data, and should surface as-is.
_MAX_INTERPOLATE_GAP_SAMPLES = 3


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(min(1, math.sqrt(a)))


def _interpolate_gaps(samples: list[dict[str, Any]], key: str) -> int:
    """Fills a short run of None values for `key` by linearly interpolating
    between the last known value before the gap and the next known value
    after it. Returns how many values were filled."""
    filled = 0
    i = 0
    n = len(samples)
    while i < n:
        if samples[i].get(key) is not None:
            i += 1
            continue
        gap_start = i
        while i < n and samples[i].get(key) is None:
            i += 1
        gap_len = i - gap_start
        if gap_len > _MAX_INTERPOLATE_GAP_SAMPLES or gap_start == 0 or i == n:
            continue  # leave real/long/edge gaps alone rather than invent data
        before, after = samples[gap_start - 1][key], samples[i][key]
        for j in range(gap_len):
            frac = (j + 1) / (gap_len + 1)
            samples[gap_start + j][key] = before + (after - before) * frac
            filled += 1
    return filled


def clean(samples: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not samples:
        return samples, {"gps_spikes_removed": 0, "power_spikes_removed": 0, "gaps_interpolated": {}}

    gps_spikes = 0
    power_spikes = 0

    last_good_gps = None
    for s in samples:
        if s.get("power_w") is not None and s["power_w"] > _MAX_PLAUSIBLE_POWER_W:
            s["power_w"] = None
            power_spikes += 1

        if s.get("lat") is None or s.get("lon") is None:
            continue
        if last_good_gps is not None:
            prev_s, prev_lat, prev_lon = last_good_gps
            dt = (s.get("elapsed_sec") or 0) - (prev_s.get("elapsed_sec") or 0)
            if dt > 0:
                dist = _haversine_m(prev_lat, prev_lon, s["lat"], s["lon"])
                if (dist / dt) > _MAX_PLAUSIBLE_SPEED_MPS:
                    s["lat"] = None
                    s["lon"] = None
                    gps_spikes += 1
                    continue  # don't let a teleported point become the new "last good" fix
        last_good_gps = (s, s["lat"], s["lon"])

    gaps_interpolated = {
        key: _interpolate_gaps(samples, key) for key in ("hr_bpm", "cadence_rpm", "power_w")
    }
    return samples, {
        "gps_spikes_removed": gps_spikes,
        "power_spikes_removed": power_spikes,
        "gaps_interpolated": {k: v for k, v in gaps_interpolated.items() if v},
    }
