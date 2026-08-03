"""Course-specific demand modeling: what will *this* course ask of *this*
rider, on the day, in those conditions?

Pipeline: route file → cleaned elevation → gradient segmentation → per-segment
physics (gravity + rolling + aero, with air density from altitude/weather) →
condition derates (altitude O₂, heat) → demand profile → gap report against
the athlete's physiology model (F6).

Everything downstream of the raw track is derived and reproducible: the stored
profile carries its full input snapshot (route hash, mass, conditions and
where they came from, model params used), and recomputes whenever any input
changes — with a before/after diff so the change is visible, not silent.

The pacing model behind "demand" (a deliberate, stated choice): demands are
computed at the pace *this rider* could actually ride — decisive climbs at
95% of condition-derated CP, flats at endurance pace, descents coasting —
because "what the course asks of you" is only meaningful relative to your own
engine. A generic race-winner's speed would produce demands unrelated to this
athlete's day.

Physics notes:
- Required power at speed v on gradient θ:
  P = v·(½ρ·CdA·v² + m·g·(Crr·cosθ + sinθ)) / η   (η = drivetrain efficiency)
- Air density from altitude + temperature + humidity + pressure (Magnus vapor
  pressure; barometric lapse when no measured pressure) — density falls with
  altitude, so flats/descents get *easier* even as the rider's engine shrinks.
- Altitude derate of aerobic power: Bassett et al. (1999) acclimatized-athlete
  cubic, %sea-level = 0.178·h³ − 1.43·h² − 4.07·h + 100 (h in km). ~95% at
  1000 m, ~88% at 2000 m, ~80% at 3000 m — steeper as you go up.
- Heat derate: ~2% of aerobic ceiling per °C of wet-bulb temperature above
  18 °C, scaled up with event duration (heat strain compounds), capped at 25%.
  Cold is treated as neutral. This is a mid-range reading of the heat-
  performance literature, not a personal measurement — stated in the output.
- Wind: left out unless explicitly provided. Climatological wind averages are
  unreliable at ride scale; the profile says the assumption instead of guessing.
"""
from __future__ import annotations

import hashlib
import math
import time
from typing import Any, Optional

from defusedxml import ElementTree as SafeET

from database import local_store

# --- Physical constants -------------------------------------------------------

_G = 9.80665
_GAS_CONSTANT_DRY = 287.058  # J/(kg·K)
_DRIVETRAIN_EFF = 0.975
_CRR = 0.004  # good road tires on asphalt

#: CdA by riding position — coarse published ballparks; the aero tab captures
#: position but no measured CdA yet, so these are assumptions and say so.
_CDA_BY_POSITION = {"relaxed": 0.35, "aero": 0.30, "tt": 0.25}
_DEFAULT_BIKE_KIT_KG = 9.0

# --- Elevation cleaning / segmentation ----------------------------------------

_RESAMPLE_M = 10.0
_SMOOTH_WINDOW = 7  # x10m = 70m of smoothing after resample
_SPIKE_MEDIAN_WINDOW = 5
_CLIMB_MIN_M = 500.0
_CLIMB_MIN_GRADE = 0.03
_SURGE_MAX_M = 300.0
_SURGE_MIN_GRADE = 0.06
_DESCENT_GRADE = -0.03

# --- Pacing model (stated assumption, see module docstring) -------------------

_CLIMB_CP_FRACTION = 0.95
_FLAT_CP_FRACTION = 0.68
_DESCENT_CP_FRACTION = 0.10
_MAX_DESCENT_SPEED = 25.0  # m/s — safety cap, nobody descends at physics-limit
_SURGE_RECOVERY_WINDOW_SEC = 300  # punches closer than this compound

_HEAT_DERATE_PER_C = 0.02
_HEAT_WBT_THRESHOLD_C = 18.0
_HEAT_MAX_DERATE = 0.25


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(a))


# --- Route parsing (defusedxml — route files are untrusted input) -------------


def parse_route(content: bytes, filename: str) -> list[dict[str, float]]:
    """GPX or TCX track → [{lat, lon, ele_m}]. FIT routes aren't supported yet
    (binary format, separate parser) — the error says so instead of guessing."""
    name = filename.lower()
    if name.endswith(".gpx"):
        return _parse_gpx(content)
    if name.endswith(".tcx"):
        return _parse_tcx(content)
    raise ValueError("Route must be .gpx or .tcx (FIT route files aren't supported yet).")


