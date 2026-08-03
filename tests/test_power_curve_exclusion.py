"""Power-curve aggregation + exclusion.

The acceptance criteria these encode all reduce to one property: exclusion is a
*filter over raw data*, never an edit of it. So every "restores exactly" test
compares against a value captured before the exclusion existed, rather than
against a recomputed approximation.

Store-level tests redirect _STORE_PATH to a tmp file and hard-disable Firestore
so a test run can never touch real training data or push to the cloud.
"""
from __future__ import annotations

import pytest

from services import power_curve


def steady_ride(watts, duration_sec, activity_id="A", date="2026-01-01", hz=1):
    """A ride holding `watts` for `duration_sec`, sampled every `hz` seconds."""
    return {
        "activity_id": activity_id,
        "date": date,
        "samples": [
            {"elapsed_sec": t, "power_w": watts, "cadence_rpm": 90, "hr_bpm": 150}
            for t in range(0, duration_sec, hz)
        ],
    }


def spike_ride(base_w=200, spike_w=4000, spike_at=1800, duration_sec=3600, activity_id="SPIKE"):
    """The goal's scenario: an otherwise ordinary ride carrying one absurd spike."""
    ride = steady_ride(base_w, duration_sec, activity_id=activity_id, date="2026-02-02")
    ride["samples"][spike_at]["power_w"] = spike_w
    return ride


class TestMeanMax:
    def test_steady_ride_gives_back_its_own_watts(self):
        curve = power_curve.ride_curve(steady_ride(200, 1300)["samples"])
        assert curve[60]["watts"] == pytest.approx(200, abs=0.5)
        assert curve[1200]["watts"] == pytest.approx(200, abs=0.5)

    def test_curve_is_monotonically_non_increasing(self):
        """Physically mandatory: a longer window can never average more than a
        shorter one, since the shorter one can sit inside it."""
        curve = power_curve.ride_curve(spike_ride()["samples"])
        watts = [curve[d]["watts"] for d in sorted(curve)]
        assert watts == sorted(watts, reverse=True)

    def test_spike_dominates_short_durations_only(self):
        curve = power_curve.ride_curve(spike_ride()["samples"])
        assert curve[1]["watts"] == pytest.approx(4000)
        # One second of 4000W spread over 20min barely moves the average.
        assert curve[1200]["watts"] == pytest.approx(203.2, abs=1)

    def test_long_gap_is_zero_filled_not_held(self):
        """A pause is zero watts, not a continuation of the last reading."""
        samples = [{"elapsed_sec": 0, "power_w": 300}, {"elapsed_sec": 600, "power_w": 300}]
        curve = power_curve.ride_curve(samples, durations=[60])
        # Only ~10s of held power exists; a 60s window is mostly pause.
        assert curve[60]["watts"] < 60

    def test_sampling_rate_marks_short_durations_unreliable(self):
        """Garmin returns ~3s samples; a 1s "max" from that isn't a sprint."""
        curve = power_curve.ride_curve(steady_ride(200, 600, hz=3)["samples"])
        assert curve[1]["reliable"] is False
        assert curve[60]["reliable"] is True


