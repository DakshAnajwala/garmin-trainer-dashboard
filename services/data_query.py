"""Ask-your-own-data: free-text questions over the athlete's own history.

"20-min power at 3000 kJ vs last spring" → parsed intent → metric + filter +
time window resolved against real rides → one sentence + a minimal chart.
No manual chart-building, no LLM: the parser is deterministic (regex over a
small metric/window vocabulary), so the same question always means the same
thing, it works with the app's Anthropic key broken, and nothing about your
training leaves the machine. The trade-off is a bounded vocabulary — unknown
phrasing gets a "here's what I can answer" reply instead of a guess.

Answers honour power exclusions (a ride whose meter you've excluded can't win
a "best power" question) and carry the resolved interpretation back to the UI,
so a misparse is visible instead of silently answering a different question.

Cached per normalized query; the cache is fingerprinted against the data it
was computed from and recomputes when rides/weights/FTP history change.
"""
from __future__ import annotations

import re
from datetime import date as date_, timedelta
from typing import Any, Optional

from database import local_store
from services import power_curve

_SEASONS = {
    "spring": (3, 5),
    "summer": (6, 8),
    "autumn": (9, 11),
    "fall": (9, 11),
    "winter": (12, 2),
}
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june",
     "july", "august", "september", "october", "november", "december"]
)}


def _parse_window(text: str, today: date_) -> tuple[Optional[str], Optional[str], str]:
    """→ (start_iso, end_iso, label). None start = all-time."""
    text = text.strip().lower()

    m = re.search(r"last\s+(\d+)\s+(day|week|month)s?", text)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        days = n * {"day": 1, "week": 7, "month": 30}[unit]
        return (today - timedelta(days=days)).isoformat(), today.isoformat(), f"last {n} {unit}s"

    for season, (m0, m1) in _SEASONS.items():
        if f"last {season}" in text or (f"this {season}" in text):
            year = today.year
            if m0 <= today.month <= (m1 if m1 >= m0 else 12):
                # currently inside that season: "last" means the previous one
                year -= 1 if f"last {season}" in text else 0
            elif today.month < m0:
                year -= 1
            if season == "winter":
                return f"{year - 1}-12-01", f"{year}-02-28", f"{season} {year - 1}/{year}"
            return f"{year}-{m0:02d}-01", f"{year}-{m1:02d}-30", f"{season} {year}"

    if "this year" in text:
        return f"{today.year}-01-01", today.isoformat(), f"{today.year} so far"
    if "last year" in text:
        return f"{today.year - 1}-01-01", f"{today.year - 1}-12-31", str(today.year - 1)

    m = re.search(r"since\s+(\w+)", text)
    if m and m.group(1) in _MONTHS:
        mo = _MONTHS[m.group(1)]
        year = today.year if mo <= today.month else today.year - 1
        return f"{year}-{mo:02d}-01", today.isoformat(), f"since {m.group(1).title()}"

    m = re.search(r"in\s+(\w+)", text)
    if m and m.group(1) in _MONTHS:
        mo = _MONTHS[m.group(1)]
        year = today.year if mo <= today.month else today.year - 1
        end_day = 28 if mo == 2 else 30
        return f"{year}-{mo:02d}-01", f"{year}-{mo:02d}-{end_day}", f"{m.group(1).title()} {year}"

    return None, None, "all tracked history"


