"""Heuristic rider-type classification (sprinter/puncheur/climber/TT) from the
power-duration curve relative to FTP.

ASSUMPTION / CAVEAT: this is a simplified approximation loosely modeled on the
standard "power profile" approach used by tools like WKO/TrainingPeaks
(comparing relative multiples of FTP at different durations) — NOT a rigorous
sports-science model. The reference ratios below are commonly-cited ballpark
figures, not personally calibrated. Two inputs (2min, 5min power) are flagged
elsewhere as not-confirmed-max-effort, which may understate puncheur/climber
scores specifically.
"""
from __future__ import annotations

from typing import Optional

from config.athlete_profile import POWER_CURVE_SECONDS

# Duration (seconds) buckets mapped to the archetype each is most indicative of.
_BUCKETS = {
    "sprinter": [1, 15],
    "puncheur": [30, 60, 120],
    "climber_diesel": [300, 600],
    "tt_rouleur": [3600],
}

# Rough typical power-as-multiple-of-FTP reference points per archetype/duration
# bucket (e.g. a 5s sprint effort is commonly ~4-7x FTP for a strong rider) —
# used to normalize so raw FTP-multiples are comparable across buckets.
_REFERENCE_MULTIPLE = {"sprinter": 6.5, "puncheur": 2.2, "climber_diesel": 1.15, "tt_rouleur": 0.84}

_LABELS = {
    "sprinter": "Sprinter",
    "puncheur": "Puncheur",
    "climber_diesel": "Climber / Diesel engine",
    "tt_rouleur": "Time-trialist / Rouleur",
}


def classify(ftp_watts: Optional[float]) -> dict:
    if not ftp_watts:
        return {"type": None, "scores": {}, "note": "No current FTP available yet."}

    ratios = {d: w / ftp_watts for d, w in POWER_CURVE_SECONDS.items()}

    bucket_scores = {}
    for archetype, durations in _BUCKETS.items():
        vals = [ratios[d] for d in durations if d in ratios]
        bucket_scores[archetype] = (sum(vals) / len(vals)) if vals else 0.0

    relative_scores = {k: round(bucket_scores[k] / _REFERENCE_MULTIPLE[k], 2) for k in bucket_scores}
    dominant = max(relative_scores, key=relative_scores.get)

    return {
        "type": _LABELS[dominant],
        "scores": {_LABELS[k]: v for k, v in relative_scores.items()},
        "note": (
            "Heuristic estimate from your power-duration curve shape relative to FTP — "
            "not a lab test. 2min/5min inputs are self-reported as not confirmed max efforts."
        ),
    }