class TestExclusionFiltersAggregates:
    def test_excluding_spike_ride_removes_it_from_all_time_curve(self):
        rides = [spike_ride(), steady_ride(250, 3600, activity_id="GOOD")]

        before = power_curve.all_time_curve(rides)
        assert before[1]["watts"] == pytest.approx(4000)
        assert before[1]["activity_id"] == "SPIKE"

        after = power_curve.all_time_curve(rides, {"SPIKE": {"excluded": True}})
        assert after[1]["watts"] == pytest.approx(250)
        assert after[1]["activity_id"] == "GOOD"

    def test_excluding_best_ride_falls_back_to_next_best(self):
        rides = [
            steady_ride(300, 3600, activity_id="BEST"),
            steady_ride(250, 3600, activity_id="SECOND"),
            steady_ride(200, 3600, activity_id="THIRD"),
        ]
        assert power_curve.all_time_curve(rides)[600]["watts"] == pytest.approx(300, abs=0.5)

        one_out = power_curve.all_time_curve(rides, {"BEST": {"excluded": True}})
        assert one_out[600]["watts"] == pytest.approx(250, abs=0.5)
        assert one_out[600]["activity_id"] == "SECOND"

        two_out = power_curve.all_time_curve(
            rides, {"BEST": {"excluded": True}, "SECOND": {"excluded": True}}
        )
        assert two_out[600]["activity_id"] == "THIRD"

    def test_excluding_every_ride_leaves_no_curve(self):
        rides = [steady_ride(300, 3600, activity_id="ONLY")]
        assert power_curve.all_time_curve(rides, {"ONLY": {"excluded": True}}) == {}

    def test_reincluding_restores_prior_values_exactly(self):
        """No data loss: the restored curve must equal the original bit for bit,
        because exclusion never touched the samples it filtered."""
        rides = [spike_ride(), steady_ride(250, 3600, activity_id="GOOD")]

        before = power_curve.all_time_curve(rides)
        _excluded = power_curve.all_time_curve(rides, {"SPIKE": {"excluded": True}})
        restored = power_curve.all_time_curve(rides, {"SPIKE": {"excluded": False}})

        assert restored == before

    def test_exclusion_leaves_raw_samples_untouched(self):
        """Distance/duration/history must be identical either way — which holds
        trivially so long as nothing mutates the samples. Guard it anyway."""
        rides = [spike_ride()]
        snapshot = [dict(s) for s in rides[0]["samples"]]

        power_curve.all_time_curve(rides, {"SPIKE": {"excluded": True}})
        power_curve.all_time_curve(rides, {"SPIKE": {"ranges": [{"start_sec": 0, "end_sec": 500}]}})

        assert rides[0]["samples"] == snapshot


class TestSegmentExclusion:
    def test_brushed_range_is_masked_out(self):
        """Calibration can drift mid-ride, so only the bad stretch goes."""
        ride = steady_ride(200, 3600, activity_id="R")
        for s in ride["samples"][1000:1200]:
            s["power_w"] = 900  # a bad stretch

        assert power_curve.all_time_curve([ride])[60]["watts"] == pytest.approx(900, abs=1)

        masked = power_curve.all_time_curve(
            [ride], {"R": {"ranges": [{"start_sec": 1000, "end_sec": 1199}]}}
        )
        assert masked[60]["watts"] == pytest.approx(200, abs=1)

    def test_excluded_window_is_skipped_not_zero_filled(self):
        """An excluded stretch must not feed aggregates at all. Diluting it with
        zeros would still let it drag a window's average down — that's feeding."""
        ride = steady_ride(200, 600, activity_id="R")
        curve = power_curve.all_time_curve(
            [ride], {"R": {"ranges": [{"start_sec": 0, "end_sec": 99}]}}, durations=[60]
        )
        assert curve[60]["watts"] == pytest.approx(200, abs=1)

    def test_whole_ride_switch_beats_ranges_and_preserves_them(self):
        ride = steady_ride(200, 600, activity_id="R")
        rule = {"excluded": True, "ranges": [{"start_sec": 0, "end_sec": 50}]}
        assert power_curve.all_time_curve([ride], {"R": rule}) == {}
        assert rule["ranges"] == [{"start_sec": 0, "end_sec": 50}]  # not consumed


class TestFtpEstimate:
    def test_ftp_follows_the_athletes_own_convention(self):
        curve = power_curve.all_time_curve([steady_ride(200, 1300)])
        assert power_curve.estimate_ftp(curve, 0.95)["ftp_watts"] == pytest.approx(190, abs=0.5)

    def test_excluding_the_ride_drops_the_ftp_estimate(self):
        rides = [steady_ride(300, 1300, activity_id="HIGH"), steady_ride(200, 1300, activity_id="LOW")]

        before = power_curve.estimate_ftp(power_curve.all_time_curve(rides), 0.95)
        after = power_curve.estimate_ftp(
            power_curve.all_time_curve(rides, {"HIGH": {"excluded": True}}), 0.95
        )
        restored = power_curve.estimate_ftp(power_curve.all_time_curve(rides), 0.95)

        assert before["ftp_watts"] == pytest.approx(285, abs=0.5)
        assert after["ftp_watts"] == pytest.approx(190, abs=0.5)
        assert restored == before

    def test_no_full_20min_block_reports_nothing_rather_than_extrapolating(self):
        curve = power_curve.all_time_curve([steady_ride(300, 300)])
        assert power_curve.estimate_ftp(curve, 0.95) is None


