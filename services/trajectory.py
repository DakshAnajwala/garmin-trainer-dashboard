"""FTP / weight / W-kg trajectory and the 4.5 W/kg milestone forecast.

Target watts is deliberately dynamic — 4.5 x *today's* weight, not a frozen
270W — because the athlete's plan is to gain weight and power together, so a
fixed wattage target would silently get easier as they get heavier.

FTP is projected with **diminishing returns**, not a straight line. Fitness
gains decay for the same training effort as you approach your ceiling: the
first months of a block buy far more watts than the twelfth. A linear fit
ignores that and compounds early gains forever — fitted to this athlete's
early tests it implied +171 W/year and had them at 7.6 W/kg within a year,
which is nonsense.

The model: the gain *rate* decays exponentially with a half-life, so

    FTP(t) = FTP_last + (v0 / k) * (1 - exp(-k*t))

where v0 is the recent rate from a least-squares fit and k = ln(2)/half-life.
This has a natural ceiling of FTP_last + v0/k, which is itself useful — if
the target sits above that ceiling, the honest answer is "not on this
trajectory", which a linear model can never say.

Weight stays linear: it's driven by deliberate eating, not by adaptation
approaching a physiological limit, so the same decay logic doesn't apply.
"""
from __future__ import annotations

import math
from datetime import date as date_, timedelta
from typing import Any, Optional

from config.settings import settings
from database import local_store

# Don't project further than this — a linear fit to a handful of points says
# nothing credible about 2030, and a banner claiming otherwise would be a lie.
_MAX_FORECAST_DAYS = 365 * 3
_MIN_POINTS_FOR_TREND = 2

# Below either of these the trend is drawn but labelled low-confidence. Two
# FTP tests 28 days apart imply +14.25 W/month (~+171 W/year) — a rate nobody
# sustains — which puts the target crossing absurdly early. The line is still
# shown (seeing it cross implausibly soon is more informative than hiding it),
# but the milestone is caveated rather than stated as a prediction.
_MIN_TESTS_FOR_CONFIDENCE = 3
_MIN_SPAN_DAYS_FOR_CONFIDENCE = 60

# Carry the projection a little past the goal so the crossing is visible
# rather than sitting exactly on the last plotted point.
_OVERSHOOT_MARGIN = 1.03

# ASSUMPTION: how fast the gain rate decays. At 9 months, whatever W/month
# you're gaining now, you gain half that 9 months from now for the same work.
# There's no way to fit this from 2-4 FTP tests, so it's a constant — chosen
# as a middle-ground for a developing rider (a novice would decay slower, an
# athlete near their ceiling faster). It's the single biggest lever on the
# forecast: halve it and the ceiling drops sharply.
_GAIN_HALF_LIFE_MONTHS = 9.0
_DAYS_PER_MONTH = 30.44


def _to_ordinal(d: str) -> int:
    return date_.fromisoformat(d).toordinal()


def _linear_fit(points: list[tuple[int, float]]) -> Optional[tuple[float, float]]:
    """Least-squares slope/intercept over (x, y). Returns None if the points
    are degenerate (all same x), which would divide by zero."""
    n = len(points)
    if n < _MIN_POINTS_FOR_TREND:
        return None
    sum_x = sum(x for x, _ in points)
    sum_y = sum(y for _, y in points)
    sum_xx = sum(x * x for x, _ in points)
    sum_xy = sum(x * y for x, y in points)
    denom = n * sum_xx - sum_x * sum_x
    if denom == 0:
        return None
    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n
    return slope, intercept