def parse(query: str, today: Optional[date_] = None) -> Optional[dict[str, Any]]:
    """Free text → intent. None when the vocabulary doesn't cover it."""
    today = today or date_.today()
    q = query.strip().lower()

    comparison = None
    main = q
    m = re.split(r"\bvs\.?\b|\bversus\b|\bcompared to\b", q, maxsplit=1)
    if len(m) == 2:
        main, comparison = m[0], m[1]

    intent: dict[str, Any] = {}

    dur = re.search(r"(\d+)\s*[- ]?\s*(s\b|sec|second|min|minute|hour|h\b)", main)
    if dur and ("power" in main or "watt" in main or re.search(r"\d+\s*min\b", main)):
        n = int(dur.group(1))
        unit = dur.group(2)
        seconds = n if unit.startswith("s") else n * 60 if unit.startswith(("m",)) else n * 3600
        intent["metric"] = "power"
        intent["duration_s"] = seconds
    elif "ftp" in main:
        intent["metric"] = "ftp"
    elif "weight" in main:
        intent["metric"] = "weight"
    elif "hrv" in main:
        intent["metric"] = "hrv"
    elif "resting" in main and "hr" in main or "rhr" in main:
        intent["metric"] = "rhr"
    elif "readiness" in main:
        intent["metric"] = "readiness"
    elif "distance" in main or re.search(r"\bkm\b", main):
        intent["metric"] = "distance"
    else:
        return None

    kj = re.search(r"(?:at|after)\s+(\d+)\s*kj", main)
    if kj:
        intent["after_kj"] = int(kj.group(1))

    start, end, label = _parse_window(main, today)
    intent["window"] = {"start": start, "end": end, "label": label}
    if comparison is not None:
        c_start, c_end, c_label = _parse_window(comparison, today)
        intent["compare_window"] = {"start": c_start, "end": c_end, "label": c_label}

    return intent


def _rides_in(window: dict[str, Any]) -> list[dict[str, Any]]:
    rides = power_curve.cached_rides()
    if window.get("start"):
        rides = [r for r in rides if r.get("date") and window["start"] <= r["date"] <= window["end"]]
    return rides


def _best_power(rides, duration_s: int, after_kj: Optional[int]) -> tuple[Optional[float], Optional[dict]]:
    exclusions = local_store.get_power_exclusions()
    best, best_ride = None, None
    for r in rides:
        rule = exclusions.get(str(r["activity_id"])) or {}
        if rule.get("excluded"):
            continue
        series = power_curve._dense_power_series(r["samples"], rule.get("ranges"))
        n = len(series)
        if n < duration_s:
            continue
        start_idx = 0
        if after_kj:
            prefix = 0.0
            start_idx = None
            for i, v in enumerate(series):
                prefix += (v or 0.0)
                if prefix / 1000 >= after_kj:
                    start_idx = i
                    break
            if start_idx is None or start_idx >= n - duration_s:
                continue
            series = series[start_idx:]
        watts = power_curve._best_mean_for_duration(series, duration_s)
        if watts and (best is None or watts > best):
            best, best_ride = watts, r
    return best, best_ride


def _series_metric(metric: str, window: dict[str, Any]) -> list[tuple[str, float]]:
    if metric == "weight":
        pts = local_store.get_weight_history(limit_days=3650)
    elif metric == "ftp":
        pts = [(t["date"], t["ftp_w"]) for t in local_store.get_ftp_history()]
    elif metric == "hrv":
        pts = [(d, (v or {}).get("last_night_avg_ms")) for d, v in sorted(local_store.get_all_metric_days("hrv").items())]
    elif metric == "rhr":
        pts = [(d, ((v or {}).get("resting_heart_rate") or {}).get("resting_hr_bpm"))
               for d, v in sorted(local_store.get_all_snapshots().items())]
    elif metric == "readiness":
        pts = [(d, (v or {}).get("readiness_score")) for d, v in sorted(local_store.get_all_metric_days("readiness").items())]
    else:
        pts = []
    pts = [(d, v) for d, v in pts if v is not None]
    if window.get("start"):
        pts = [(d, v) for d, v in pts if window["start"] <= d <= window["end"]]
    return pts


_UNITS = {"power": "W", "ftp": "W", "weight": "kg", "hrv": "ms", "rhr": "bpm", "readiness": "", "distance": "km"}


