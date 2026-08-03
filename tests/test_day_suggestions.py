"""The "what should I do today?" payload contract.

The endpoint returns previews only, and "add to calendar" is a plain PUT of
the `workout` object it handed back. That only stays true if the payload is
accepted by the same Pydantic model the write endpoint enforces — otherwise
the athlete gets three suggestions where clicking one 422s. These tests pin
that round-trip rather than the prose.
"""
from __future__ import annotations

from datetime import date

import pytest

from api.main import PlannedWorkoutModel, _option_payload
from services import day_planner as dp

NEUROMUSCULAR = "Neuromuscular (~15s; Coggan reference is 5s)"
ANAEROBIC_CAP = "Anaerobic Capacity (1min)"
VO2MAX_ROW = "VO2max (5min; self-reported as not a max effort)"
THRESHOLD_ROW = "Functional Threshold (current FTP; Coggan reference is 20min)"

FTP = 219.0

#: Every branch of compose_three_options' decision tree, so the round-trip is
#: checked for the rest/note/strength/team-ride shapes too — not just the
#: structured interval sessions that obviously have steps.
DAYS = [
    ("monday-rest-gate", date(2026, 8, 3), "TRAIN", {}),
    ("saturday-team-ride", date(2026, 8, 8), "TRAIN", {}),
    ("sunday-long-ride", date(2026, 8, 9), "TRAIN", {}),
    ("normal-tuesday", date(2026, 8, 4), "TRAIN", {}),
    ("rest-verdict", date(2026, 8, 4), "REST", {}),
    ("easy-verdict", date(2026, 8, 4), "EASY", {}),
    ("unknown-verdict", date(2026, 8, 4), "UNKNOWN", {}),
    ("loaded-week", date(2026, 8, 4), "TRAIN", {"2026-08-05": {"session_type": "intervals", "title": "VO2max"}}),
]

WEAKNESSES = [NEUROMUSCULAR, ANAEROBIC_CAP, VO2MAX_ROW, THRESHOLD_ROW, None]


def _payloads(target_date, verdict, week, weakest=NEUROMUSCULAR, ftp=FTP):
    options = dp.compose_three_options(weakest, None, week, verdict, target_date, ftp)
    return [_option_payload(o) for o in options]


class TestPayloadRoundTrip:
    @pytest.mark.parametrize("name,target_date,verdict,week", DAYS)
    def test_every_option_validates_as_a_planned_workout(self, name, target_date, verdict, week):
        for payload in _payloads(target_date, verdict, week):
            PlannedWorkoutModel(**payload["workout"])  # raises if the shape is wrong

    @pytest.mark.parametrize("weakest", WEAKNESSES)
    def test_round_trip_holds_for_every_weakness(self, weakest):
        for payload in _payloads(date(2026, 8, 4), "TRAIN", {}, weakest=weakest):
            PlannedWorkoutModel(**payload["workout"])

    def test_round_trip_holds_with_no_ftp_logged(self):
        """A brand-new account has no FTP — the suggestions must still be
        addable, not just renderable."""
        for payload in _payloads(date(2026, 8, 4), "TRAIN", {}, weakest=None, ftp=None):
            PlannedWorkoutModel(**payload["workout"])

    def test_the_workout_title_matches_the_option_title(self):
        """What lands on the calendar has to be what was previewed."""
        for payload in _payloads(date(2026, 8, 4), "TRAIN", {}):
            assert payload["workout"]["title"] == payload["title"]

    def test_options_are_tagged_as_coach_sourced(self):
        """So a later regenerate treats them as suggestions, not hand-built
        sessions it must leave alone."""
        for payload in _payloads(date(2026, 8, 4), "TRAIN", {}):
            assert payload["workout"]["source"] == "coach"


class TestPayloadCompleteness:
    @pytest.mark.parametrize("name,target_date,verdict,week", DAYS)
    def test_required_fields_are_always_present(self, name, target_date, verdict, week):
        for payload in _payloads(target_date, verdict, week):
            for key in ("kind", "exclusive_with", "title", "detail", "reason", "workout"):
                assert key in payload, key
            assert payload["reason"], f"{payload['title']} has no visible why"

    def test_strength_options_carry_a_loggable_type(self):
        """The 'mark as done' flow writes straight to /api/strength, so a
        planned strength session must already know how it will be logged."""
        valid = {"general", "lower_body", "upper_body", "core", "full_body"}
        payloads = _payloads(date(2026, 8, 4), "TRAIN", {})
        strength = [p for p in payloads if p["kind"] == "strength"]
        assert strength
        for p in strength:
            assert p["strength_log_type"] in valid
            assert p["workout"]["session_type"] == "strength"

    @pytest.mark.parametrize("weakest", WEAKNESSES)
    def test_the_log_type_survives_the_save(self, weakest):
        """Regression: strength_log_type was returned on the option but wasn't
        a field on PlannedWorkoutModel, so pydantic dropped it on save and
        "mark as done" fell back to full_body — silently throwing away the
        weakness targeting at the exact moment the session was completed."""
        payloads = _payloads(date(2026, 8, 4), "TRAIN", {}, weakest=weakest)
        strength = next(p for p in payloads if p["kind"] == "strength")
        saved = PlannedWorkoutModel(**strength["workout"])
        assert saved.strength_log_type == strength["strength_log_type"]
        assert saved.strength_log_type is not None

    def test_non_strength_options_carry_no_strength_fields(self):
        for p in _payloads(date(2026, 8, 4), "TRAIN", {}):
            if p["kind"] != "strength":
                assert p["strength_focus"] is None
                assert p["strength_log_type"] is None

    @pytest.mark.parametrize("name,target_date,verdict,week", DAYS)
    def test_always_exactly_three_options(self, name, target_date, verdict, week):
        assert len(_payloads(target_date, verdict, week)) == 3
