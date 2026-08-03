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


def build_profile(
    weight_kg: Optional[float], ftp_watts: Optional[float], power_curve: Optional[dict] = None
) -> dict:
    """`power_curve` (duration -> watts) defaults to the self-reported config
    bests. Callers pass the measured/merged curve so that excluding a ride with
    bad power actually moves this comparison. The 1200s row deliberately still
    reads from FTP, not from a measured 20min: the athlete's convention is
    FTP = 0.95 x a *maximal* 20min test, and the best 20min inside an ordinary
    ride is submaximal, so letting it drive this row would understate the
    category rather than correct it.
    """
    curve = POWER_CURVE_SECONDS if power_curve is None else power_curve
    if not weight_kg:
        return {"available": False, "reason": "Log your weight to compute W/kg for the Coggan comparison.", "rows": []}

    rows = []
    for coggan_duration, mapping in _MAPPING.items():
        watts = curve.get(mapping["source_duration"]) if mapping["source_duration"] else ftp_watts
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


# --- Power-profile grid (intervals.icu-style table-as-chart) -------------------
#
# The grid's trick: each duration column is scaled to its OWN W/kg range, so a
# category band sits at the same height in every column even though the numbers
# are wildly different (Cat 3 is ~12.5 W/kg at 5s but ~3.9 W/kg at 20min). The
# shared vertical axis is therefore *category position*, not watts — which is
# what makes "my 5s is Cat 3 but my 20min is Cat 5" readable at a glance, and
# what the continuous log-duration curve (build_curve) can't show.

#: Rows drawn inside each band. Three matches the reference layout and keeps the
#: ladder readable without turning it into a spreadsheet.
_ROWS_PER_BAND = 3

#: Grid columns: (Coggan reference duration, label, where the athlete's number
#: comes from). The 5s column reads the athlete's 15s best — same deliberate
#: substitution _MAPPING makes above, carried through with its caveat rather
#: than quietly pretending we measured a true 5s. None = FTP-anchored.
_GRID_COLUMNS: list[tuple[int, str, Optional[int]]] = [
    (5, "5s", 15),
    (60, "1min", 60),
    (300, "5min", 300),
    (1200, "20min", None),
]


def _band_edges(bands: dict[str, float]) -> list[dict]:
    """Category bands for one duration, bottom to top, as [low, high) in W/kg.

    Two synthetic edges are needed to close the ends: a floor below Cat 5 and a
    ceiling above Pro/UCI. Both are extrapolated by repeating the adjacent
    band's own width — the alternative (inventing named tiers like "Noob" or
    "Hero" with made-up thresholds) would be fabricating physiology we have no
    source for. They exist to bound the drawing, and are labelled as ranges
    rather than as achievements.
    """
    t = [bands[c] for c in CATEGORIES]
    floor = t[0] - (t[1] - t[0])
    ceiling = t[-1] + (t[-1] - t[-2])

    edges = [{"name": "Below Cat 5", "low": round(floor, 2), "high": t[0]}]
    for i in range(len(CATEGORIES) - 1):
        edges.append({"name": CATEGORIES[i], "low": t[i], "high": t[i + 1]})
    edges.append({"name": CATEGORIES[-1], "low": t[-1], "high": round(ceiling, 2)})
    return edges


def _wkg_to_y(wkg: float, edges: list[dict]) -> float:
    """W/kg -> shared category axis. y = band index + fraction through it."""
    for i, e in enumerate(edges):
        if wkg < e["high"]:
            span = e["high"] - e["low"]
            return max(0.0, i + ((wkg - e["low"]) / span if span else 0.0))
    last = len(edges) - 1
    span = edges[last]["high"] - edges[last]["low"]
    # Off the top of the chart is a real possibility; clamp so it still draws.
    return min(float(len(edges)), last + ((wkg - edges[last]["low"]) / span if span else 1.0))


def _y_to_wkg(y: float, edges: list[dict]) -> float:
    i = max(0, min(int(y), len(edges) - 1))
    e = edges[i]
    return e["low"] + (y - i) * (e["high"] - e["low"])


def _category_for(wkg: float, bands: dict[str, float]) -> str:
    category = "Below Cat 5"
    for c in CATEGORIES:
        if wkg >= bands[c]:
            category = c
    return category


