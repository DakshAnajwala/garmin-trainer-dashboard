"""Advisory backtest: does a model change make predictions better or worse?

When the athlete edits a parameter or brings their own algorithm (F6), the
change is scored against held-out reality before they commit to it: the most
recent ride's maximal efforts are set aside, a comparison model is fit without
them, and both parameter sets predict those efforts through the 2-parameter
model (P(t) = CP + W′/t). Mean absolute percentage error, side by side, with
the delta. **Advisory only — it reports, it never blocks.** The athlete may
know exactly why a "worse-fitting" model is right (illness, a new meter, a
deliberately conservative race plan).

Honest limits, stated where the athlete will see them:

- Only CP and W′ are scoreable this way — they predict power-at-duration,
  which held-out efforts can check. Durability and repeatability shape *plans*,
  not P(t) predictions, so changes to them return "not scoreable by this
  backtest" rather than a fabricated verdict.
- The comparison fit excludes the held-out ride's contributions (no grading
  your own homework), but keeps the manual FTP anchor — that's an independent
  test, not part of the held-out ride.
"""
from __future__ import annotations

from typing import Any, Optional

from services import power_curve
from services.physiology_model import _FIT_DURATIONS, fit_cp_wprime

#: Verdict dead-band: error changes smaller than this are noise, not signal.
_NEUTRAL_BAND_PP = 0.5


def _predict(cp: float, w_prime: float, duration_s: int) -> float:
    return cp + w_prime / duration_s


def holdout_efforts() -> tuple[Optional[str], list[dict[str, Any]]]:
    """Maximal efforts (reliable, 2–20 min) from the most recent powered ride.

    "Powered" is checked against the raw samples, not the derived curve: a ride
    with no power meter zero-fills into a curve of 0 W points, which are not
    efforts — scoring against them crashed on a real outdoor ride whose 522
    samples carry no power at all.
    """
    rides = [r for r in power_curve.cached_rides() if r.get("date")]
    for ride in sorted(rides, key=lambda r: r["date"], reverse=True):
        if not any(s.get("power_w") for s in ride["samples"]):
            continue
        curve = power_curve.ride_curve(ride["samples"], durations=_FIT_DURATIONS)
        efforts = [
            {"duration_s": d, "watts": p["watts"], "date": ride["date"]}
            for d, p in curve.items()
            if p.get("reliable") and p["watts"] > 0
        ]
        if efforts:
            return str(ride["activity_id"]), efforts
    return None, []


def _blind_fit(exclude_activity_id: str) -> Optional[tuple[float, float]]:
    """CP/W′ fit from everything except the held-out ride. The manual FTP
    anchor stays in — it's an independent measurement, not held-out data."""
    from config.athlete_profile import FTP_TEST_FACTOR
    from services import ftp as ftp_service

    rides = [r for r in power_curve.cached_rides() if str(r["activity_id"]) != exclude_activity_id]
    curve = power_curve.all_time_curve(rides, power_curve.local_store.get_power_exclusions(), _FIT_DURATIONS)
    points = {d: p["watts"] for d, p in curve.items() if p.get("reliable")}

    ftp_watts = ftp_service.current_ftp().get("ftp_watts")
    if ftp_watts:
        anchor = ftp_watts / FTP_TEST_FACTOR
        points[1200] = max(points.get(1200, 0), anchor)
    return fit_cp_wprime(points)


def _mape(cp: float, w_prime: float, efforts: list[dict[str, Any]]) -> Optional[float]:
    errors = [
        abs(_predict(cp, w_prime, e["duration_s"]) - e["watts"]) / e["watts"]
        for e in efforts
        if e["watts"]
    ]
    return 100 * sum(errors) / len(errors) if errors else None


def evaluate_change(proposed: dict[str, float], current: dict[str, float]) -> dict[str, Any]:
    """Score `proposed` {cp_watts, w_prime_j, ...} against `current` on held-out
    maximal efforts. Returns verdict + both errors + the efforts used, so the
    UI can show the numbers instead of asking for trust.
    """
    cp_changed = proposed.get("cp_watts") != current.get("cp_watts")
    wp_changed = proposed.get("w_prime_j") != current.get("w_prime_j")
    if not cp_changed and not wp_changed:
        return {
            "verdict": "not_scoreable",
            "detail": (
                "Only CP and W′ predict power-at-duration, which is what held-out efforts can check. "
                "Durability/repeatability changes shape the plan, not P(t) — no fabricated verdict."
            ),
        }

    holdout_id, efforts = holdout_efforts()
    if not efforts:
        return {
            "verdict": "insufficient_data",
            "detail": "No powered ride with reliable 2-20min efforts to hold out yet.",
        }

    blind = _blind_fit(holdout_id)
    baseline_cp = current.get("cp_watts")
    baseline_wp = current.get("w_prime_j")
    baseline_note = "current model"
    if blind:
        # Prefer the holdout-blind refit as the baseline where possible — the
        # current model may have been fit on the very ride we're predicting.
        baseline_cp, baseline_wp = blind
        baseline_note = "holdout-blind refit of the current approach"
    if baseline_cp is None or baseline_wp is None:
        return {"verdict": "insufficient_data", "detail": "No baseline CP/W′ to compare against."}

    err_current = _mape(baseline_cp, baseline_wp, efforts)
    err_proposed = _mape(
        proposed.get("cp_watts", baseline_cp), proposed.get("w_prime_j", baseline_wp), efforts
    )
    if err_current is None or err_proposed is None:
        return {"verdict": "insufficient_data", "detail": "Held-out efforts carry no usable power."}
    delta = err_proposed - err_current

    if delta < -_NEUTRAL_BAND_PP:
        verdict = "improved"
    elif delta > _NEUTRAL_BAND_PP:
        verdict = "worse"
    else:
        verdict = "neutral"

    return {
        "verdict": verdict,
        "error_current_pct": round(err_current, 2),
        "error_proposed_pct": round(err_proposed, 2),
        "delta_pp": round(delta, 2),
        "holdout_activity_id": holdout_id,
        "holdout_efforts": efforts,
        "baseline": baseline_note,
        "detail": (
            f"Predicting the held-out ride's maximal efforts: proposed model errs "
            f"{err_proposed:.1f}% vs {err_current:.1f}% for the {baseline_note} "
            f"({delta:+.1f} percentage points). Advisory only — you may know something the data doesn't."
        ),
    }