def _resolve(intent: dict[str, Any], window_key: str) -> dict[str, Any]:
    window = intent[window_key]
    metric = intent["metric"]

    if metric == "power":
        rides = _rides_in(window)
        best, ride = _best_power(rides, intent["duration_s"], intent.get("after_kj"))
        chart = []
        for r in rides:
            v, _ = _best_power([r], intent["duration_s"], intent.get("after_kj"))
            if v:
                chart.append((r["date"], round(v, 1)))
        return {"value": round(best, 1) if best else None, "detail": ride and f"ride {ride['activity_id']} on {ride['date']}",
                "chart": sorted(chart), "n": len(rides)}

    if metric == "distance":
        # From the activity-list caches (distance is a summary field). Every
        # cached day holds a snapshot of the SAME recent activities, so
        # deduplicate by activity_id or each ride counts once per cache day.
        by_activity: dict[str, tuple[str, float]] = {}
        for m in ("activities_list_large", "activities_list"):
            for _d, payload in local_store.get_all_metric_days(m).items():
                for a in (payload or {}).get("items", []):
                    d = str(a.get("start_time_local", ""))[:10]
                    if window.get("start") and not (window["start"] <= d <= window["end"]):
                        continue
                    km = (a.get("distance_m") or 0) / 1000
                    if km:
                        by_activity[str(a.get("activity_id"))] = (d, km)
        per_day: dict[str, float] = {}
        for d, km in by_activity.values():
            per_day[d] = per_day.get(d, 0) + km
        total = sum(per_day.values())
        chart = sorted((d, round(km, 1)) for d, km in per_day.items())
        return {"value": round(total, 1), "detail": f"{len(by_activity)} ride(s) across {len(per_day)} day(s)",
                "chart": chart, "n": len(by_activity)}

    pts = _series_metric(metric, window)
    if not pts:
        return {"value": None, "detail": None, "chart": [], "n": 0}
    if metric == "ftp":
        value, detail = pts[-1][1], f"latest test {pts[-1][0]}"
    else:
        value, detail = round(sum(v for _, v in pts) / len(pts), 1), f"average of {len(pts)} days"
    return {"value": value, "detail": detail, "chart": pts, "n": len(pts)}


def _fingerprint() -> str:
    return f"{len(power_curve.cached_rides())}:{len(local_store.get_ftp_history())}:{local_store.get_latest_weight()}"


def answer(query: str, today: Optional[date_] = None) -> dict[str, Any]:
    normalized = " ".join(query.lower().split())
    cached = local_store.get_cached_query(normalized)
    if cached and cached.get("fingerprint") == _fingerprint():
        return {**cached, "cached": True}

    intent = parse(query, today)
    if intent is None:
        return {
            "answer": (
                "I couldn't map that to a metric I know. Try things like: '20 min power', "
                "'5 min power at 500 kJ vs last spring', 'weight this year', 'FTP', 'HRV last 30 days', "
                "'distance in june'."
            ),
            "chart": [], "resolved": None, "cached": False,
        }

    main = _resolve(intent, "window")
    metric, unit = intent["metric"], _UNITS.get(intent["metric"], "")
    label = intent["window"]["label"]
    name = f"{intent['duration_s'] // 60}min power" if metric == "power" and intent.get("duration_s", 0) >= 60 else (
        f"{intent.get('duration_s')}s power" if metric == "power" else metric.upper() if metric in ("ftp", "hrv") else metric
    )
    if intent.get("after_kj"):
        name += f" after {intent['after_kj']} kJ"

    if main["value"] is None:
        sentence = f"No data for {name} in {label}"
        if intent.get("after_kj"):
            sentence += f" — no ride reaches {intent['after_kj']} kJ with a full effort window after it"
        sentence += f" ({main['n']} candidate rides/days)."
    else:
        agg = "Best" if metric in ("power", "distance") else ("Latest" if metric == "ftp" else "Average")
        agg = "Total" if metric == "distance" else agg
        sentence = f"{agg} {name} in {label}: {main['value']}{unit}" + (f" ({main['detail']})" if main["detail"] else "") + "."

    result: dict[str, Any] = {
        "answer": sentence,
        "chart": {"title": name, "unit": unit, "points": main["chart"]},
        "resolved": intent,
        "cached": False,
        "fingerprint": _fingerprint(),
    }

    if intent.get("compare_window"):
        other = _resolve(intent, "compare_window")
        c_label = intent["compare_window"]["label"]
        if other["value"] is None:
            result["answer"] += f" No data for {c_label} to compare against."
        elif main["value"] is not None:
            delta = main["value"] - other["value"]
            pct = 100 * delta / other["value"] if other["value"] else 0
            result["answer"] += (
                f" {c_label.capitalize()}: {other['value']}{unit} → {delta:+.1f}{unit} ({pct:+.1f}%)."
            )
            result["compare_chart"] = {"title": f"{name} — {c_label}", "unit": unit, "points": other["chart"]}

    local_store.cache_query(normalized, result)
    return result
