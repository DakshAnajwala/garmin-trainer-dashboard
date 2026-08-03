"""The declared half of the athlete: what you told the app about yourself.

Its counterpart is services/physiology_model.py — what the app worked out from
your rides. Together they answer one question ("what is my engine?"), which is
why they share a tab.

Every field carries a `drives` line, because that's the thing nothing else in
the app says out loud: these look like settings, but each one silently
propagates somewhere load-bearing. ftp_test_factor moves your CP fit;
max_hr_bpm moves every zone; floor_weight_kg is a safety rail rather than a
preference. Read-only for now — making them editable needs the same
lock/reason/provenance machinery the model inspector already has, plus a
recompute story, and that is not something to bundle into a navigation change.
"""
from __future__ import annotations

from typing import Any

from config import athlete_profile
from config.settings import settings

_SOURCE_FILE = "config/athlete_profile.json"


def declared_profile() -> dict[str, Any]:
    fields = [
        {
            "key": "target_wkg",
            "label": "Target",
            "value": settings.target_wkg,
            "unit": "W/kg",
            "source": "environment (TARGET_WKG)",
            "drives": (
                "The trajectory target on the Power tab. Deliberately dynamic: the target watts are "
                "target × today's weight, so it moves with you instead of being a fixed number that "
                "quietly gets easier."
            ),
        },
        {
            "key": "ftp_test_factor",
            "label": "FTP test factor",
            "value": athlete_profile.FTP_TEST_FACTOR,
            "unit": "×",
            "source": _SOURCE_FILE,
            "drives": (
                "FTP = factor × your best 20min test. It also anchors the 20min point of the "
                "critical-power fit, so it moves CP — a change here shifts your whole model."
            ),
        },
        {
            "key": "max_hr_bpm",
            "label": "Max HR",
            "value": list(athlete_profile.MAX_HR_BPM),
            "unit": "bpm",
            "source": _SOURCE_FILE,
            "drives": "Every heart-rate zone in the app.",
        },
        {
            "key": "lthr_bpm",
            "label": "Lactate threshold HR",
            "value": athlete_profile.LTHR_BPM,
            "unit": "bpm",
            "source": _SOURCE_FILE,
            "drives": (
                "Threshold-based HR zones. Garmin's own measured value changing is treated as a "
                "personal record and surfaced on the fitness chart."
            ),
        },
        {
            "key": "floor_weight_kg",
            "label": "Floor weight",
            "value": athlete_profile.FLOOR_WEIGHT_KG,
            "unit": "kg",
            "source": _SOURCE_FILE,
            "drives": (
                "A safety rail, not a target. The coach will never suggest getting lighter than this — "
                "your strategy is to gain weight and power, so this exists to stop advice drifting the "
                "wrong way."
            ),
        },
        {
            "key": "limiter",
            "label": "Limiter",
            "value": athlete_profile.LIMITER,
            "unit": "",
            "source": _SOURCE_FILE,
            "drives": "What Wednesday's interval session is built to target.",
        },
    ]

    return {
        "fields": fields,
        "source_file": _SOURCE_FILE,
        "using_example_profile": athlete_profile.USING_EXAMPLE_PROFILE,
        "editable": False,
        "why_read_only": (
            "These aren't preferences — each one propagates into your model, your zones or your "
            "coaching. Editing them safely needs the same lock/reason/provenance treatment the "
            f"measured parameters below already have, so for now they're edited in {_SOURCE_FILE}."
        ),
    }
