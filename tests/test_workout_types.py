"""The deterministic workout-type catalog.

Every type must always produce a valid workout — this is what keeps
"Let my coach plan for me" working while the Anthropic key is invalid, so the
templates get the same scrutiny as anything else load-bearing.
"""
from __future__ import annotations

import pytest

from services import workout_types as wt

FTP = 220.0


class TestCatalog:
    def test_every_type_builds(self):
        for t in wt.WORKOUT_TYPES:
            w = wt.build(t, FTP)
            assert w.steps
            assert w.duration_min > 0

    def test_unknown_type_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown workout type"):
            wt.build("sprints", FTP)

    def test_duration_min_matches_the_actual_step_sum(self):
        """The headline duration must not lie about what the steps add up to."""
        for t in wt.WORKOUT_TYPES:
            w = wt.build(t, FTP)
            assert round(sum(s["duration_sec"] for s in w.steps) / 60) == w.duration_min

    def test_no_ftp_reports_tbd_rather_than_crashing(self):
        for t in wt.WORKOUT_TYPES:
            w = wt.build(t, None)
            assert w.target_watts_low is None
            assert "TBD" in w.detail


class TestOvergearing:
    def test_work_intervals_carry_low_cadence(self):
        w = wt.build("overgearing", FTP)
        work_steps = [s for s in w.steps if s.get("cadence_low_rpm") is not None]
        assert work_steps, "overgearing must have at least one cadence-targeted step"
        assert all(30 <= s["cadence_low_rpm"] <= 60 and 30 <= s["cadence_high_rpm"] <= 60 for s in work_steps)

    def test_intensity_matches_threshold_not_a_separate_zone(self):
        """Overgearing is defined BY cadence, not by a different power zone —
        it should sit in the same %FTP band as lactate_threshold."""
        over = wt.build("overgearing", FTP)
        thresh = wt.build("lactate_threshold", FTP)
        assert over.target_watts_low >= 0.9 * thresh.target_watts_low

    def test_recovery_steps_have_no_cadence_target(self):
        """Only the work intervals prescribe low cadence — recovery is free."""
        w = wt.build("overgearing", FTP)
        easy_steps = [s for s in w.steps if s["target_low_pct_ftp"] <= 0.55]
        assert all(s.get("cadence_low_rpm") is None for s in easy_steps)


class TestIntensityKnob:
    def test_intensity_is_clamped(self):
        low = wt.build("vo2max", FTP, intensity=-5)
        high = wt.build("vo2max", FTP, intensity=99)
        assert low.duration_min <= wt.build("vo2max", FTP, intensity=0).duration_min + 1
        assert high.duration_min >= wt.build("vo2max", FTP, intensity=1).duration_min - 1

    def test_higher_intensity_never_shortens_a_session(self):
        for t in wt.WORKOUT_TYPES:
            low = wt.build(t, FTP, intensity=0.0)
            high = wt.build(t, FTP, intensity=1.0)
            assert high.duration_min >= low.duration_min


class TestPowerZonesAreOrderedSensibly:
    """A sanity check on the catalog as a whole: harder-named zones should
    generally ask for more watts, so a weakness->type mapping built on top of
    this later isn't secretly recommending a harder session that's actually
    easier."""

    def test_anaerobic_is_the_hardest_by_peak_watts(self):
        peak = {t: wt.build(t, FTP).target_watts_high for t in wt.WORKOUT_TYPES}
        assert peak["anaerobic"] == max(peak.values())

    def test_endurance_is_the_easiest(self):
        peak = {t: wt.build(t, FTP).target_watts_high for t in wt.WORKOUT_TYPES}
        assert peak["endurance"] == min(peak.values())


class TestStepShapeValidity:
    def test_every_step_has_required_fields(self):
        for t in wt.WORKOUT_TYPES:
            for s in wt.build(t, FTP).steps:
                assert s["duration_sec"] > 0
                assert s["target_type"] in ("steady", "range", "ramp")
                assert 0 < s["target_low_pct_ftp"] <= 2.0

    def test_generated_steps_validate_as_workoutstep(self):
        """The generator's output must be accepted by the same Pydantic model
        the API enforces on hand-built workouts — no special-casing."""
        from api.main import WorkoutStep

        for t in wt.WORKOUT_TYPES:
            for s in wt.build(t, FTP).steps:
                WorkoutStep(**s)  # raises if shape is invalid