def build(forecast_days: int = 365) -> dict[str, Any]:
    ftp_tests = local_store.get_ftp_history()
    weights = local_store.get_weight_history(limit_days=100000)

    ftp_points = [(_to_ordinal(t["date"]), float(t["ftp_w"])) for t in ftp_tests if t.get("ftp_w")]
    weight_points = [(_to_ordinal(d), float(w)) for d, w in weights]

    if not ftp_points:
        return {"available": False, "reason": "Log an FTP test to see your trajectory.", "history": [], "forecast": []}
    if not weight_points:
        return {"available": False, "reason": "Log a weigh-in to compute W/kg.", "history": [], "forecast": []}

    ftp_fit = _linear_fit(ftp_points)
    weight_fit = _linear_fit(weight_points)

    # Project forward from the last *actual* value, not from the fitted line
    # evaluated at today — with sparse points the line has usually already
    # drifted well above the real last measurement, which would quietly
    # backdate the whole forecast.
    last_ftp_x, last_ftp_y = max(ftp_points)
    last_weight_x, last_weight_y = max(weight_points)

    # Diminishing returns: v0 is the current rate in W/day, decaying with
    # _GAIN_HALF_LIFE_MONTHS. Integrating the decaying rate gives the closed
    # form below, whose limit (the ceiling) is last_ftp_y + v0/k.
    v0 = ftp_fit[0] if ftp_fit else 0.0
    k = math.log(2) / (_GAIN_HALF_LIFE_MONTHS * _DAYS_PER_MONTH)
    ftp_ceiling = last_ftp_y + (v0 / k) if v0 > 0 else last_ftp_y

    def ftp_at(ordinal: int) -> float:
        if v0 <= 0:
            return last_ftp_y  # flat or declining trend: don't model decay onto a decline
        t = ordinal - last_ftp_x
        return last_ftp_y + (v0 / k) * (1 - math.exp(-k * t))

    def weight_at(ordinal: int) -> float:
        if not weight_fit:
            return last_weight_y  # single weigh-in: hold it flat rather than invent a trend
        return last_weight_y + weight_fit[0] * (ordinal - last_weight_x)

    # History rows are the real logged values, each paired with the weight in
    # force at that time (carried forward from the most recent prior weigh-in)
    # so W/kg is a real historical number, not a modelled one.
    history = []
    for ordinal, ftp in sorted(ftp_points):
        prior = [w for x, w in sorted(weight_points) if x <= ordinal]
        weight = prior[-1] if prior else weight_points[0][1]
        history.append(
            {
                "date": date_.fromordinal(ordinal).isoformat(),
                "ftp_w": round(ftp, 1),
                "weight_kg": round(weight, 1),
                "wkg": round(ftp / weight, 2),
                "target_watts": round(settings.target_wkg * weight, 1),
            }
        )

    latest = history[-1]
    today = date_.today().toordinal()
    span_days = max(ftp_points)[0] - min(ftp_points)[0]
    low_confidence = len(ftp_points) < _MIN_TESTS_FOR_CONFIDENCE or span_days < _MIN_SPAN_DAYS_FOR_CONFIDENCE

    forecast = []
    for offset in range(0, min(forecast_days, _MAX_FORECAST_DAYS) + 1, 7):  # weekly points keep the payload small
        ordinal = today + offset
        ftp = ftp_at(ordinal)
        weight = weight_at(ordinal)
        if weight <= 0:
            break
        wkg = ftp / weight
        forecast.append(
            {
                "date": date_.fromordinal(ordinal).isoformat(),
                "ftp_w": round(ftp, 1),
                "weight_kg": round(weight, 1),
                "wkg": round(wkg, 2),
                "target_watts": round(settings.target_wkg * weight, 1),
                "projected": True,
            }
        )
        # Stop once the trend clears the goal. Projecting past it is both
        # meaningless (the goal is the point) and actively harmful to the
        # chart: an unchecked steep trend runs to ~7.6 W/kg, which rescales
        # the axis until the real 3.6-3.8 history is an unreadable sliver.
        if wkg >= settings.target_wkg * _OVERSHOOT_MARGIN:
            break

    return {
        "available": True,
        "target_wkg": settings.target_wkg,
        "current": latest,
        "history": history,
        "forecast": forecast,
        "forecast_available": bool(forecast),
        "low_confidence": low_confidence,
        "ftp_test_count": len(ftp_points),
        "ftp_span_days": span_days,
        "milestone": _milestone(
            ftp_at, weight_at, today, latest, low_confidence, len(ftp_points), span_days, ftp_ceiling
        ),
        "ftp_slope_w_per_month": round(v0 * _DAYS_PER_MONTH, 2) if ftp_fit else None,
        "weight_slope_kg_per_month": round(weight_fit[0] * _DAYS_PER_MONTH, 3) if weight_fit else None,
        "weight_trend_available": weight_fit is not None,
        "ftp_ceiling_w": round(ftp_ceiling, 1),
        "gain_half_life_months": _GAIN_HALF_LIFE_MONTHS,
    }


