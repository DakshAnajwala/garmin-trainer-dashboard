"""Mean-max power curve computed from the athlete's actual ride samples.

This is the aggregation layer the Coggan curve and FTP estimation were missing.
Until now `POWER_CURVE_SECONDS` (config/athlete_profile.json) was hand-entered
self-reported bests, so no ride could influence the curve — and equally, no bad
ride could corrupt it. Now that rides feed the curve, a miscalibrated power
meter genuinely can poison it, which is exactly why exclusion exists.

Two honest limitations, both surfaced rather than hidden:

- **Garmin's detail endpoint is downsampled, not 1Hz.** Real rides here come
  back at ~3s intervals (verified: 1350 of 1401 gaps on a real indoor ride were
  exactly 3s). You cannot measure a true 1s or 5s max from 3s-averaged samples,
  so every duration carries a `reliable` flag based on the ride's own measured
  sample interval. Short durations are computed but marked unreliable rather
  than silently presented as if they were sprint-accurate.
- **"All-time" means since this app started caching ride details**, same caveat
  as services/personal_records.py — not true Garmin lifetime history.

Exclusion is applied *here*, at aggregation time, by masking excluded seconds
out of the series. Raw samples are never modified or deleted, so re-including a
ride restores the previous curve exactly.
"""
from __future__ import annotations

import statistics
from typing import Any, Optional

from config.athlete_profile import POWER_CURVE_SECONDS
from database import local_store

#: Durations a power-duration curve is conventionally reported at.
STANDARD_DURATIONS = [1, 5, 15, 30, 60, 120, 300, 600, 1200, 1800, 3600]

#: Never hold a sample's value across a gap longer than this — a long gap is a
#: pause or a dropout, and carrying power across it would fabricate effort that
#: didn't happen. (A real ride in the cache has a 791s pause mid-file.)
#: Beyond this the series is zero-filled, not held: see _dense_power_series.
_MAX_HOLD_SEC = 10

#: A duration shorter than this multiple of the ride's own sample interval
#: can't be honestly resolved from that ride's data.
_RELIABLE_INTERVAL_MULTIPLE = 3


def sample_interval_sec(samples: list[dict[str, Any]]) -> Optional[float]:
    """Median seconds between consecutive samples — the ride's real resolution,
    which is a property of how Garmin returned it, not something we control."""
    times = [s.get("elapsed_sec") for s in samples if s.get("elapsed_sec") is not None]
    if len(times) < 2:
        return None
    deltas = [b - a for a, b in zip(times, times[1:]) if b > a]
    return statistics.median(deltas) if deltas else None


def _dense_power_series(
    samples: list[dict[str, Any]], excluded_ranges: Optional[list[dict[str, Any]]] = None
) -> list[Optional[float]]:
    """Expand irregularly-spaced samples into a per-second series.

    Each sample's power is held forward until the next sample, but only across
    gaps up to _MAX_HOLD_SEC. A longer gap is a pause or a dead sensor, and is
    **zero-filled**: not pedalling really is zero watts, so this is a physical
    fact rather than fabricated data. It also fails safe — zeros can only drag
    an average down, so a gap can never inflate a best or an FTP estimate. The
    strict alternative (marking gaps invalid) was rejected after testing on a
    real ride: its longest gap-free run was 998s, so a single mid-ride pause
    silently made every 20min window unmeasurable, which reads as "no data"
    when the truth is "you stopped pedalling for a bit".

    Two states are deliberately distinct:
      - zero  -> known: no power was being produced (counts toward averages)
      - None  -> excluded: must not feed aggregates at all, so any window
                 overlapping it is skipped entirely rather than diluted with
                 invented zeros.

    Exclusion masking touches only this derived series, never stored samples.
    """
    points = [
        (s["elapsed_sec"], s.get("power_w"))
        for s in samples
        if s.get("elapsed_sec") is not None
    ]
    if not points:
        return []
    points.sort(key=lambda p: p[0])

    end_sec = points[-1][0]
    series: list[Optional[float]] = [0.0] * (int(end_sec) + 1)

    for (t, power), (next_t, _) in zip(points, points[1:] + [(end_sec + 1, None)]):
        if power is None:
            continue
        hold_until = min(int(next_t), int(t) + _MAX_HOLD_SEC)
        for sec in range(int(t), max(int(t) + 1, hold_until)):
            if 0 <= sec < len(series):
                series[sec] = float(power)

    for r in excluded_ranges or []:
        start = max(0, int(r.get("start_sec", 0)))
        stop = min(len(series), int(r.get("end_sec", 0)) + 1)
        for sec in range(start, stop):
            series[sec] = None

    return series


