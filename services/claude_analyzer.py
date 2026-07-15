"""Claude-powered coaching, grounded in your athlete profile and today's live
Garmin snapshot.

The personal half of the system prompt comes from `coach_context` in
config/athlete_profile.json — see _build_system_prompt below.
"""
from __future__ import annotations

from typing import Any, Optional

import anthropic

from config.athlete_profile import COACH_CONTEXT, FTP_TEST_FACTOR, LIMITER, LTHR_BPM, MAX_HR_BPM
from config.settings import settings
from garmin_mcp.schemas import DailyHealthSnapshot

SUGGESTED_FOLLOWUPS = [
    "Why am I feeling tired today?",
    "How should I approach this week's group ride given my readiness?",
    "What should I eat today to support recovery and my weight goal?",
]


def _build_system_prompt() -> str:
    """Generic coaching instructions plus whatever the athlete wrote about
    themselves in config/athlete_profile.json. The personal half lives in that
    (gitignored) file rather than in source, so this repo carries no one's
    physiology — and so the coach can be told things a fixed schema could
    never capture ("never suggest I skip Saturday", "I'm gaining weight on
    purpose")."""
    base = (
        "You are a data-driven cycling coach. Your athlete's goal is "
        f"{settings.target_wkg} W/kg FTP, tracked DYNAMICALLY (target watts = "
        f"{settings.target_wkg} x today's actual weight) — never as a fixed wattage number, "
        "because weight changes over time.\n\n"
        f"FTP convention: FTP = {FTP_TEST_FACTOR} x best 20min power. Garmin's own auto FTP "
        "estimate also appears in the live data below.\n"
    )
    facts = []
    if LIMITER:
        facts.append(f"- Limiter (self-identified weakness): {LIMITER}. Weight advice toward this zone.")
    facts.append(f"- Max HR {MAX_HR_BPM[0]}-{MAX_HR_BPM[1]}bpm, LTHR {LTHR_BPM}bpm.")
    if facts:
        base += "\n" + "\n".join(facts) + "\n"
    if COACH_CONTEXT:
        base += "\n" + COACH_CONTEXT + "\n"
    base += (
        "\nGround every answer in the live data provided in the user message; don't invent "
        "numbers you weren't given. If a metric is missing, say so rather than guessing."
    )
    return base


_SYSTEM_PROMPT = _build_system_prompt()


def _client() -> anthropic.Anthropic:
    if not settings.anthropic_api_key or settings.anthropic_api_key == "sk-ant-placeholder":
        raise RuntimeError(
            "No real Anthropic API key configured. Run `python -m scripts.set_secrets` "
            "once to store it (encrypted) and enable the coach."
        )
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _snapshot_context(snapshot: DailyHealthSnapshot, weight_kg: Optional[float]) -> str:
    lines = [f"Today's date: {snapshot.date} ({snapshot.date.strftime('%A')})"]

    if snapshot.training_readiness:
        r = snapshot.training_readiness
        lines.append(f"Garmin Training Readiness: {r.readiness_score}/100 ({r.level}), feedback: {r.feedback}")
    if snapshot.hrv:
        h = snapshot.hrv
        lines.append(
            f"HRV last night: {h.last_night_avg_ms}ms (7-day avg {h.weekly_avg_ms}ms, "
            f"balanced band {h.baseline_low_ms}-{h.baseline_high_ms}ms, status {h.status})"
        )
    if snapshot.resting_heart_rate and snapshot.resting_heart_rate.resting_hr_bpm:
        lines.append(f"Resting HR: {snapshot.resting_heart_rate.resting_hr_bpm}bpm")
    if snapshot.sleep:
        s = snapshot.sleep
        lines.append(f"Sleep score: {s.sleep_score}, total sleep: {s.total_sleep_hours}h")
    if snapshot.body_battery:
        b = snapshot.body_battery
        lines.append(f"Body Battery: charged {b.charged}, drained {b.drained}")
    if snapshot.stress:
        lines.append(f"Avg stress: {snapshot.stress.avg_stress_level}, max: {snapshot.stress.max_stress_level}")
    if snapshot.respiration and snapshot.respiration.avg_waking_breaths_per_min:
        lines.append(f"Waking breathing rate: {snapshot.respiration.avg_waking_breaths_per_min:.0f}/min")
    if snapshot.training_load:
        t = snapshot.training_load
        lines.append(
            f"Training load: acute {t.acute_load}, chronic {t.chronic_load}, "
            f"ACWR {t.acwr} ({t.acwr_status}), status: {t.status}"
        )
    if snapshot.vo2_max and snapshot.vo2_max.vo2_max_cycling:
        lines.append(f"VO2max (cycling): {snapshot.vo2_max.vo2_max_cycling}")

    ftp_watts = snapshot.cycling_ftp.ftp_watts if snapshot.cycling_ftp else None
    if ftp_watts:
        lines.append(f"Garmin's auto FTP estimate: {ftp_watts}W (as of {snapshot.cycling_ftp.date})")
    if weight_kg:
        lines.append(f"Latest logged weight: {weight_kg}kg")
        if ftp_watts:
            lines.append(f"Current W/kg: {round(ftp_watts / weight_kg, 2)} (target {settings.target_wkg})")
    else:
        lines.append("No weight logged yet — W/kg can't be computed today.")

    # Rider phenotype (climber/sprinter/etc) — lets the coach tailor race-day tactics.
    try:
        from services import ftp as ftp_service
        from services import rider_profile

        resolved = ftp_service.current_ftp(ftp_watts)["ftp_watts"]
        profile = rider_profile.classify(resolved)
        if profile["type"]:
            scores = ", ".join(f"{k}: {v}" for k, v in profile["scores"].items())
            lines.append(f"Rider phenotype (heuristic): {profile['type']} ({scores})")
    except Exception:
        pass

    return "\n".join(lines)


