"""Per-ride analysis: aerobic decoupling (Pw:Hr drift).

Decoupling splits a ride in half and compares the power-to-heart-rate ratio
of each half. If the second half needs more heartbeats for the same watts,
the ratio drops and the ride "decoupled" — the standard read is that under
~5% means aerobic durability is holding for that duration, and more means
you're outrunning your base.

Needs power *and* HR throughout, so for this athlete it only works on indoor
KICKR sessions until the outdoor power meter arrives (~Aug 2026) — callers
get an explicit `available: False` + reason rather than a fabricated number.
"""
from __future__ import annotations

from typing import Any, Optional

# Coggan's conventional read of Pw:Hr drift on an aerobic effort.
_GOOD_THRESHOLD_PCT = 5.0
# Below this the halves are too short for the ratio to mean anything.
_MIN_SAMPLES_PER_HALF = 60


def _mean(values: list[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _half_ratio(samples: list[dict[str, Any]]) -> Optional[float]:
    """Pw:Hr for one half — mean power over mean HR, using only samples that
    have both (a dropout in either would otherwise skew one mean)."""
    paired = [(s["power_w"], s["hr_bpm"]) for s in samples if s.get("power_w") is not None and s.get("hr_bpm")]
    if len(paired) < _MIN_SAMPLES_PER_HALF:
        return None
    avg_power = _mean([p for p, _ in paired])
    avg_hr = _mean([h for _, h in paired])
    if not avg_hr:
        return None
    return avg_power / avg_hr


def decoupling(samples: list[dict[str, Any]], has_power: bool = True) -> dict[str, Any]:
    if not samples:
        return {"available": False, "reason": "No sample data for this ride."}

    has_any_power = any(s.get("power_w") is not None for s in samples)
    if not has_any_power or not has_power:
        return {
            "available": False,
            "reason": "No power data on this ride — decoupling needs power and heart rate together. "
            "This will activate for outdoor rides when your power meter arrives.",
        }
    if not any(s.get("hr_bpm") for s in samples):
        return {"available": False, "reason": "No heart-rate data on this ride."}

    midpoint = len(samples) // 2
    first = _half_ratio(samples[:midpoint])
    second = _half_ratio(samples[midpoint:])
    if first is None or second is None or first == 0:
        return {"available": False, "reason": "Not enough paired power + heart-rate samples to split this ride."}

    # Positive = second half needed more heartbeats per watt = decoupled.
    pct = ((first - second) / first) * 100
    return {
        "available": True,
        "decoupling_pct": round(pct, 1),
        "first_half_pw_hr": round(first, 3),
        "second_half_pw_hr": round(second, 3),
        "good": pct < _GOOD_THRESHOLD_PCT,
        "threshold_pct": _GOOD_THRESHOLD_PCT,
    }