class TestMonotonicRepair:
    def test_shorter_duration_lifted_to_implied_value(self):
        """Merging sources that define different durations can invent a curve
        that rises with duration; that must be repaired and labelled."""
        repaired = power_curve._enforce_monotonic({
            600: {"watts": 180.0, "source": "measured"},
            3600: {"watts": 193.0, "source": "self_reported"},
        })
        assert repaired[600]["watts"] == 193.0
        assert repaired[600]["implied_from_s"] == 3600
        assert repaired[600]["source"] == "self_reported"

    def test_already_valid_curve_is_left_alone(self):
        curve = {60: {"watts": 400.0, "source": "measured"}, 600: {"watts": 250.0, "source": "measured"}}
        assert power_curve._enforce_monotonic(curve) == curve


class TestMergedCurve:
    """Covers the wiring, not just the helpers: a mutation that dropped the
    monotonic repair from merged_curve slipped past helper-level tests."""

    @pytest.fixture
    def fake_sources(self, monkeypatch):
        def _apply(config_curve, measured):
            monkeypatch.setattr(power_curve, "POWER_CURVE_SECONDS", config_curve)
            monkeypatch.setattr(power_curve, "measured_all_time", lambda durations=None: measured)
        return _apply

    def test_measured_best_beats_self_reported(self, fake_sources):
        fake_sources({600: 244}, {600: {"watts": 281.1, "reliable": True, "activity_id": "R", "date": "2026-07-09"}})
        point = power_curve.merged_curve()[600]
        assert point["watts"] == 281.1
        assert point["source"] == "measured"
        assert point["activity_id"] == "R"

    def test_self_reported_survives_a_weaker_measurement(self, fake_sources):
        fake_sources({60: 432}, {60: {"watts": 377.4, "reliable": True}})
        assert power_curve.merged_curve()[60] == {"watts": 432.0, "source": "self_reported", "reliable": True}

    def test_unreliable_measurement_cannot_set_a_record(self, fake_sources):
        """A 1s "best" derived from 3s samples must not overwrite a real sprint."""
        fake_sources({1: 1023}, {1: {"watts": 1200.0, "reliable": False}})
        assert power_curve.merged_curve()[1]["source"] == "self_reported"

    def test_merged_result_is_monotonic(self, fake_sources):
        """The real regression: config has no 1800s, so an unrepaired merge put
        3600s=193W above 1800s=182.4W — a curve that rises with duration."""
        fake_sources({3600: 193}, {1800: {"watts": 182.4, "reliable": True}})
        merged = power_curve.merged_curve()
        assert merged[1800]["watts"] >= merged[3600]["watts"]
        assert merged[1800]["implied_from_s"] == 3600


class TestExclusionStore:
    @pytest.fixture
    def store(self, tmp_path, monkeypatch):
        from database import local_store

        monkeypatch.setattr(local_store, "_STORE_PATH", tmp_path / "store.json")
        monkeypatch.setattr(local_store.firestore_db, "available", lambda: False)
        monkeypatch.setattr(local_store.backup, "snapshot_before_write", lambda _p: None)
        return local_store

    def test_defaults_to_not_excluded(self, store):
        assert store.get_power_exclusion("123") == {"excluded": False, "reason": "", "ranges": []}

    def test_round_trips_toggle_reason_and_ranges(self, store):
        store.set_power_exclusion("123", excluded=True, reason="forgot to zero offset")
        entry = store.get_power_exclusion("123")
        assert entry["excluded"] is True
        assert entry["reason"] == "forgot to zero offset"

    def test_partial_update_leaves_other_fields_alone(self, store):
        store.set_power_exclusion("123", excluded=True, reason="drift")
        store.set_power_exclusion("123", excluded=False)
        assert store.get_power_exclusion("123")["reason"] == "drift"

    def test_ranges_survive_toggling_the_whole_ride_switch(self, store):
        ranges = [{"start_sec": 10, "end_sec": 20}]
        store.set_power_exclusion("123", ranges=ranges)
        store.set_power_exclusion("123", excluded=True)
        store.set_power_exclusion("123", excluded=False)
        assert store.get_power_exclusion("123")["ranges"] == ranges

    def test_backwards_range_is_rejected(self, store):
        store.set_power_exclusion("123", ranges=[{"start_sec": 90, "end_sec": 10}])
        assert store.get_power_exclusion("123")["ranges"] == []

    def test_empty_entry_is_dropped_to_keep_the_map_syncable(self, store):
        store.set_power_exclusion("123", excluded=True)
        store.set_power_exclusion("123", excluded=False, reason="", ranges=[])
        assert "123" not in store.get_power_exclusions()
