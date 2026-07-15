"""Athlete facts that Garmin doesn't provide — loaded from your own config.

Copy `athlete_profile.example.json` to `athlete_profile.json` and fill in your
numbers. That file is gitignored, so your physiology, test history and
coaching context stay on your machine and never reach the repo.

Everything here is self-reported: the power curve is your best known efforts,
not a lab measurement, and `power_curve_unverified` marks durations you
haven't actually tested to failure, so the UI can say so rather than implying
precision that isn't there.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_PROFILE_PATH = Path(__file__).resolve().parent / "athlete_profile.json"
_EXAMPLE_PATH = Path(__file__).resolve().parent / "athlete_profile.example.json"


def _load() -> dict[str, Any]:
    if _PROFILE_PATH.exists():
        return json.loads(_PROFILE_PATH.read_text())
    if _EXAMPLE_PATH.exists():
        # Fall back to the example so a fresh clone boots and you can click
        # around before filling anything in. The numbers are placeholders —
        # every W/kg, zone and coaching answer is wrong until you copy this to
        # athlete_profile.json and put your own values in.
        return json.loads(_EXAMPLE_PATH.read_text())
    raise FileNotFoundError(
        f"No athlete profile found. Copy config/{_EXAMPLE_PATH.name} to config/{_PROFILE_PATH.name} and edit it."
    )


_profile = _load()

#: True when running on placeholder data — surfaced in the UI as a warning.
USING_EXAMPLE_PROFILE = not _PROFILE_PATH.exists()

# Best power per duration (seconds -> watts). JSON keys are strings; the rest
# of the app indexes by int.
POWER_CURVE_SECONDS: dict[int, int] = {int(k): v for k, v in _profile["power_curve_seconds"].items()}

# Durations you haven't confirmed as true maximal efforts.
POWER_CURVE_UNVERIFIED: set[int] = {int(d) for d in _profile.get("power_curve_unverified", [])}

# FTP = ftp_test_factor x best 20min power. 0.95 is the usual convention.
FTP_TEST_FACTOR: float = _profile.get("ftp_test_factor", 0.95)
FTP_TEST_HISTORY: list[dict[str, Any]] = [
    {
        "date": test["date"],
        "power_20min_w": test["power_20min_w"],
        "ftp_w": round(test["power_20min_w"] * FTP_TEST_FACTOR, 1),
    }
    for test in _profile.get("ftp_test_history", [])
]

LIMITER: str = _profile.get("limiter", "")
MAX_HR_BPM: tuple[int, int] = tuple(_profile["max_hr_bpm"])
LTHR_BPM: int = _profile["lthr_bpm"]
FLOOR_WEIGHT_KG: float = _profile["floor_weight_kg"]

# Free-text block describing you, your goal and your constraints, injected
# into the coach's system prompt. Prose rather than fixed fields because what
# a coach needs to know about you doesn't fit a rigid schema.
COACH_CONTEXT: str = _profile.get("coach_context", "")