def _parse_gpx(content: bytes) -> list[dict[str, float]]:
    root = SafeET.fromstring(content)
    ns = {"gpx": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}
    tag = ".//gpx:trkpt" if ns else ".//trkpt"
    points = []
    for pt in root.findall(tag, ns) or root.findall(".//rtept", ns) or root.findall(".//gpx:rtept", ns):
        ele = pt.find("gpx:ele", ns) if ns else pt.find("ele")
        points.append({
            "lat": float(pt.get("lat")),
            "lon": float(pt.get("lon")),
            "ele_m": float(ele.text) if ele is not None and ele.text else 0.0,
        })
    if len(points) < 10:
        raise ValueError(f"Route contains only {len(points)} track points — not enough to model.")
    return points


def _parse_tcx(content: bytes) -> list[dict[str, float]]:
    root = SafeET.fromstring(content)
    ns = {"tcx": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}
    points = []
    for tp in root.findall(".//tcx:Trackpoint" if ns else ".//Trackpoint", ns):
        pos = tp.find("tcx:Position" if ns else "Position", ns)
        if pos is None:
            continue
        lat = pos.find("tcx:LatitudeDegrees" if ns else "LatitudeDegrees", ns)
        lon = pos.find("tcx:LongitudeDegrees" if ns else "LongitudeDegrees", ns)
        alt = tp.find("tcx:AltitudeMeters" if ns else "AltitudeMeters", ns)
        if lat is None or lon is None:
            continue
        points.append({
            "lat": float(lat.text),
            "lon": float(lon.text),
            "ele_m": float(alt.text) if alt is not None and alt.text else 0.0,
        })
    if len(points) < 10:
        raise ValueError(f"Route contains only {len(points)} usable track points.")
    return points


# --- Elevation cleaning (bad elevation ruins gradient — first-class step) -----