def _best_mean_for_duration(series: list[Optional[float]], duration: int) -> Optional[float]:
    """Max rolling average over any fully-valid window of `duration` seconds.

    A window containing any invalid second is skipped entirely rather than
    treated as zero (which would understate) or interpolated (which would
    invent data). O(n) via a prefix sum plus the last-invalid index.
    """
    n = len(series)
    if duration <= 0 or n < duration:
        return None

    prefix = [0.0] * (n + 1)
    for i, v in enumerate(series):
        prefix[i + 1] = prefix[i] + (v or 0.0)

    best: Optional[float] = None
    last_invalid = -1
    for i, v in enumerate(series):
        if v is None:
            last_invalid = i
        start = i - duration + 1
        if start < 0 or last_invalid >= start:
            continue
        mean = (prefix[i + 1] - prefix[start]) / duration
        if best is None or mean > best:
            best = mean
    return best


def ride_curve(
    samples: list[dict[str, Any]],
    excluded_ranges: Optional[list[dict[str, Any]]] = None,
    durations: Optional[list[int]] = None,
) -> dict[int, dict[str, Any]]:
    """Mean-max power per duration for a single ride, after exclusions."""
    interval = sample_interval_sec(samples)
    series = _dense_power_series(samples, excluded_ranges)
    if not series:
        return {}

    out: dict[int, dict[str, Any]] = {}
    for d in durations or STANDARD_DURATIONS:
        watts = _best_mean_for_duration(series, d)
        if watts is None:
            continue
        out[d] = {
            "watts": round(watts, 1),
            "reliable": interval is None or d >= interval * _RELIABLE_INTERVAL_MULTIPLE,
            "sample_interval_sec": interval,
        }
    return out


def all_time_curve(
    rides: list[dict[str, Any]],
    exclusions: Optional[dict[str, Any]] = None,
    durations: Optional[list[int]] = None,
) -> dict[int, dict[str, Any]]:
    """Best mean-max across every ride, with the ride that set each best.

    `rides` is [{activity_id, date, samples}]. `exclusions` maps activity_id ->
    {excluded: bool, reason: str, ranges: [{start_sec, end_sec}]}.

    Semantics, deliberately unambiguous: `excluded` is the whole-ride switch and
    wins outright — the ride contributes nothing. Otherwise `ranges` are masked
    out and the rest of the ride still counts. Ranges are kept (not cleared)
    while a ride is whole-excluded, so re-including restores the segment-level
    state the athlete had set rather than silently discarding it.

    Because this recomputes from raw samples every call, toggling an exclusion
    can never leave a stale best behind — there is no cached bests array to go
    out of sync. Excluding the ride that set a best simply lets the next-best
    remaining ride win.
    """
    exclusions = exclusions or {}
    best: dict[int, dict[str, Any]] = {}

    for ride in rides:
        aid = str(ride.get("activity_id"))
        rule = exclusions.get(aid) or {}
        if rule.get("excluded"):
            continue

        curve = ride_curve(ride.get("samples") or [], rule.get("ranges") or [], durations)
        for d, point in curve.items():
            if d not in best or point["watts"] > best[d]["watts"]:
                best[d] = {
                    **point,
                    "activity_id": ride.get("activity_id"),
                    "date": ride.get("date"),
                }
    return best


def _activity_dates() -> dict[str, str]:
    """activity_id -> YYYY-MM-DD, read from whichever activity-list cache holds
    the ride. Sample data itself carries no date, only elapsed seconds."""
    dates: dict[str, str] = {}
    for metric in ("activities_list", "activities_list_large"):
        for _day, payload in local_store.get_all_metric_days(metric).items():
            for item in (payload or {}).get("items", []):
                aid, start = item.get("activity_id"), item.get("start_time_local")
                if aid and start:
                    dates[str(aid)] = str(start)[:10]
    return dates


