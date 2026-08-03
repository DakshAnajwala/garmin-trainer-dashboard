"""The declared half of the athlete profile.

This is read-only on purpose, so the tests are mostly about that being a
*decision* the code states rather than an omission — and about the one thing
that justifies the tab existing at all: every field explaining what it drives.
"""
from __future__ import annotations

from services import athlete


class TestDeclaredProfile:
    def test_exposes_every_declared_field(self):
        keys = {f["key"] for f in athlete.declared_profile()["fields"]}
        assert keys == {
            "target_wkg",
            "ftp_test_factor",
            "max_hr_bpm",
            "lthr_bpm",
            "floor_weight_kg",
            "limiter",
        }

    def test_every_field_says_what_it_drives(self):
        """The tab is read-only, so this is the thing that earns its place: no
        other surface tells you these numbers propagate anywhere."""
        for f in athlete.declared_profile()["fields"]:
            assert f["drives"].strip(), f"{f['key']} doesn't say what it drives"
            assert f["source"].strip()
            assert "label" in f and "value" in f

    def test_read_only_is_declared_with_a_reason(self):
        profile = athlete.declared_profile()
        assert profile["editable"] is False
        assert profile["why_read_only"].strip()
        assert profile["source_file"] == "config/athlete_profile.json"

    def test_floor_weight_is_described_as_a_safety_rail(self):
        """It enforces the standing 'never suggest weight loss' constraint. If
        this ever reads as a target, the framing has drifted somewhere it
        shouldn't."""
        floor = next(f for f in athlete.declared_profile()["fields"] if f["key"] == "floor_weight_kg")
        text = floor["drives"].lower()
        assert "never" in text and "lighter" in text

    def test_ftp_factor_warns_that_it_moves_cp(self):
        """The non-obvious one: it looks like a display convention, but it
        anchors the critical-power fit."""
        factor = next(f for f in athlete.declared_profile()["fields"] if f["key"] == "ftp_test_factor")
        assert "cp" in factor["drives"].lower() or "critical-power" in factor["drives"].lower()

    def test_no_secret_shaped_field_leaks_in(self):
        blob = repr(athlete.declared_profile()).lower()
        for word in ("api_key", "password", "secret", "token"):
            assert word not in blob