def _milestone(
    ftp_at,
    weight_at,
    today: int,
    latest: dict[str, Any],
    low_confidence: bool,
    test_count: int,
    span_days: int,
    ftp_ceiling: float,
) -> dict[str, Any]:
    """When the projected W/kg first crosses the target, by day-stepping the
    two fitted lines. Solving analytically is possible but the ratio of two
    lines makes it fiddly for no gain at this scale."""
    target = settings.target_wkg
    caveat = (
        f" Treat this as a rough extrapolation, not a prediction — it's fitted to only {test_count} FTP "
        f"{'test' if test_count == 1 else 'tests'} over {span_days} days, which implies a gain rate that "
        f"almost certainly won't hold. Log a third test spanning {_MIN_SPAN_DAYS_FOR_CONFIDENCE}+ days to firm it up."
        if low_confidence
        else ""
    )

    if latest["wkg"] >= target:
        return {"reached": True, "message": f"You're already at {latest['wkg']} W/kg — target {target} W/kg met."}

    for offset in range(0, _MAX_FORECAST_DAYS + 1):
        ordinal = today + offset
        weight = weight_at(ordinal)
        if weight <= 0:
            break
        if ftp_at(ordinal) / weight >= target:
            when = date_.fromordinal(ordinal)
            # A crossing at/behind today means the fitted line has already
            # overtaken reality — say that rather than name a past month.
            if offset == 0:
                return {
                    "reached": False,
                    "date": None,
                    "low_confidence": low_confidence,
                    "message": (
                        f"Your recent trend is steep enough that it already projects past {target} W/kg — "
                        f"but you're actually at {latest['wkg']} W/kg, so the trend is running ahead of "
                        f"reality and can't give a meaningful date yet." + caveat
                    ),
                }
            return {
                "reached": False,
                "date": when.isoformat(),
                "days_away": offset,
                "low_confidence": low_confidence,
                "projected_watts": round(target * weight),
                "projected_weight_kg": round(weight, 1),
                "message": (
                    f"At your current progression rate, you reach {target} W/kg "
                    f"(~{round(target * weight)}W at {round(weight, 1)}kg) in {when.strftime('%B %Y')}." + caveat
                ),
            }

    # Gains decay toward a ceiling, so "never" is a real answer here — and a
    # more useful one than a linear model's date decades out.
    ceiling_weight = weight_at(today + _MAX_FORECAST_DAYS)
    ceiling_wkg = ftp_ceiling / ceiling_weight if ceiling_weight > 0 else 0
    if ceiling_wkg < target:
        return {
            "reached": False,
            "date": None,
            "low_confidence": low_confidence,
            "message": (
                f"On your current trajectory you plateau around {round(ftp_ceiling)}W "
                f"(~{round(ceiling_wkg, 2)} W/kg) — short of {target} W/kg. Gains decay as you approach your "
                f"ceiling, so reaching the target needs a change in stimulus, not just more of the same."
                + caveat
            ),
        }

    return {
        "reached": False,
        "date": None,
        "low_confidence": low_confidence,
        "message": (
            f"At your current progression rate you don't reach {target} W/kg within 3 years, "
            f"though you do trend toward it (plateau ~{round(ftp_ceiling)}W)." + caveat
        ),
    }
