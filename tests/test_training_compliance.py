"""Weekly distance against the team's 300km minimum.

The bug this service is built to avoid: every cached day holds a snapshot of
the SAME recent activities, so naively summing the caches counts each ride
once per cached day. That's what made "distance in june" report 3637km instead
of 1212km. These tests pin the deduplication, not just the arithmetic.
"""
from __future__ import annotations

from datetime import date

import pytest

from services import training_compliance as tc

MONDAY = date(2026, 8, 3)
WEDNESDAY = date(2026, 8, 5)
SUNDAY = date(2026, 8, 9)


@pytest.fixture
def cached(monkeypatch):
    """Install fake activity caches keyed by cache-day, mirroring the real
    store's shape: each day repeats the same recent activities."""

    def install(days: dict[str, list[dict]]):
        payloads = {d: {"items": items} for d, items in days.items()}
        monkeypatch.setattr(
            tc.local_store,
            "get_all_metric_days",
            lambda metric: payloads if metric == "activities_list_large" else {},
        )

    return install


def ride(activity_id, day, km):
    return {"activity_id": activity_id, "start_time_local": f"{day}T07:00:00", "distance_m": km * 1000}


class TestDeduplication:
    def test_repeated_snapshots_do_not_multiply(self, cached):
        one_ride = [ride(1, "2026-08-04", 100)]
        cached({"2026-08-04": one_ride, "2026-08-05": one_ride, "2026-08-06": one_ride})
        r = tc.week_distance_km(WEDNESDAY)
        assert r["distance_km"] == 100
        assert r["rides"] == 1

    def test_distinct_rides_all_count(self, cached):
        cached({"2026-08-05": [ride(1, "2026-08-03", 50), ride(2, "2026-08-04", 70)]})
        r = tc.week_distance_km(WEDNESDAY)
        assert r["distance_km"] == 120
        assert r["rides"] == 2

    def test_rides_with_no_distance_are_ignored(self, cached):
        cached({"2026-08-05": [ride(1, "2026-08-04", 50), {"activity_id": 2, "start_time_local": "2026-08-04T09:00:00"}]})
        r = tc.week_distance_km(WEDNESDAY)
        assert r["rides"] == 1


class TestWeekWindow:
    def test_week_runs_monday_to_sunday(self, cached):
        cached({})
        for d in (MONDAY, WEDNESDAY, SUNDAY):
            r = tc.week_distance_km(d)
            assert r["week_start"] == "2026-08-03"
            assert r["week_end"] == "2026-08-09"

    def test_rides_outside_the_week_are_excluded(self, cached):
        cached({"2026-08-05": [ride(1, "2026-08-02", 200), ride(2, "2026-08-04", 60), ride(3, "2026-08-10", 200)]})
        r = tc.week_distance_km(WEDNESDAY)
        assert r["distance_km"] == 60

    def test_counting_stops_at_today_not_at_sunday(self, cached):
        """Distance-so-far and days-elapsed must cover the same window, or a
        past week queried mid-week credits rides that hadn't happened yet and
        always reads on-pace."""
        cached({"2026-08-09": [ride(1, "2026-08-04", 50), ride(2, "2026-08-08", 250)]})
        midweek = tc.week_distance_km(WEDNESDAY)
        assert midweek["distance_km"] == 50
        assert midweek["counted_through"] == "2026-08-05"

        full = tc.week_distance_km(SUNDAY)
        assert full["distance_km"] == 300
        assert full["counted_through"] == "2026-08-09"


class TestPacing:
    def test_hitting_the_target_reads_met(self, cached):
        cached({"2026-08-09": [ride(1, "2026-08-04", 320)]})
        assert tc.week_distance_km(SUNDAY)["met"] is True

    def test_short_of_the_target_reads_not_met(self, cached):
        cached({"2026-08-09": [ride(1, "2026-08-04", 299)]})
        r = tc.week_distance_km(SUNDAY)
        assert r["met"] is False
        assert r["remaining_km"] == 1

    def test_remaining_never_goes_negative(self, cached):
        cached({"2026-08-09": [ride(1, "2026-08-04", 500)]})
        assert tc.week_distance_km(SUNDAY)["remaining_km"] == 0

    def test_ahead_of_the_linear_share_is_on_pace(self, cached):
        # By Wednesday (3 of 7 days) the flat share is ~128.6km.
        cached({"2026-08-05": [ride(1, "2026-08-04", 150)]})
        assert tc.week_distance_km(WEDNESDAY)["on_pace"] is True

    def test_behind_the_linear_share_is_not_on_pace(self, cached):
        cached({"2026-08-05": [ride(1, "2026-08-04", 100)]})
        assert tc.week_distance_km(WEDNESDAY)["on_pace"] is False

    def test_days_remaining_counts_down_through_the_week(self, cached):
        cached({})
        assert tc.week_distance_km(MONDAY)["days_remaining"] == 6
        assert tc.week_distance_km(WEDNESDAY)["days_remaining"] == 4
        assert tc.week_distance_km(SUNDAY)["days_remaining"] == 0

    def test_an_empty_week_is_not_on_pace_once_underway(self, cached):
        """A rider who has done nothing by Wednesday is behind, and the widget
        shouldn't reassure them otherwise."""
        cached({})
        assert tc.week_distance_km(WEDNESDAY)["on_pace"] is False
        assert tc.week_distance_km(WEDNESDAY)["distance_km"] == 0