def build_grid(
    weight_kg: Optional[float],
    ftp_watts: Optional[float],
    curves_by_window: dict[str, dict[int, float]],
) -> dict:
    """Power-profile grid: category bands as rows, durations as columns, and
    one line per time window plotted across them.

    `curves_by_window` maps a window label ("42 days", "All time") to that
    window's best watts by duration. Windows are kept separate rather than
    merged because "am I sharper than I was six weeks ago" is the question this
    chart shape exists to answer.
    """
    if not weight_kg:
        return {"available": False, "reason": "Log your weight to compute W/kg for the Coggan comparison.",
                "columns": [], "rows": [], "series": []}

    edges_by_duration = {d: _band_edges(COGGAN_WKG_BY_DURATION[d]) for d, _l, _s in _GRID_COLUMNS}
    band_count = len(next(iter(edges_by_duration.values())))

    columns = [
        {
            "duration_s": d,
            "label": label,
            "source_duration_s": source,
            "note": (
                f"Coggan's reference is {label}; your curve's nearest measured duration is {source}s"
                if source and source != d else
                ("Anchored to your current FTP" if source is None else None)
            ),
        }
        for d, label, source in _GRID_COLUMNS
    ]

    # The ladder, top row first (matches how it reads on screen). Rows sit
    # *centred inside* each band rather than on its edges, so a boundary reads
    # as the line between two rows instead of striking through one.
    rows = []
    for i in range(band_count - 1, -1, -1):
        for k in range(_ROWS_PER_BAND - 1, -1, -1):
            y = i + (k + 0.5) / _ROWS_PER_BAND
            rows.append({
                "y": round(y, 4),
                "band": edges_by_duration[5][i]["name"],
                "values": {str(d): round(_y_to_wkg(y, edges_by_duration[d]), 2) for d, _l, _s in _GRID_COLUMNS},
            })

    bands = []
    for i in range(band_count):
        name = edges_by_duration[5][i]["name"]
        bands.append({
            "name": name,
            "y_low": i,
            "y_high": i + 1,
            # A real Coggan category with a published threshold, vs. the
            # "Below Cat 5" catch-all. Pro/UCI is emphatically real — only its
            # *upper* edge is extrapolated, which is a drawing detail and not a
            # reason to render the category as if it were invented.
            "is_category": name in CATEGORIES,
            "extrapolated_edge": i in (0, band_count - 1),
        })

    series = []
    for name, curve in curves_by_window.items():
        points = []
        for d, label, source in _GRID_COLUMNS:
            watts = curve.get(source if source is not None else d)
            if source is None and ftp_watts:
                watts = max(ftp_watts, watts or 0)
            if not watts:
                continue
            wkg = watts / weight_kg
            points.append({
                "duration_s": d,
                "label": label,
                "watts": round(watts, 1),
                "wkg": round(wkg, 2),
                "y": round(_wkg_to_y(wkg, edges_by_duration[d]), 3),
                "category": _category_for(wkg, COGGAN_WKG_BY_DURATION[d]),
            })
        if points:
            series.append({"name": name, "points": points})

    return {
        "available": True,
        "weight_kg": weight_kg,
        "columns": columns,
        "rows": rows,
        "bands": bands,
        "series": series,
        "axis_note": (
            "Each column is scaled to its own W/kg range so category bands line up across durations — "
            "the vertical axis is category, not watts."
        ),
    }


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


def build_curve(
    weight_kg: Optional[float], ftp_watts: Optional[float], power_curve: Optional[dict] = None
) -> dict:
    """Full power-duration curve for a WKO/TrainingPeaks-style chart: the
    athlete's actual best power at every known duration, plus each category's
    threshold interpolated (in log-duration space) across that same duration
    range, so it renders as continuous shaded zones rather than 4 disconnected
    bars."""
    curve = POWER_CURVE_SECONDS if power_curve is None else power_curve
    if not weight_kg:
        return {"available": False, "reason": "Log your weight to compute W/kg for the Coggan comparison.", "durations": [], "your_points": [], "bands": {}}

    durations = sorted(set(curve) | ({1200} if ftp_watts else set()))

    your_points = []
    for d in durations:
        # 1200s keeps its FTP meaning, but a measured 20min that genuinely beat
        # FTP shouldn't be thrown away — take whichever is actually higher.
        watts = max(ftp_watts, curve.get(d) or 0) if d == 1200 and ftp_watts else curve.get(d)
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
