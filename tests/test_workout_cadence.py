"""Cadence on WorkoutStep — the schema addition overgearing work needs.

Overgearing is defined BY its cadence (same %FTP as threshold, just 40-60rpm),
so the two properties that matter: cadence is optional everywhere (no existing
workout breaks), and when present it survives into the .ZWO export, which is
the one place this data leaves the app.
"""
from __future__ import annotations

from services import workout_export


def steady(pct_ftp, duration=300, cadence_low=None, cadence_high=None):
    step = {"duration_sec": duration, "target_type": "steady", "target_low_pct_ftp": pct_ftp}
    if cadence_low is not None or cadence_high is not None:
        step["cadence_low_rpm"] = cadence_low
        step["cadence_high_rpm"] = cadence_high
    return step


class TestWorkoutStepModel:
    def test_cadence_defaults_to_none(self):
        from api.main import WorkoutStep

        s = WorkoutStep(duration_sec=60, target_type="steady", target_low_pct_ftp=0.9)
        assert s.cadence_low_rpm is None
        assert s.cadence_high_rpm is None

    def test_cadence_round_trips(self):
        from api.main import WorkoutStep

        s = WorkoutStep(duration_sec=60, target_type="steady", target_low_pct_ftp=0.97, cadence_low_rpm=45, cadence_high_rpm=55)
        assert (s.cadence_low_rpm, s.cadence_high_rpm) == (45, 55)

    def test_planned_workout_model_accepts_cadence_steps(self):
        from api.main import PlannedWorkoutModel, WorkoutStep

        m = PlannedWorkoutModel(
            title="Overgearing",
            steps=[WorkoutStep(duration_sec=600, target_type="steady", target_low_pct_ftp=0.97, cadence_low_rpm=50, cadence_high_rpm=55)],
        )
        assert m.steps[0].cadence_low_rpm == 50


class TestZwoExportCadence:
    def test_step_without_cadence_is_unchanged(self):
        """An ordinary interval must export byte-identical to before this
        feature — no fabricated Cadence attribute on steps that never asked for one."""
        xml = workout_export.to_zwo({"name": "t", "steps": [steady(1.06)]})
        assert "Cadence" not in xml

    def test_step_with_cadence_gets_the_attribute(self):
        xml = workout_export.to_zwo({"name": "t", "steps": [steady(0.97, cadence_low=50, cadence_high=60)]})
        assert 'Cadence="55"' in xml  # midpoint of 50-60

    def test_single_sided_cadence_uses_that_value(self):
        xml = workout_export.to_zwo({"name": "t", "steps": [steady(0.97, cadence_low=50, cadence_high=None)]})
        assert 'Cadence="50"' in xml

    def test_mixed_workout_only_tags_the_cadence_steps(self):
        xml = workout_export.to_zwo({
            "name": "t",
            "steps": [steady(0.55), steady(0.97, cadence_low=50, cadence_high=55), steady(0.55)],
        })
        assert xml.count("Cadence=") == 1

    def test_ramp_step_can_also_carry_cadence(self):
        ramp = {"duration_sec": 300, "target_type": "ramp", "target_low_pct_ftp": 0.5, "target_high_pct_ftp": 0.75,
                "cadence_low_rpm": 80, "cadence_high_rpm": 90}
        xml = workout_export.to_zwo({"name": "t", "steps": [ramp]})
        assert "<Ramp" in xml and 'Cadence="85"' in xml
