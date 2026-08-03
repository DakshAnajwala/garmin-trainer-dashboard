"""Dated planned workouts + the generate-week materializer.

The two properties that matter: the calendar is empty until you generate
(otherwise it's the old fake repeating template again), and generate never
destroys a day you've edited (otherwise regenerating silently wipes your work).
"""
from __future__ import annotations

from datetime import date

import pytest

from services import plan_generator


@pytest.fixture
def store(tmp_path, monkeypatch):
    from database import local_store

    monkeypatch.setattr(local_store, "_STORE_PATH", tmp_path / "store.json")
    monkeypatch.setattr(local_store.firestore_db, "available", lambda: False)
    monkeypatch.setattr(local_store.backup, "snapshot_before_write", lambda _p: None)
    return local_store


class TestGenerator:
    VIEW = date(2026, 7, 21)  # a Tuesday

    def test_generate_fills_the_whole_week(self):
        r = plan_generator.generate_week(self.VIEW, 220.0, 1, existing_dates=set())
        assert r["week_start"] == "2026-07-20"  # Monday
        assert r["week_end"] == "2026-07-26"  # Sunday
        assert len(r["created"]) == 7
        assert not r["skipped"]

    def test_intervals_day_carries_structured_steps(self):
        """'Open in Builder' needs something real to edit — the Wednesday
        intervals session must come with its step structure, not a bare title."""
        r = plan_generator.generate_week(self.VIEW, 220.0, 1, existing_dates=set())
        weds = r["created"]["2026-07-22"]
        assert weds["session_type"] == "intervals"
        assert len(weds["steps"]) > 0

    def test_easy_days_have_no_fake_steps(self):
        r = plan_generator.generate_week(self.VIEW, 220.0, 1, existing_dates=set())
        assert r["created"]["2026-07-20"]["steps"] == []  # rest day

    def test_generate_is_non_destructive(self):
        """The core promise: regenerating skips days you've already planned."""
        existing = {"2026-07-22"}  # you edited Wednesday
        r = plan_generator.generate_week(self.VIEW, 220.0, 1, existing_dates=existing)
        assert "2026-07-22" not in r["created"]
        assert "2026-07-22" in r["skipped"]
        assert len(r["created"]) == 6

    def test_fully_planned_week_creates_nothing(self):
        week = {(date(2026, 7, 20) + __import__("datetime").timedelta(days=i)).isoformat() for i in range(7)}
        r = plan_generator.generate_week(self.VIEW, 220.0, 1, existing_dates=week)
        assert r["created"] == {}
        assert len(r["skipped"]) == 7

    def test_every_generated_session_is_tagged_generated(self):
        r = plan_generator.generate_week(self.VIEW, 220.0, 1, existing_dates=set())
        assert all(w["source"] == "generated" for w in r["created"].values())

    def test_generator_is_pure_touches_no_store(self, store):
        """The materializer must not write on its own — the endpoint decides
        what to persist. Keeps it trivially testable and surprise-free."""
        plan_generator.generate_week(self.VIEW, 220.0, 1, existing_dates=set())
        assert store.get_planned_workouts("2026-07-20", "2026-07-26") == {}


class TestPlannedStore:
    def test_calendar_range_is_empty_until_something_is_planned(self, store):
        assert store.get_planned_workouts("2026-07-20", "2026-07-26") == {}

    def test_save_and_read_a_day(self, store):
        store.save_planned_workout("2026-07-22", {"session_type": "intervals", "title": "VO2max"})
        got = store.get_planned_workout("2026-07-22")
        assert got["title"] == "VO2max"
        assert got["date"] == "2026-07-22"  # stamped even if caller omits it

    def test_range_only_returns_days_in_range(self, store):
        store.save_planned_workout("2026-07-22", {"title": "in"})
        store.save_planned_workout("2026-08-01", {"title": "out"})
        got = store.get_planned_workouts("2026-07-20", "2026-07-26")
        assert set(got) == {"2026-07-22"}

    def test_delete_is_undoable(self, store):
        store.save_planned_workout("2026-07-22", {"title": "oops"})
        store.delete_planned_workout("2026-07-22")
        assert store.get_planned_workout("2026-07-22") is None
        undo = store.list_undo_log()
        assert any(e["collection"] == "planned_workouts" for e in undo)

    def test_delete_missing_day_is_a_noop(self, store):
        assert store.delete_planned_workout("2026-07-22") is None

    def test_editing_a_day_replaces_it(self, store):
        store.save_planned_workout("2026-07-22", {"title": "first", "source": "generated"})
        store.save_planned_workout("2026-07-22", {"title": "second", "source": "custom"})
        got = store.get_planned_workout("2026-07-22")
        assert got["title"] == "second"
        assert got["source"] == "custom"

    def test_planned_workouts_syncs(self, store):
        assert "planned_workouts" in store._SYNCED_KEYS
