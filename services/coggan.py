"""Maps the athlete's own power-curve durations onto the nearest Coggan
reference duration for comparison, rather than pretending our data matches
Coggan's exact 5s/60s/300s/1200s durations precisely."""
from __future__ import annotations

import math
from typing import Optional

from config.athlete_profile import POWER_CURVE_SECONDS, POWER_CURVE_UNVERIFIED
from config.coggan_profile import CATEGORIES, COGGAN_WKG_BY_DURATION

_MAPPING = {
    5: {"source_duration": 15, "label": "Neuromuscular (~15s; Coggan reference is 5s)"},
    60: {"source_duration": 60, "label": "Anaerobic Capacity (1min)"},
    300: {"source_duration": 300, "label": "VO2max (5min; self-reported as not a max effort)"},
    1200: {"source_duration": None, "label": "Functional Threshold (current FTP; Coggan reference is 20min)"},
}


def build_profile(weight_kg: Optional[float], ftp_watts: Optional[float]) -> dict:
    if not weight_kg:
        return {"available": False, "reason": "Log your weight to compute W/kg for the Coggan comparison.", "rows": []}

    rows = []
    for coggan_duration, mapping in _MAPPING.items():
        watts = POWER_CURVE_SECONDS.get(mapping["source_duration"]) if mapping["source_duration"] else ftp_watts
        if watts is None:
            continue
        wkg = round(watts / weight_kg, 2)
        bands = COGGAN_WKG_BY_DURATION[coggan_duration]

        category = "Below Cat 5"
        for cat in CATEGORIES:
            if wkg >= bands[cat]:
                category = cat

        rows.append({"label": mapping["label"], "watts": watts, "wkg": wkg, "category": category, "bands": bands})

    def _rank(row):
        return CATEGORIES.index(row["category"]) if row["category"] in CATEGORIES else -1

    weakest = min(rows, key=_rank) if rows else None
    return {"available": True, "rows": rows, "weakest_zone": weakest["label"] if weakest else None}


def _log_interp(duration_s: int, anchors: list[tuple[int, float]]) -> float:
    """Log-duration interpolation between Coggan's 4 reference points, clamped
    at the ends (5s and 1200s) — we don't extrapolate a category's threshold
    beyond the range Coggan's chart actually defines."""
    if duration_s <= anchors[0][0]:
        return anchors[0][1]
    if duration_s >= anchors[-1][0]:
        return anchors[-1][1]
    for (d0, v0), (d1, v1) in zip(anchors, anchors[1:]):
        if d0 <= duration_s <= d1:
            t = (math.log(duration_s) - math.log(d0)) / (math.log(d1) - math.log(d0))
            return v0 + t * (v1 - v0)
    return anchors[-1][1]


def build_curve(weight_kg: Optional[float], ftp_watts: Optional[float]) -> dict:
    """Full power-duration curve for a WKO/TrainingPeaks-style chart: the
    athlete's actual best power at every known duration, plus each category's
    threshold interpolated (in log-duration space) across that same duration
    range, so it renders as continuous shaded zones rather than 4 disconnected
    bars."""
    if not weight_kg:
        return {"available": False, "reason": "Log your weight to compute W/kg for the Coggan comparison.", "durations": [], "your_points": [], "bands": {}}

    durations = sorted(set(POWER_CURVE_SECONDS) | ({1200} if ftp_watts else set()))

    your_points = []
    for d in durations:
        watts = ftp_watts if d == 1200 else POWER_CURVE_SECONDS.get(d)
        if watts is None:
            continue
        your_points.append({
            "duration_s": d,
            "watts": watts,
            "wkg": round(watts / weight_kg, 2),
            "unverified": d in POWER_CURVE_UNVERIFIED,
        })

    bands: dict[str, list[dict]] = {}
    for cat in CATEGORIES:
        anchors = sorted((d, cat_bands[cat]) for d, cat_bands in COGGAN_WKG_BY_DURATION.items())
        bands[cat] = [
            {"duration_s": d, "watts": round(_log_interp(d, anchors) * weight_kg, 1)}
            for d in durations
        ]

    return {"available": True, "durations": durations, "your_points": your_points, "bands": bands}
