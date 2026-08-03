"""Detects power data that *looks* miscalibrated, and says so — nothing else.

This never excludes anything. It returns suggestions the athlete confirms or
dismisses, because every signal here has an innocent explanation:

- Power while coasting is the classic un-zeroed / drifting offset, but it's
  also just what happens on a trainer with flywheel spin-down, or with a
  cadence sensor that dropped out while you were genuinely pedalling.
- A huge spike is usually a dropout artefact, but it's also what a real
  standing sprint looks like — this athlete's own self-reported 1s best is
  1023W, comfortably above a naive "implausible" line.
- Power that doesn't track HR/cadence at all suggests a constant offset, but
  it's equally what an easy spin, an interval rest block, or a ride with a
  flaky HR strap looks like.

Guessing wrong in the exclusion direction silently deletes real bests, which is
strictly worse than showing a prompt. So: suggest, explain, let the human
decide. Same "visible recommendation, not silent rewrite" rule the adaptive
load advisory and periodization recommendation already follow.
"""
from __future__ import annotations

from typing import Any, Optional

#: Above the highest sprint any rider in this app plausibly produces. Kept well
#: clear of the athlete's own 1023W self-reported 1s best so a real sprint is
#: never flagged; this is aimed at dropout artefacts (4000W+), not big efforts.
_IMPLAUSIBLE_SPIKE_W = 2000

#: Multiple of the athlete's own known 1s best that counts as implausible when
#: that best is known — scales the check to the rider instead of a fixed line.
_KNOWN_MAX_MULTIPLE = 1.5

#: Power above this while not pedalling reads as offset drift rather than noise.
_COASTING_POWER_W = 50
_COASTING_MIN_SAMPLES = 10


def _spike_flag(samples: list[dict[str, Any]], known_max_w: Optional[float]) -> Optional[dict[str, Any]]:
    ceiling = _IMPLAUSIBLE_SPIKE_W
    if known_max_w:
        ceiling = min(ceiling, known_max_w * _KNOWN_MAX_MULTIPLE)

    spikes = [s for s in samples if (s.get("power_w") or 0) > ceiling]
    if not spikes:
        return None
    worst = max(spikes, key=lambda s: s["power_w"])
    return {
        "code": "implausible_spike",
        "severity": "high",
        "detail": (
            f"{len(spikes)} sample(s) above {int(ceiling)}W, peaking at {int(worst['power_w'])}W. "
            "A spike like this is usually a recording artefact rather than a real effort, and it "
            "will set a permanent all-time best if it stays in."
        ),
        "suggested_ranges": [
            {"start_sec": int(s["elapsed_sec"]), "end_sec": int(s["elapsed_sec"])} for s in spikes
        ],
    }


def _coasting_flag(samples: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    coasting = [
        s for s in samples
        if s.get("cadence_rpm") == 0 and (s.get("power_w") or 0) > _COASTING_POWER_W
    ]
    if len(coasting) < _COASTING_MIN_SAMPLES:
        return None
    avg = sum(s["power_w"] for s in coasting) / len(coasting)
    return {
        "code": "power_while_coasting",
        "severity": "medium",
        "detail": (
            f"{len(coasting)} samples show ~{int(avg)}W average while cadence was zero. "
            "That pattern is typical of a power meter that needs a zero-offset reset — though "
            "trainer flywheel spin-down or a dropped cadence sensor look the same."
        ),
        "suggested_ranges": [],
    }


def _decoupling_flag(samples: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Power that never varies with effort suggests a stuck reading or a
    constant offset. Deliberately narrow: only fires when power is essentially
    flat across a ride whose HR/cadence clearly weren't."""
    powered = [s for s in samples if s.get("power_w") is not None]
    if len(powered) < 60:
        return None

    powers = [s["power_w"] for s in powered]
    cadences = [s["cadence_rpm"] for s in powered if s.get("cadence_rpm") is not None]
    if len(cadences) < 60:
        return None

    power_range = max(powers) - min(powers)
    cadence_range = max(cadences) - min(cadences)
    if power_range > 20 or cadence_range < 30:
        return None
    return {
        "code": "power_not_tracking_effort",
        "severity": "medium",
        "detail": (
            f"Power stayed within {int(power_range)}W all ride while cadence varied by "
            f"{int(cadence_range)}rpm. A reading that flat usually means a stuck sensor or a "
            "constant offset rather than genuinely steady effort."
        ),
        "suggested_ranges": [],
    }


def inspect(samples: list[dict[str, Any]], known_max_w: Optional[float] = None) -> list[dict[str, Any]]:
    """Calibration red flags for one ride, worst first. Empty list = nothing
    suspicious, which is the expected result for a healthy ride."""
    if not samples:
        return []
    flags = [
        _spike_flag(samples, known_max_w),
        _coasting_flag(samples),
        _decoupling_flag(samples),
    ]
    found = [f for f in flags if f]
    return sorted(found, key=lambda f: 0 if f["severity"] == "high" else 1)
