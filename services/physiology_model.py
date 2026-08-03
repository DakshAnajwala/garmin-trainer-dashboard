"""Personalized physiology model: CP, W′, durability, repeatability.

Every parameter is a first-class, inspectable object — value, unit, source,
confidence, the reasoning behind it, and the exact input snapshot it was
computed from — because a number you can't interrogate is a number you can't
trust or correct. The athlete can override and lock any parameter (post-illness
CP, say); locked values survive every auto-recompute until unlocked, and the
computed value is kept alongside so unlocking never loses information.

Model choices, stated plainly:

- **CP/W′** use the classic 2-parameter critical-power model, fit as the
  work–time linear form (W(t) = W′ + CP·t) over 2–20 min mean-max points.
  The 20 min anchor prefers the manual FTP test (back-converted through the
  athlete's own FTP = 0.95 × 20 min convention) over the measured 20 min,
  for the reason established in services/ftp.py: the best 20 min inside an
  ordinary ride is submaximal and would bias CP low.
- **Durability** is the fraction of fresh 10 min power still available after
  K kJ of work, measured from real ride series at the largest K (250 kJ
  steps) any ride can actually support. With today's short indoor rides that
  K is small — the parameter says so rather than extrapolating to the
  2000+ kJ race scenario it will eventually measure.
- **Repeatability** is the decay across near-maximal 30 s punches within a
  ride (later punches ÷ first). One punch = nothing to compare = low
  confidence, reported as exactly that.

Weak data lowers `confidence` and is spelled out in `reasoning`; it never
silently becomes a made-up default presented as measurement.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from database import local_store
from services import power_curve

#: Physiological sanity bounds — used both to clamp custom-algorithm output
#: (services/custom_model.py) and to validate manual overrides.
PARAM_BOUNDS: dict[str, tuple[float, float]] = {
    "cp_watts": (50.0, 600.0),
    "w_prime_j": (1_000.0, 50_000.0),
    "durability": (0.5, 1.0),
    "repeatability": (0.3, 1.0),
}

_FIT_DURATIONS = [120, 300, 600, 1200]  # 2–20 min: the 2-param model's valid range
_PUNCH_WINDOW_SEC = 30
_PUNCH_THRESHOLD = 0.85  # of the ride's own best 30 s
_PUNCH_SPACING_SEC = 90
_DURABILITY_WINDOW_SEC = 600
_DURABILITY_KJ_STEP = 250


def _param(value: Optional[float], unit: str, source: str, confidence: str, reasoning: str) -> dict[str, Any]:
    # Callers pass already-rounded values — re-rounding here mangled fractions
    # (0.85 became 0.8 while the reasoning still said 0.85).
    return {
        "value": value,
        "unit": unit,
        "source": source,
        "confidence": confidence,
        "reasoning": reasoning,
    }


def fit_cp_wprime(points: dict[int, float]) -> Optional[tuple[float, float]]:
    """Least-squares fit of W(t) = W′ + CP·t. Returns (cp_watts, w_prime_j).

    Needs ≥2 distinct durations; with exactly 2 it solves exactly. Points are
    (duration_s -> watts) maximal efforts in the 2–20 min range.
    """
    pts = [(t, w * t) for t, w in points.items() if w]
    if len(pts) < 2:
        return None
    n = len(pts)
    mean_t = sum(t for t, _ in pts) / n
    mean_work = sum(work for _, work in pts) / n
    denom = sum((t - mean_t) ** 2 for t, _ in pts)
    if denom == 0:
        return None
    cp = sum((t - mean_t) * (work - mean_work) for t, work in pts) / denom
    w_prime = mean_work - cp * mean_t
    return cp, w_prime


def _fit_points(ftp_watts: Optional[float], ftp_factor: float) -> tuple[dict[int, float], list[str]]:
    merged = power_curve.merged_curve(durations=power_curve.STANDARD_DURATIONS)
    notes = []
    points: dict[int, float] = {}
    for d in _FIT_DURATIONS:
        p = merged.get(d)
        if p:
            points[d] = p["watts"]
    if ftp_watts:
        anchor = ftp_watts / ftp_factor
        if anchor > points.get(1200, 0):
            points[1200] = anchor
            notes.append(
                f"20min point anchored to the manual FTP test ({ftp_watts}W ÷ {ftp_factor} = "
                f"{anchor:.0f}W) — in-ride 20min bests are submaximal and would bias CP low."
            )
    return points, notes


def _measure_durability() -> dict[str, Any]:
    best_fresh = 0.0
    best_at_k: dict[int, float] = {}
    rides_used = 0

    for ride in power_curve.cached_rides():
        series = power_curve._dense_power_series(ride["samples"])
        n = len(series)
        if n < _DURABILITY_WINDOW_SEC * 2:
            continue
        rides_used += 1
        prefix = [0.0] * (n + 1)
        for i, v in enumerate(series):
            prefix[i + 1] = prefix[i] + (v or 0.0)

        def best_window_from(start: int) -> float:
            best = 0.0
            for i in range(start, n - _DURABILITY_WINDOW_SEC):
                best = max(best, (prefix[i + _DURABILITY_WINDOW_SEC] - prefix[i]) / _DURABILITY_WINDOW_SEC)
            return best

        best_fresh = max(best_fresh, best_window_from(0))
        total_kj = prefix[n] / 1000
        k = _DURABILITY_KJ_STEP
        while k + 50 < total_kj:
            # first second at which k kJ of work has been done
            spent_idx = next((i for i in range(n) if prefix[i] / 1000 >= k), None)
            if spent_idx is None or spent_idx >= n - _DURABILITY_WINDOW_SEC:
                break
            best_at_k[k] = max(best_at_k.get(k, 0.0), best_window_from(spent_idx))
            k += _DURABILITY_KJ_STEP

    if not best_fresh or not best_at_k:
        return _param(
            1.0, "fraction", "default (unmeasured)", "low",
            "No cached ride is long enough to measure power decay after meaningful work. "
            "Defaulting to no measured decay — this will tighten as longer rides accumulate.",
        )

    k_max = max(best_at_k)
    value = min(1.0, best_at_k[k_max] / best_fresh)
    confidence = "medium" if k_max >= 1000 else "low"
    return _param(
        round(value, 3), "fraction", f"measured at {k_max} kJ", confidence,
        f"Best {_DURABILITY_WINDOW_SEC // 60}min after {k_max} kJ of work ({best_at_k[k_max]:.0f}W) vs fresh "
        f"({best_fresh:.0f}W), across {rides_used} ride(s). The race-relevant question is decay at 2000+ kJ; "
        f"{k_max} kJ is as deep as any cached ride goes, so treat this as an early reading, not the answer.",
    )


def _measure_repeatability() -> dict[str, Any]:
    best_ride_punches: list[float] = []

    for ride in power_curve.cached_rides():
        series = power_curve._dense_power_series(ride["samples"])
        n = len(series)
        if n < _PUNCH_WINDOW_SEC * 3:
            continue
        prefix = [0.0] * (n + 1)
        for i, v in enumerate(series):
            prefix[i + 1] = prefix[i] + (v or 0.0)
        window = lambda i: (prefix[i + _PUNCH_WINDOW_SEC] - prefix[i]) / _PUNCH_WINDOW_SEC  # noqa: E731
        best30 = max(window(i) for i in range(n - _PUNCH_WINDOW_SEC))
        if best30 <= 0:
            continue
        punches = []
        i = 0
        while i < n - _PUNCH_WINDOW_SEC:
            w = window(i)
            if w >= _PUNCH_THRESHOLD * best30:
                punches.append(w)
                i += _PUNCH_WINDOW_SEC + _PUNCH_SPACING_SEC
            else:
                i += 5
        if len(punches) > len(best_ride_punches):
            best_ride_punches = punches

    if len(best_ride_punches) < 2:
        return _param(
            0.85, "fraction", "default (unmeasured)", "low",
            f"No cached ride contains 2+ near-maximal {_PUNCH_WINDOW_SEC}s punches "
            f"(≥{int(_PUNCH_THRESHOLD * 100)}% of that ride's best), so repeat-effort decay can't be "
            "measured yet. Defaulting to 0.85 — a deliberate placeholder, not a measurement.",
        )

    first = best_ride_punches[0]
    later = sum(best_ride_punches[1:]) / (len(best_ride_punches) - 1)
    value = max(PARAM_BOUNDS["repeatability"][0], min(1.0, later / first))
    confidence = "medium" if len(best_ride_punches) >= 4 else "low"
    return _param(
        round(value, 3), "fraction", f"measured across {len(best_ride_punches)} punches", confidence,
        f"Average of punches 2..{len(best_ride_punches)} ({later:.0f}W) vs the first ({first:.0f}W) "
        "within the single ride that had the most near-max efforts.",
    )


def compute() -> dict[str, Any]:
    """Compute the model from current data, then lay locked overrides on top.

    The returned dict is stored whole — computed values, overrides, the input
    snapshot, and timestamps — so any later question of "why does the model say
    X" has its answer attached rather than reconstructed.
    """
    from config.athlete_profile import FTP_TEST_FACTOR
    from services import ftp as ftp_service

    current_ftp = ftp_service.current_ftp()
    ftp_watts = current_ftp.get("ftp_watts")

    points, fit_notes = _fit_points(ftp_watts, FTP_TEST_FACTOR)
    fit = fit_cp_wprime(points)

    if fit:
        cp, w_prime = fit
        lo, hi = PARAM_BOUNDS["cp_watts"]
        cp = max(lo, min(hi, cp))
        lo, hi = PARAM_BOUNDS["w_prime_j"]
        w_prime = max(lo, min(hi, w_prime))
        n_pts = len(points)
        reasoning = (
            f"2-parameter critical-power fit (work = W′ + CP·t) over {n_pts} mean-max points "
            f"at {sorted(points)}s. " + " ".join(fit_notes)
        )
        cp_param = _param(round(cp, 1), "W", f"CP fit ({n_pts} points)", "medium" if n_pts >= 3 else "low", reasoning)
        wp_param = _param(round(w_prime, 0), "J", f"CP fit ({n_pts} points)", "medium" if n_pts >= 3 else "low", reasoning)
    else:
        cp_param = _param(
            ftp_watts, "W", "FTP fallback", "low",
            "Too few 2–20min maximal points for a CP fit — using current FTP as the aerobic ceiling.",
        )
        wp_param = _param(
            20_000.0, "J", "default (unmeasured)", "low",
            "No CP fit possible, so W′ is a population-typical placeholder (20 kJ), not a measurement.",
        )

    params = {
        "cp_watts": cp_param,
        "w_prime_j": wp_param,
        "durability": _measure_durability(),
        "repeatability": _measure_repeatability(),
    }

    overrides = local_store.get_model_overrides()
    for name, ov in overrides.items():
        if name in params and ov.get("locked"):
            params[name] = {
                **params[name],
                "computed_value": params[name]["value"],
                "value": ov["value"],
                "source": "manual override (locked)",
                "confidence": "user",
                "reasoning": ov.get("reason") or "Manually set and locked by the athlete.",
                "locked": True,
            }

    model = {
        "params": params,
        "inputs_snapshot": {
            "fit_points": {str(k): round(v, 1) for k, v in points.items()},
            "ftp": current_ftp,
            "rides_analyzed": [str(r["activity_id"]) for r in power_curve.cached_rides()],
            "overrides_applied": [k for k, v in overrides.items() if v.get("locked")],
        },
        "computed_at": time.time(),
    }
    local_store.save_physiology_model(model)
    return model


def effective_values(model: Optional[dict[str, Any]] = None) -> dict[str, float]:
    """Just the numbers, for consumers (demand gap, backtest) that don't need
    the provenance wrapper."""
    model = model or local_store.get_physiology_model() or compute()
    return {name: p["value"] for name, p in model["params"].items() if p.get("value") is not None}