def cached_rides() -> list[dict[str, Any]]:
    """Rides available to the measured curve.

    Only rides whose sample detail has been cached count — details are fetched
    lazily when a ride is opened, so a ride you've never clicked into cannot
    contribute a best. That's a real coverage limit, reported as `rides_analyzed`
    rather than presented as if it were your whole history.
    """
    dates = _activity_dates()
    return [
        {"activity_id": aid, "date": dates.get(str(aid)), "samples": samples}
        for aid, samples in local_store.get_all_activity_details().items()
        if samples
    ]


def measured_all_time(durations: Optional[list[int]] = None) -> dict[int, dict[str, Any]]:
    """All-time measured mean-max, honouring current exclusions.

    Recomputed from raw samples on every call, which is what makes exclusion
    toggling correct by construction: there is no cached bests array that could
    survive a toggle and keep a spike alive in the historical curve.
    """
    return all_time_curve(cached_rides(), local_store.get_power_exclusions(), durations)


def _enforce_monotonic(curve: dict[int, dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Repair the one way merging two sources can produce an impossible curve.

    A power-duration curve must be non-increasing: averaging X watts for 60min
    mathematically guarantees averaging at least X for some 30min window inside
    it, so best(30min) >= best(60min) always. Max-merging two curves preserves
    that — but only where both define the same durations. The config curve has
    no 1800s entry, so a real merge produced 1800s=182.4W (measured) alongside
    3600s=193W (self-reported): a curve that rises with duration, which is not
    physically possible and would corrupt both the Coggan comparison and the
    rider phenotype classification.

    Lifting the shorter duration to the longer one's value is a logical
    implication of data already claimed, not invented data — but it is still an
    inference, so it's tagged `implied_from_s` and never silently attributed to
    a ride that didn't measure it.
    """
    out = dict(curve)
    carried: Optional[tuple[int, dict[str, Any]]] = None
    for d in sorted(out, reverse=True):
        if carried is not None and out[d]["watts"] < carried[1]["watts"]:
            source_d, source = carried
            out[d] = {
                "watts": source["watts"],
                "source": source["source"],
                "reliable": source.get("reliable", True),
                "implied_from_s": source_d,
            }
        else:
            carried = (d, out[d])
    return out


def merged_curve(durations: Optional[list[int]] = None) -> dict[int, dict[str, Any]]:
    """The self-reported config curve merged with what rides actually measured.

    Both sources are kept because each knows something the other doesn't: the
    config curve holds career bests from before this app cached anything, while
    rides measure efforts the config was never updated for. Best-per-duration
    wins, tagged with provenance so the UI can show which is which — and so
    excluding a ride visibly drops its durations back to the self-reported
    value instead of silently vanishing.

    Only `reliable` measured points may set a best: a 1s "max" derived from 3s
    samples isn't a sprint measurement and must not overwrite a real one.
    """
    merged: dict[int, dict[str, Any]] = {
        d: {"watts": float(w), "source": "self_reported", "reliable": True}
        for d, w in POWER_CURVE_SECONDS.items()
    }
    for d, point in measured_all_time(durations).items():
        if not point.get("reliable"):
            continue
        if d not in merged or point["watts"] > merged[d]["watts"]:
            merged[d] = {
                "watts": point["watts"],
                "source": "measured",
                "reliable": True,
                "activity_id": point.get("activity_id"),
                "date": point.get("date"),
            }
    return _enforce_monotonic(merged)


def estimate_ftp(all_time: dict[int, dict[str, Any]], factor: float) -> Optional[dict[str, Any]]:
    """FTP from measured 20min mean-max, using the athlete's own convention
    (FTP = factor x best 20min). Returns None when no ride has a full,
    unexcluded 20min block of power — which is the common case early on, and
    is reported honestly rather than extrapolated from a shorter effort.
    """
    point = all_time.get(1200)
    if not point:
        return None
    return {
        "ftp_watts": round(point["watts"] * factor, 1),
        "source": "measured_20min",
        "power_20min_w": point["watts"],
        "activity_id": point.get("activity_id"),
        "date": point.get("date"),
    }