def clean_elevation(points: list[dict[str, float]]) -> dict[str, Any]:
    """Median-filter spikes, resample to an even distance grid, then smooth.
    Returns the grid plus a report of what was done — cleaning that can't be
    inspected is cleaning that can't be trusted."""
    dist = [0.0]
    for a, b in zip(points, points[1:]):
        dist.append(dist[-1] + _haversine_m(a["lat"], a["lon"], b["lat"], b["lon"]))

    ele = [p["ele_m"] for p in points]

    # 1. median filter kills single-point barometric/GPS spikes
    half = _SPIKE_MEDIAN_WINDOW // 2
    median_ele = [
        sorted(ele[max(0, i - half): i + half + 1])[len(ele[max(0, i - half): i + half + 1]) // 2]
        for i in range(len(ele))
    ]
    spikes_removed = sum(1 for a, b in zip(ele, median_ele) if abs(a - b) > 3.0)

    # 2. resample to an even grid so gradients are per-distance, not per-point
    total = dist[-1]
    n_grid = max(2, int(total / _RESAMPLE_M))
    grid_d = [i * _RESAMPLE_M for i in range(n_grid + 1)]
    grid_e = []
    j = 0
    for d in grid_d:
        while j < len(dist) - 2 and dist[j + 1] < d:
            j += 1
        span = dist[j + 1] - dist[j]
        t = (d - dist[j]) / span if span > 0 else 0.0
        grid_e.append(median_ele[j] + t * (median_ele[j + 1] - median_ele[j]))

    # 3. moving-average smooth
    half = _SMOOTH_WINDOW // 2
    smooth_e = [
        sum(grid_e[max(0, i - half): i + half + 1]) / len(grid_e[max(0, i - half): i + half + 1])
        for i in range(len(grid_e))
    ]

    return {
        "distance_m": grid_d,
        "elevation_m": smooth_e,
        "total_m": total,
        "report": {
            "source_points": len(points),
            "spikes_removed": spikes_removed,
            "resampled_to_m": _RESAMPLE_M,
            "smoothing_window_m": _SMOOTH_WINDOW * _RESAMPLE_M,
        },
    }


def segment_route(grid: dict[str, Any]) -> list[dict[str, Any]]:
    """Split the cleaned grid into climbs / descents / flats / rollers / surges.

    A surge is a short steep pitch (<300 m at ≥6%) — the punchy stuff that
    breaks groups; a climb is sustained (≥500 m at ≥3% average)."""
    d, e = grid["distance_m"], grid["elevation_m"]
    n = len(d)
    grades = [(e[i + 1] - e[i]) / _RESAMPLE_M for i in range(n - 1)]

    segments: list[dict[str, Any]] = []
    i = 0
    while i < len(grades):
        g = grades[i]
        if g >= _CLIMB_MIN_GRADE:
            j = i
            slack = 0
            while j < len(grades) and slack < 5:  # allow ~50m of easing without ending the climb
                if grades[j] >= _CLIMB_MIN_GRADE * 0.6:
                    slack = 0
                else:
                    slack += 1
                j += 1
            j = min(j, len(grades))
            length = (j - i) * _RESAMPLE_M
            gain = e[j] - e[i]
            avg_grade = gain / length if length else 0.0
            if length <= _SURGE_MAX_M and avg_grade >= _SURGE_MIN_GRADE:
                kind = "surge"
            elif length >= _CLIMB_MIN_M and avg_grade >= _CLIMB_MIN_GRADE:
                kind = "climb"
            else:
                kind = "roller"
            segments.append(_seg(kind, d[i], d[j], e[i], e[j]))
            i = j
        elif g <= _DESCENT_GRADE:
            j = i
            while j < len(grades) and grades[j] <= _DESCENT_GRADE * 0.5:
                j += 1
            segments.append(_seg("descent", d[i], d[j], e[i], e[j]))
            i = j
        else:
            j = i
            while j < len(grades) and _DESCENT_GRADE < grades[j] < _CLIMB_MIN_GRADE:
                j += 1
            segments.append(_seg("flat", d[i], d[j], e[i], e[j]))
            i = j

    return [s for s in segments if s["length_m"] >= _RESAMPLE_M]


def _seg(kind: str, d0: float, d1: float, e0: float, e1: float) -> dict[str, Any]:
    length = d1 - d0
    return {
        "kind": kind,
        "start_m": round(d0),
        "end_m": round(d1),
        "length_m": round(length),
        "gain_m": round(e1 - e0, 1),
        "avg_grade": round((e1 - e0) / length, 4) if length else 0.0,
        "start_ele_m": round(e0, 1),
        "end_ele_m": round(e1, 1),
    }


# --- Conditions: air density, altitude derate, heat derate ---------------------


def air_density(elevation_m: float, temp_c: float, humidity_pct: float, pressure_pa: Optional[float] = None) -> float:
    """kg/m³. Humidity matters twice: vapor pressure lowers density here, and
    drives the wet-bulb heat term below."""
    if pressure_pa is None:
        pressure_pa = 101325 * (1 - 2.25577e-5 * elevation_m) ** 5.25588
    temp_k = temp_c + 273.15
    # Magnus saturation vapor pressure (Pa), scaled by relative humidity
    svp = 610.94 * math.exp(17.625 * temp_c / (temp_c + 243.04))
    vapor = svp * humidity_pct / 100
    return (pressure_pa / (_GAS_CONSTANT_DRY * temp_k)) * (1 - 0.378 * vapor / pressure_pa)


def altitude_power_fraction(elevation_m: float) -> float:
    """Fraction of sea-level aerobic power available (acclimatized athlete,
    Bassett et al. 1999). Below 300 m the effect is noise — treated as 1.0."""
    if elevation_m < 300:
        return 1.0
    h = elevation_m / 1000
    pct = 0.178 * h**3 - 1.43 * h**2 - 4.07 * h + 100
    return max(0.5, pct / 100)


def wet_bulb_c(temp_c: float, humidity_pct: float) -> float:
    """Stull (2011) approximation — good to ~0.3°C in normal ranges."""
    rh = humidity_pct
    return (
        temp_c * math.atan(0.151977 * math.sqrt(rh + 8.313659))
        + math.atan(temp_c + rh)
        - math.atan(rh - 1.676331)
        + 0.00391838 * rh**1.5 * math.atan(0.023101 * rh)
        - 4.686035
    )


def heat_power_fraction(temp_c: float, humidity_pct: float, event_hours: float) -> float:
    """Heat strain compounds with duration: the derate scales from ~40% of full
    effect for a 1h event to full effect at 3h+."""
    wbt = wet_bulb_c(temp_c, humidity_pct)
    if wbt <= _HEAT_WBT_THRESHOLD_C:
        return 1.0
    duration_scale = min(1.0, max(0.4, event_hours / 3))
    derate = min(_HEAT_MAX_DERATE, _HEAT_DERATE_PER_C * (wbt - _HEAT_WBT_THRESHOLD_C) * duration_scale)
    return 1.0 - derate


# --- Physics ------------------------------------------------------------------


def power_at_speed(v: float, grade: float, mass_kg: float, rho: float, cda: float) -> float:
    theta = math.atan(grade)
    aero = 0.5 * rho * cda * v**3
    rolling = mass_kg * _G * _CRR * math.cos(theta) * v
    gravity = mass_kg * _G * math.sin(theta) * v
    return (aero + rolling + gravity) / _DRIVETRAIN_EFF


def speed_at_power(power_w: float, grade: float, mass_kg: float, rho: float, cda: float) -> float:
    """Bisection solve of the cubic — monotonic in v, so this always converges."""
    lo, hi = 0.1, 30.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if power_at_speed(mid, grade, mass_kg, rho, cda) < power_w:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# --- Conditions resolution ------------------------------------------------------


def climatological_conditions(lat: float, lon: float, event_date: str) -> Optional[dict[str, Any]]:
    """Best-effort normals: same calendar date averaged over the last 3 years
    (Open-Meteo ERA5 archive, no key needed). Returns None on any failure —
    the caller falls back to defaults and *records that it did*."""
    import httpx

    try:
        year, rest = event_date[:4], event_date[4:]
        years = [int(year) - i for i in (1, 2, 3)]
        temps, hums = [], []
        for y in years:
            date = f"{y}{rest}"
            resp = httpx.get(
                "https://archive-api.open-meteo.com/v1/archive",
                params={
                    "latitude": lat, "longitude": lon,
                    "start_date": date, "end_date": date,
                    "daily": "temperature_2m_mean,relative_humidity_2m_mean",
                    "timezone": "auto",
                },
                timeout=10,
            )
            if resp.status_code != 200:
                continue
            daily = resp.json().get("daily", {})
            t = (daily.get("temperature_2m_mean") or [None])[0]
            h = (daily.get("relative_humidity_2m_mean") or [None])[0]
            if t is not None:
                temps.append(t)
            if h is not None:
                hums.append(h)
        if not temps:
            return None
        return {
            "temp_c": round(sum(temps) / len(temps), 1),
            "humidity_pct": round(sum(hums) / len(hums), 1) if hums else 50.0,
            "source": f"climatological normal ({len(temps)}-year average, Open-Meteo ERA5)",
        }
    except Exception:
        return None


# --- The demand profile ---------------------------------------------------------


def build_demand_profile(
    route_points: list[dict[str, float]],
    event_date: str,
    rider_mass_kg: float,
    bike_kit_kg: float,
    conditions: Optional[dict[str, Any]],
    model_values: dict[str, float],
    cda: Optional[float] = None,
    position: str = "relaxed",
) -> dict[str, Any]:
    grid = clean_elevation(route_points)
    segments = segment_route(grid)

    if conditions is None:
        mid = route_points[len(route_points) // 2]
        conditions = climatological_conditions(mid["lat"], mid["lon"], event_date) or {
            "temp_c": 20.0,
            "humidity_pct": 50.0,
            "source": "default (20°C/50% — climatology fetch unavailable); override with a forecast",
        }

    total_mass = rider_mass_kg + bike_kit_kg
    cda = cda or _CDA_BY_POSITION.get(position, 0.35)
    cp = model_values.get("cp_watts") or 200.0
    w_prime = model_values.get("w_prime_j") or 20000.0

    mean_ele = sum(grid["elevation_m"]) / len(grid["elevation_m"])
    max_ele = max(grid["elevation_m"])
    alt_fraction_mean = altitude_power_fraction(mean_ele)

    # First pass with a rough duration to seed the heat term, then refine once.
    est_hours = grid["total_m"] / 1000 / 30
    for _ in range(2):
        heat_fraction = heat_power_fraction(conditions["temp_c"], conditions["humidity_pct"], est_hours)
        cp_derated = cp * alt_fraction_mean * heat_fraction

        walk = _walk_route(segments, total_mass, cda, cp_derated, conditions)
        est_hours = walk["total_sec"] / 3600

    climbs = [s for s in walk["segments"] if s["kind"] == "climb"]
    surges = [s for s in walk["segments"] if s["kind"] == "surge"]

    # Decisive selections: the climbs that hurt most (duration x intensity),
    # plus surge clusters with short recovery.
    decisive = sorted(climbs, key=lambda s: s["duration_sec"] * s["required_watts"], reverse=True)[:5]
    surge_cluster = _cluster_surges(surges)

    profile = {
        "conditions": conditions,
        "derates": {
            "altitude_power_fraction": round(alt_fraction_mean, 3),
            "heat_power_fraction": round(heat_fraction, 3),
            "cp_sea_level_fresh_w": round(cp, 1),
            "cp_on_the_day_w": round(cp_derated, 1),
            "air_density_kgm3": round(walk["rho"], 4),
            "air_density_sea_level_note": (
                "Lower density at altitude cuts aero drag (flats/descents easier) even as the O₂ derate "
                "shrinks the engine (climbs harder) — both are modeled, in opposite directions."
            ),
            "wind": "not modeled — no reliable per-segment wind data; assumption stated rather than guessed",
        },
        "course": {
            "total_km": round(grid["total_m"] / 1000, 1),
            "total_gain_m": round(sum(max(0.0, s["gain_m"]) for s in segments)),
            "mean_elevation_m": round(mean_ele),
            "max_elevation_m": round(max_ele),
            "estimated_duration_hours": round(est_hours, 2),
            "elevation_cleaning": grid["report"],
        },
        "segments": walk["segments"],
        "demands": _demands(decisive, surge_cluster, walk, cp_derated, w_prime),
        "computed_at": time.time(),
    }
    return profile


def _walk_route(
    segments: list[dict[str, Any]], mass: float, cda: float, cp_derated: float, conditions: dict[str, Any]
) -> dict[str, Any]:
    out = []
    elapsed = 0.0
    kj = 0.0
    rho_cache: dict[int, float] = {}

    for seg in segments:
        mid_ele = (seg["start_ele_m"] + seg["end_ele_m"]) / 2
        rho_key = int(mid_ele / 50)
        if rho_key not in rho_cache:
            rho_cache[rho_key] = air_density(mid_ele, conditions["temp_c"], conditions["humidity_pct"])
        rho = rho_cache[rho_key]

        # CP is derated at the route's mean elevation; a true per-segment
        # derate (summit finishes bite harder than the mean says) is noted as
        # a refinement, not silently half-done.
        local_cp = cp_derated

        if seg["kind"] in ("climb", "roller"):
            power = local_cp * _CLIMB_CP_FRACTION
        elif seg["kind"] == "surge":
            power = local_cp * _CLIMB_CP_FRACTION  # replaced by surge physics below
        elif seg["kind"] == "descent":
            power = local_cp * _DESCENT_CP_FRACTION
        else:
            power = local_cp * _FLAT_CP_FRACTION

        v = min(speed_at_power(power, seg["avg_grade"], mass, rho, cda), _MAX_DESCENT_SPEED)
        duration = seg["length_m"] / v if v > 0 else 0.0

        entry = {**seg, "required_watts": round(power), "speed_kmh": round(v * 3.6, 1),
                 "duration_sec": round(duration), "kj_before": round(kj), "elapsed_before_sec": round(elapsed)}

        if seg["kind"] == "surge":
            # The surge demand is holding the *approach* speed over the pitch —
            # that's what staying with a group through a punch costs.
            approach_v = out[-1]["speed_kmh"] / 3.6 if out else v
            p_surge = power_at_speed(max(approach_v, v), seg["avg_grade"], mass, rho, cda)
            t_surge = seg["length_m"] / max(approach_v, v)
            entry["required_watts"] = round(p_surge)
            entry["duration_sec"] = round(t_surge)
            entry["w_prime_cost_j"] = round(max(0.0, (p_surge - cp_derated) * t_surge))
            duration = t_surge
            power = p_surge

        elapsed += duration
        kj += power * duration / 1000
        out.append(entry)

    return {"segments": out, "total_sec": elapsed, "total_kj": kj, "rho": sum(rho_cache.values()) / len(rho_cache)}


def _cluster_surges(surges: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    clusters: list[list[dict[str, Any]]] = []
    for s in surges:
        if clusters and s["elapsed_before_sec"] - (
            clusters[-1][-1]["elapsed_before_sec"] + clusters[-1][-1]["duration_sec"]
        ) <= _SURGE_RECOVERY_WINDOW_SEC:
            clusters[-1].append(s)
        else:
            clusters.append([s])
    return clusters


def _demands(decisive, surge_clusters, walk, cp_derated: float, w_prime: float) -> list[dict[str, Any]]:
    demands = []
    for c in decisive:
        demands.append({
            "type": "sustained_climb",
            "description": (
                f"{c['length_m'] / 1000:.1f}km at {c['avg_grade'] * 100:.1f}% — "
                f"~{c['required_watts']}W for {c['duration_sec'] // 60}min, "
                f"arriving with {c['kj_before']} kJ already spent"
            ),
            "required_watts": c["required_watts"],
            "duration_sec": c["duration_sec"],
            "kj_before": c["kj_before"],
            "start_m": c["start_m"],
        })

    biggest = max(surge_clusters, key=len, default=None)
    if biggest and len(biggest) >= 2:
        worst = max(biggest, key=lambda s: s.get("w_prime_cost_j", 0))
        demands.append({
            "type": "repeated_surges",
            "description": (
                f"{len(biggest)} punches inside {_SURGE_RECOVERY_WINDOW_SEC // 60}min-recovery windows, "
                f"worst ~{worst['required_watts']}W for {worst['duration_sec']}s "
                f"(~{worst.get('w_prime_cost_j', 0) / 1000:.1f} kJ of W′ each)"
            ),
            "count": len(biggest),
            "worst_watts": worst["required_watts"],
            "w_prime_cost_j": worst.get("w_prime_cost_j", 0),
            "kj_before": biggest[0]["kj_before"],
        })

    if decisive:
        final = max(decisive, key=lambda c: c["kj_before"])
        demands.append({
            "type": "durability",
            "description": (
                f"The last decisive selection comes after {final['kj_before']} kJ — "
                f"you need ~{round(100 * final['required_watts'] / cp_derated)}% of your day-derated CP still available there"
            ),
            "kj_at_selection": final["kj_before"],
            "fraction_of_cp_needed": round(final["required_watts"] / cp_derated, 3),
        })
    return demands


def gap_report(profile: dict[str, Any], model: dict[str, Any]) -> list[dict[str, Any]]:
    """Per demand: where the athlete currently falls short, in that day's
    conditions, with the model's own confidence attached — a gap measured by a
    low-confidence parameter is a hypothesis, not a verdict."""
    params = model["params"]
    values = {k: p["value"] for k, p in params.items()}
    cp_day = profile["derates"]["cp_on_the_day_w"]
    gaps = []

    for d in profile["demands"]:
        if d["type"] == "sustained_climb":
            required, have = d["required_watts"], cp_day
            status = "ok" if have >= required else ("stretch" if have >= 0.93 * required else "gap")
            gaps.append({
                "demand": d["description"], "status": status,
                "detail": f"Needs ~{required}W sustained; your condition-derated CP is {cp_day}W "
                          f"(sea-level fresh: {profile['derates']['cp_sea_level_fresh_w']}W).",
                "confidence": params["cp_watts"]["confidence"],
            })
        elif d["type"] == "repeated_surges":
            w_prime = values.get("w_prime_j") or 0
            effective = w_prime * (values.get("repeatability") or 0.85)
            supported = int(effective // d["w_prime_cost_j"]) if d["w_prime_cost_j"] else 99
            status = "ok" if supported >= d["count"] else ("stretch" if supported >= d["count"] - 1 else "gap")
            gaps.append({
                "demand": d["description"], "status": status,
                "detail": f"Each punch costs ~{d['w_prime_cost_j'] / 1000:.1f} kJ of W′; your W′ ({w_prime / 1000:.1f} kJ) "
                          f"x measured repeatability ({values.get('repeatability')}) supports ~{supported} "
                          f"consecutive at that recovery — the course asks {d['count']}.",
                "confidence": params["repeatability"]["confidence"],
            })
        elif d["type"] == "durability":
            have = values.get("durability") or 1.0
            need = d["fraction_of_cp_needed"]
            status = "ok" if have >= need else ("stretch" if have >= need - 0.05 else "gap")
            gaps.append({
                "demand": d["description"], "status": status,
                "detail": f"Needs {need:.0%} of day-CP after {d['kj_at_selection']} kJ; your measured decay "
                          f"({params['durability']['source']}) holds {have:.0%}. "
                          + ("Measured shallower than the race asks — treat as provisional. " if params["durability"]["confidence"] == "low" else ""),
                "confidence": params["durability"]["confidence"],
            })
    return gaps


# --- Event orchestration (store, recompute, diff) --------------------------------


def _route_hash(points: list[dict[str, float]]) -> str:
    payload = ",".join(f"{p['lat']:.5f}:{p['lon']:.5f}:{p['ele_m']:.1f}" for p in points[::10])
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def recompute_event(event: dict[str, Any]) -> dict[str, Any]:
    """(Re)build the demand profile for an event; returns profile + a diff vs
    the previous computation when inputs changed."""
    from services import physiology_model

    route = local_store.get_event_route(event["id"])
    if not route:
        raise ValueError("Event has no stored route.")

    model = local_store.get_physiology_model() or physiology_model.compute()
    conditions = event.get("conditions_override")

    profile = build_demand_profile(
        route_points=route,
        event_date=event["date"],
        rider_mass_kg=event["rider_mass_kg"],
        bike_kit_kg=event.get("bike_kit_kg", _DEFAULT_BIKE_KIT_KG),
        conditions=conditions,
        model_values={k: p["value"] for k, p in model["params"].items()},
        cda=event.get("cda"),
        position=(local_store._load().get("aero_profile") or {}).get("position", "relaxed"),
    )
    profile["gap_report"] = gap_report(profile, model)
    profile["inputs_snapshot"] = {
        "route_hash": _route_hash(route),
        "route_points": len(route),
        "event_date": event["date"],
        "rider_mass_kg": event["rider_mass_kg"],
        "bike_kit_kg": event.get("bike_kit_kg", _DEFAULT_BIKE_KIT_KG),
        "conditions_used": profile["conditions"],
        "model_computed_at": model.get("computed_at"),
        "model_values": {k: p["value"] for k, p in model["params"].items()},
    }

    previous = local_store.get_demand_profile(event["id"])
    profile["diff_vs_previous"] = _profile_diff(previous, profile) if previous else None
    local_store.save_demand_profile(event["id"], profile)
    return profile


def _profile_diff(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    changes = []
    o_snap, n_snap = old.get("inputs_snapshot", {}), new.get("inputs_snapshot", {})
    for key in ("route_hash", "rider_mass_kg", "bike_kit_kg", "conditions_used", "model_values"):
        if o_snap.get(key) != n_snap.get(key):
            changes.append(f"input changed: {key}")
    for field, label in [
        (("derates", "cp_on_the_day_w"), "day-derated CP"),
        (("course", "estimated_duration_hours"), "estimated duration (h)"),
    ]:
        ov = old.get(field[0], {}).get(field[1])
        nv = new.get(field[0], {}).get(field[1])
        if ov != nv:
            changes.append(f"{label}: {ov} → {nv}")
    o_gaps = {g["demand"]: g["status"] for g in old.get("gap_report", [])}
    for g in new.get("gap_report", []):
        prev = o_gaps.get(g["demand"])
        if prev and prev != g["status"]:
            changes.append(f"gap '{g['demand'][:50]}...': {prev} → {g['status']}")
    return changes or ["inputs unchanged — recompute produced identical demands"]