def analyze_day(snapshot: DailyHealthSnapshot, weight_kg: Optional[float] = None) -> str:
    context = _snapshot_context(snapshot, weight_kg)
    return _send(
        model=settings.anthropic_model,
        max_tokens=700,
        system=_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Here is today's live data:\n\n{context}\n\n"
                    "Analyze how my day has been and give me a clear recommendation for "
                    "today's training, in a few short paragraphs."
                ),
            }
        ],
    )


def _send(**kwargs) -> str:
    """All Claude calls go through here so an invalid/missing key produces one
    clear, actionable message instead of a raw 401 JSON blob in the UI."""
    try:
        return _client().messages.create(**kwargs).content[0].text
    except anthropic.AuthenticationError as exc:
        raise RuntimeError(
            "Anthropic rejected the stored API key. Re-run `python -m scripts.set_secrets` "
            "with a valid key, then restart the backend."
        ) from exc


def _ride_context(
    activity: dict[str, Any], splits: list[dict[str, Any]], decoupling: dict[str, Any], ftp_watts: Optional[float]
) -> str:
    lines = [f"Activity: {activity.get('name')} ({activity.get('type')}) on {activity.get('start_time_local')}"]
    duration = activity.get("duration_sec")
    if duration:
        lines.append(f"Duration: {round(duration / 60)} min")
    if activity.get("distance_m"):
        lines.append(f"Distance: {activity['distance_m'] / 1000:.1f} km")
    if activity.get("elevation_gain_m"):
        lines.append(f"Elevation gain: {round(activity['elevation_gain_m'])} m")
    for label, key in [("Avg HR", "avg_hr"), ("Max HR", "max_hr"), ("Avg power", "avg_power_w"),
                       ("Norm power", "norm_power_w"), ("Max power", "max_power_w")]:
        if activity.get(key):
            lines.append(f"{label}: {activity[key]}")
    if ftp_watts:
        lines.append(f"Current FTP: {ftp_watts}W")
        if activity.get("norm_power_w"):
            lines.append(f"Intensity factor (NP/FTP): {activity['norm_power_w'] / ftp_watts:.2f}")

    if splits:
        lines.append(f"\nLap splits ({len(splits)} laps):")
        for lap in splits[:20]:  # long rides can have dozens; the shape is clear from the first 20
            parts = [f"  Lap {lap.get('lap_index')}"]
            if lap.get("duration_sec"):
                parts.append(f"{round(lap['duration_sec'] / 60, 1)}min")
            if lap.get("distance_m"):
                parts.append(f"{lap['distance_m'] / 1000:.1f}km")
            if lap.get("avg_power_w"):
                parts.append(f"{round(lap['avg_power_w'])}W")
            if lap.get("avg_hr"):
                parts.append(f"{round(lap['avg_hr'])}bpm")
            lines.append(" — ".join(parts))

    if decoupling.get("available"):
        lines.append(
            f"\nAerobic decoupling: {decoupling['decoupling_pct']}% "
            f"(first half Pw:Hr {decoupling['first_half_pw_hr']}, second half {decoupling['second_half_pw_hr']}; "
            f"under {decoupling['threshold_pct']}% is considered aerobically durable)"
        )
    else:
        lines.append(f"\nAerobic decoupling: not available — {decoupling.get('reason')}")

    return "\n".join(lines)


def analyze_ride(
    activity: dict[str, Any],
    splits: list[dict[str, Any]],
    decoupling: dict[str, Any],
    ftp_watts: Optional[float] = None,
) -> str:
    context = _ride_context(activity, splits, decoupling, ftp_watts)
    return _send(
        model=settings.anthropic_model,
        max_tokens=800,
        system=_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Here is one specific ride of mine:\n\n{context}\n\n"
                    "Analyze this ride: what it did for me, what the lap/decoupling data says about "
                    "how well it went, and what it means for my training. Be specific and concise. "
                    "If a metric is unavailable, say so rather than guessing at it."
                ),
            }
        ],
    )


def chat_reply(
    history: list[dict[str, str]], snapshot: DailyHealthSnapshot, weight_kg: Optional[float] = None
) -> str:
    context = _snapshot_context(snapshot, weight_kg)
    grounded_system = _SYSTEM_PROMPT + f"\n\nToday's live data:\n{context}"
    return _send(
        model=settings.anthropic_model,
        max_tokens=700,
        system=grounded_system,
        messages=history,
    )
