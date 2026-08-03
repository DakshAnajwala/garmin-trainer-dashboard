"""The deterministic "decide for me" + placement-warning logic.

A real bug was caught writing these: the planner's own type vocabulary
(vo2max, lactate_threshold, ...) was being compared directly against
plan_reflow's _HARD_TYPES, which classifies STORED session_type values
(intervals, long_ride, team_ride). Every catalog type maps to session_type
"intervals" except endurance, so that comparison silently always returned
False — stacking-avoidance and placement warnings never fired. Several tests
below exist specifically to pin that fix.
"""
from __future__ import annotations

from datetime import date

from services import day_planner as dp

NEUROMUSCULAR = "Neuromuscular (~15s; Coggan reference is 5s)"
ANAEROBIC_CAP = "Anaerabic Capacity (1min)".replace("Anaerabic", "Anaerobic")
VO2MAX_ROW = "VO2max (5min; self-reported as not a max effort)"
THRESHOLD_ROW = "Functional Threshold (current FTP; Coggan reference is 20min)"


class TestDecideType:
    def test_threshold_weakness_maps_to_lactate_threshold(self):
        t, reason = dp.decide_type(THRESHOLD_ROW, None, {})
        assert t == "lactate_threshold"
        assert "weakest zone" in reason.lower()

    def test_vo2max_weakness_maps_to_vo2max(self):
        t, _ = dp.decide_type(VO2MAX_ROW, None, {})
        assert t == "vo2max"

    def test_anaerobic_capacity_weakness_maps_to_anaerobic(self):
        t, _ = dp.decide_type(ANAEROBIC_CAP, None, {})
        assert t == "anaerobic"

    def test_neuromuscular_falls_back_to_anaerobic_with_a_caveat(self):
        """No true sprint-power prescription exists in the catalog — this must
        be the honest fallback, not a silent mismatch."""
        t, reason = dp.decide_type(NEUROMUSCULAR, None, {})
        assert t == "anaerobic"
        assert "closest match" in reason.lower()

    def test_no_signal_at_all_defaults_to_endurance(self):
        t, reason = dp.decide_type(None, None, {})
        assert t == "endurance"
        assert "no weakness signal" in reason.lower()

    def test_race_gap_beats_coggan_weakness(self):
        gap = [{"type": "sustained_climb", "status": "gap", "demand": "needs 195W after 133kJ"}]
        t, reason = dp.decide_type(THRESHOLD_ROW, gap, {})
        assert t == "lactate_threshold"
        assert "race demand" in reason.lower()

    def test_a_gap_status_of_ok_is_not_treated_as_a_weakness(self):
        gap = [{"type": "sustained_climb", "status": "ok", "demand": "no problem here"}]
        t, _ = dp.decide_type(VO2MAX_ROW, gap, {})
        assert t == "vo2max"  # falls through to the Coggan signal, gap is fine

    def test_repeated_surges_gap_maps_to_anaerobic(self):
        gap = [{"type": "repeated_surges", "status": "gap", "demand": "3 punches, worst 493W"}]
        t, _ = dp.decide_type(None, gap, {})
        assert t == "anaerobic"

    def test_durability_gap_maps_to_endurance(self):
        gap = [{"type": "durability", "status": "gap", "demand": "needs 95% of day-CP late"}]
        t, _ = dp.decide_type(None, gap, {})
        assert t == "endurance"


class TestStackingAvoidance:
    """Regression coverage for the vocabulary bug: a hard catalog type must be
    downgraded to endurance when the week already carries a hard STORED
    session, even though the two use different type names."""

    def test_hard_pick_downgrades_when_week_already_has_a_hard_session(self):
        week = {"2026-07-22": {"session_type": "intervals", "title": "VO2max"}}
        t, reason = dp.decide_type(ANAEROBIC_CAP, None, week)
        assert t == "endurance"
        assert "already has a hard session" in reason

    def test_hard_pick_survives_when_week_has_only_easy_sessions(self):
        week = {"2026-07-20": {"session_type": "endurance", "title": "Base"}}
        t, _ = dp.decide_type(THRESHOLD_ROW, None, week)
        assert t == "lactate_threshold"

    def test_long_ride_counts_as_a_hard_session_too(self):
        week = {"2026-07-26": {"session_type": "long_ride", "title": "Long ride"}}
        t, _ = dp.decide_type(VO2MAX_ROW, None, week)
        assert t == "endurance"

    def test_team_ride_counts_as_a_hard_session_too(self):
        week = {"2026-07-25": {"session_type": "team_ride", "title": "Team ride"}}
        t, _ = dp.decide_type(VO2MAX_ROW, None, week)
        assert t == "endurance"

    def test_endurance_pick_never_gets_downgraded_further(self):
        week = {"2026-07-22": {"session_type": "intervals", "title": "VO2max"}}
        t, _ = dp.decide_type(None, None, week)
        assert t == "endurance"


class TestPlacement:
    TUESDAY = date(2026, 7, 21)
    WEDNESDAY = date(2026, 7, 22)
    SATURDAY = date(2026, 7, 25)

    def test_no_warning_on_a_clean_day(self):
        assert dp.check_placement(self.TUESDAY, {}, "vo2max") is None

    def test_endurance_never_warns_regardless_of_neighbors(self):
        week = {"2026-07-21": {"session_type": "intervals", "title": "VO2max"}}
        assert dp.check_placement(self.WEDNESDAY, week, "endurance") is None

    def test_warns_when_yesterday_was_hard(self):
        week = {"2026-07-21": {"session_type": "intervals", "title": "VO2max intervals"}}
        warning = dp.check_placement(self.WEDNESDAY, week, "lactate_threshold")
        assert warning is not None
        assert "Yesterday" in warning

    def test_warns_when_tomorrow_is_hard(self):
        week = {"2026-07-23": {"session_type": "long_ride", "title": "Long ride"}}
        warning = dp.check_placement(self.WEDNESDAY, week, "vo2max")
        assert warning is not None
        assert "Tomorrow" in warning

    def test_saturday_always_warns_for_a_hard_type(self):
        assert dp.check_placement(self.SATURDAY, {}, "vo2max") is not None

    def test_saturday_does_not_warn_for_endurance(self):
        assert dp.check_placement(self.SATURDAY, {}, "endurance") is None

    def test_every_catalog_type_except_endurance_is_treated_as_hard(self):
        """The set that broke before: every non-endurance catalog type must
        trigger placement checks, not just ones that happen to be named the
        same as a stored session_type."""
        from services.workout_types import WORKOUT_TYPES

        week = {"2026-07-21": {"session_type": "intervals", "title": "x"}}
        for t in WORKOUT_TYPES:
            warning = dp.check_placement(self.WEDNESDAY, week, t)
            if t == "endurance":
                assert warning is None
            else:
                assert warning is not None, f"{t} should have warned about the adjacent hard day"
