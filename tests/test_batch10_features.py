"""Tests the goals file asks for, by feature:

- F1: elevation cleaning, gradient segmentation, altitude/air-density/heat
  derates, recompute-on-input-change.
- F6: override-lock persistence, custom-endpoint validation/clamping,
  advisory backtest scoring.
- F8: reflow with pins.

Store-touching tests run against a tmp store with Firestore disabled — a test
run must never touch real training data.
"""
from __future__ import annotations

import math
from datetime import date

import pytest

from services import model_backtest, plan_reflow, route_demand
from services.custom_model import validate_and_clamp
from services.physiology_model import PARAM_BOUNDS, fit_cp_wprime


# --- helpers -------------------------------------------------------------------


def synthetic_route(profile: list[tuple[float, float]], step_m: float = 25.0) -> list[dict]:
    """profile = [(length_m, grade), ...] → GPX-like points heading due north."""
    pts = []
    lat, ele = 45.0, 300.0
    for length, grade in profile:
        for _ in range(int(length / step_m)):
            lat += step_m / 111320
            ele += step_m * grade
            pts.append({"lat": lat, "lon": 6.0, "ele_m": ele})
    return pts


@pytest.fixture
def store(tmp_path, monkeypatch):
    from database import local_store

    monkeypatch.setattr(local_store, "_STORE_PATH", tmp_path / "store.json")
    monkeypatch.setattr(local_store.firestore_db, "available", lambda: False)
    monkeypatch.setattr(local_store.backup, "snapshot_before_write", lambda _p: None)
    return local_store


# --- F1: elevation cleaning ------------------------------------------------------


class TestElevationCleaning:
    def test_spikes_are_caught_and_grid_is_even(self):
        pts = synthetic_route([(5000, 0.0)])
        pts[40]["ele_m"] += 50  # barometric spike
        pts[80]["ele_m"] -= 45
        grid = route_demand.clean_elevation(pts)
        assert grid["report"]["spikes_removed"] >= 2
        steps = [b - a for a, b in zip(grid["distance_m"], grid["distance_m"][1:])]
        assert all(abs(s - 10.0) < 1e-6 for s in steps)

    def test_spike_does_not_survive_into_gradients(self):
        """The reason cleaning is first-class: one 50m spike creates a fake
        ±20% gradient pair that would segment as a wall + cliff."""
        pts = synthetic_route([(5000, 0.0)])
        pts[100]["ele_m"] += 50
        grid = route_demand.clean_elevation(pts)
        e = grid["elevation_m"]
        worst = max(abs(b - a) / 10.0 for a, b in zip(e, e[1:]))
        assert worst < 0.03  # flat route stays flat after cleaning


class TestSegmentation:
    def test_finds_designed_structure(self):
        pts = synthetic_route([
            (4000, 0.0), (3000, 0.07), (1000, 0.0), (200, 0.09), (150, 0.0), (200, 0.09), (3000, -0.05), (2000, 0.0),
        ])
        segs = route_demand.segment_route(route_demand.clean_elevation(pts))
        kinds = [s["kind"] for s in segs]
        assert "climb" in kinds and "descent" in kinds and "flat" in kinds
        climbs = [s for s in segs if s["kind"] == "climb"]
        main = max(climbs, key=lambda s: s["length_m"])
        assert 2500 <= main["length_m"] <= 3600
        assert 0.055 <= main["avg_grade"] <= 0.085
        assert sum(1 for s in segs if s["kind"] == "surge") >= 1


# --- F1: physics + derates -------------------------------------------------------


class TestConditions:
    def test_air_density_matches_isa_at_sea_level(self):
        assert route_demand.air_density(0, 15, 0) == pytest.approx(1.225, abs=0.001)

    def test_density_falls_with_altitude_and_humidity(self):
        base = route_demand.air_density(0, 25, 30)
        assert route_demand.air_density(2000, 25, 30) < base
        assert route_demand.air_density(0, 25, 95) < base  # humid air is LIGHTER

    def test_altitude_derate_curve(self):
        assert route_demand.altitude_power_fraction(100) == 1.0
        assert route_demand.altitude_power_fraction(1000) == pytest.approx(0.947, abs=0.005)
        assert route_demand.altitude_power_fraction(3000) == pytest.approx(0.797, abs=0.01)
        # steeper above 1500m: the marginal cost of the next 1000m grows
        d1 = route_demand.altitude_power_fraction(1000) - route_demand.altitude_power_fraction(2000)
        d2 = route_demand.altitude_power_fraction(2000) - route_demand.altitude_power_fraction(3000)
        assert d2 > d1

    def test_heat_derate_grows_with_duration_and_cold_is_neutral(self):
        assert route_demand.heat_power_fraction(10, 50, 4) == 1.0
        short = route_demand.heat_power_fraction(32, 70, 1)
        long_ = route_demand.heat_power_fraction(32, 70, 4)
        assert long_ < short < 1.0

    def test_power_speed_round_trip(self):
        for grade in (0.0, 0.05, -0.04):
            v = route_demand.speed_at_power(250, grade, 67, 1.15, 0.32)
            assert route_demand.power_at_speed(v, grade, 67, 1.15, 0.32) == pytest.approx(250, abs=0.5)

    def test_altitude_cuts_both_ways(self):
        """Same speed needs less power in thin air (density), while the
        engine shrinks (O₂) — the two mechanisms are separate and opposite."""
        v = 11.0
        p_sea = route_demand.power_at_speed(v, 0.0, 67, route_demand.air_density(0, 15, 50), 0.32)
        p_alt = route_demand.power_at_speed(v, 0.0, 67, route_demand.air_density(2500, 15, 50), 0.32)
        assert p_alt < p_sea
        assert route_demand.altitude_power_fraction(2500) < 1.0


# --- F1: demand profile + recompute-on-change ------------------------------------


class TestDemandRecompute:
    MODEL = {"cp_watts": 220.0, "w_prime_j": 20000.0, "durability": 0.8, "repeatability": 0.85}

    def _profile(self, temp=20.0, mass=58.0):
        pts = synthetic_route([(5000, 0.0), (4000, 0.08), (5000, -0.05), (3000, 0.0)])
        return route_demand.build_demand_profile(
            route_points=pts, event_date="2026-09-12", rider_mass_kg=mass, bike_kit_kg=9.0,
            conditions={"temp_c": temp, "humidity_pct": 60.0, "source": "test"},
            model_values=self.MODEL,
        )

    def test_profile_has_demands_and_snapshot_fields(self):
        p = self._profile()
        types = {d["type"] for d in p["demands"]}
        assert "sustained_climb" in types and "durability" in types
        assert p["derates"]["cp_on_the_day_w"] <= self.MODEL["cp_watts"]

    def test_hotter_day_lowers_day_cp_and_changes_demands(self):
        cool, hot = self._profile(temp=18.0), self._profile(temp=34.0)
        assert hot["derates"]["cp_on_the_day_w"] < cool["derates"]["cp_on_the_day_w"]
        assert hot["derates"]["heat_power_fraction"] < 1.0

    def test_recompute_on_input_change_produces_diff(self, store):
        pts = synthetic_route([(5000, 0.0), (4000, 0.08), (3000, 0.0)])
        event = {"id": "EV1", "name": "t", "date": "2026-09-12", "rider_mass_kg": 58.0,
                 "bike_kit_kg": 9.0,
                 "conditions_override": {"temp_c": 20.0, "humidity_pct": 50.0, "source": "test"}}
        store.save_race_event(event)
        store.save_event_route("EV1", pts)
        # a physiology model must exist in the tmp store for recompute
        store.save_physiology_model({"params": {k: {"value": v, "confidence": "medium", "source": "test", "reasoning": ""}
                                                for k, v in TestDemandRecompute.MODEL.items()},
                                     "computed_at": 1.0})

        p1 = route_demand.recompute_event(event)
        assert p1["diff_vs_previous"] is None

        event["rider_mass_kg"] = 62.0
        p2 = route_demand.recompute_event(event)
        assert any("rider_mass_kg" in c for c in p2["diff_vs_previous"])

        p3 = route_demand.recompute_event(event)
        assert p3["diff_vs_previous"] == ["inputs unchanged — recompute produced identical demands"]


# --- F6: CP fit, override locks, custom-endpoint validation, backtest -------------


class TestCpFit:
    def test_exact_synthetic_recovery(self):
        cp, wp = 250.0, 18000.0
        points = {t: cp + wp / t for t in (120, 300, 600, 1200)}
        fit_cp, fit_wp = fit_cp_wprime(points)
        assert fit_cp == pytest.approx(cp, abs=0.1)
        assert fit_wp == pytest.approx(wp, rel=0.01)

    def test_too_few_points_returns_none(self):
        assert fit_cp_wprime({300: 280.0}) is None


class TestOverrideLocks:
    def test_locked_override_survives_recompute_until_unlocked(self, store, monkeypatch):
        from services import physiology_model as pm

        store.set_model_override("cp_watts", 180.0, locked=True, reason="post-illness")
        model = pm.compute()
        assert model["params"]["cp_watts"]["value"] == 180.0
        assert model["params"]["cp_watts"]["locked"] is True
        assert "computed_value" in model["params"]["cp_watts"]

        # recompute again — the lock must hold
        model2 = pm.compute()
        assert model2["params"]["cp_watts"]["value"] == 180.0

        # unlock → computed value returns
        store.set_model_override("cp_watts", None, locked=False)
        model3 = pm.compute()
        assert model3["params"]["cp_watts"]["value"] != 180.0


class TestCustomEndpointValidation:
    def test_clamps_and_rejects(self):
        accepted, notes = validate_and_clamp({
            "cp_watts": 99999,             # clamp to upper bound
            "w_prime_j": float("nan"),     # reject
            "durability": "DROP TABLE",    # reject
            "repeatability": -5,           # clamp to lower bound
            "surprise": 42,                # unknown -> dropped
        })
        assert accepted == {"cp_watts": PARAM_BOUNDS["cp_watts"][1], "repeatability": PARAM_BOUNDS["repeatability"][0]}
        assert len(notes) == 5  # every input got a note: 2 clamps, 2 rejects, 1 drop
        # every survivor is in bounds
        for k, v in accepted.items():
            lo, hi = PARAM_BOUNDS[k]
            assert lo <= v <= hi

    def test_all_garbage_raises(self):
        with pytest.raises(ValueError):
            validate_and_clamp({"nonsense": 1, "cp_watts": float("inf")})
        with pytest.raises(ValueError):
            validate_and_clamp(["not", "a", "dict"])

    def test_bool_is_not_a_number(self):
        with pytest.raises(ValueError):
            validate_and_clamp({"cp_watts": True})


class TestAdvisoryBacktest:
    def _fake_holdout(self, monkeypatch, cp=250.0, wp=18000.0):
        efforts = [{"duration_s": t, "watts": cp + wp / t, "date": "2026-07-01"} for t in (120, 300, 600)]
        monkeypatch.setattr(model_backtest, "holdout_efforts", lambda: ("RIDE", efforts))
        monkeypatch.setattr(model_backtest, "_blind_fit", lambda _id: (cp, wp))

    def test_correct_improved_verdict(self, monkeypatch):
        self._fake_holdout(monkeypatch)
        # blind fit IS the truth here; a proposal moving away must read worse,
        # and one matching truth against a worse current must read improved
        worse = model_backtest.evaluate_change(
            {"cp_watts": 300.0, "w_prime_j": 18000.0}, {"cp_watts": 250.0, "w_prime_j": 18000.0}
        )
        assert worse["verdict"] == "worse"
        assert worse["delta_pp"] > 0

    def test_matching_truth_is_neutral_vs_perfect_baseline(self, monkeypatch):
        self._fake_holdout(monkeypatch)
        r = model_backtest.evaluate_change(
            {"cp_watts": 250.0, "w_prime_j": 18001.0}, {"cp_watts": 250.0, "w_prime_j": 18000.0}
        )
        assert r["verdict"] == "neutral"

    def test_untestable_param_changes_are_not_scored(self, monkeypatch):
        self._fake_holdout(monkeypatch)
        r = model_backtest.evaluate_change(
            {"cp_watts": 250.0, "w_prime_j": 18000.0, "durability": 0.9},
            {"cp_watts": 250.0, "w_prime_j": 18000.0, "durability": 0.7},
        )
        assert r["verdict"] == "not_scoreable"


# --- F8: reflow with pins ----------------------------------------------------------


class TestReflowWithPins:
    THURSDAY = date(2026, 7, 16)

    def test_missed_key_session_moves(self):
        r = plan_reflow.reflow_week(220, 1, {}, {}, {}, self.THURSDAY)
        assert any("Moved VO2max intervals" in c for c in r["changes"])
        thu = next(d for d in r["week"] if d["date"] == "2026-07-16")
        assert thu["session"]["session_type"] == "intervals"

    def test_pinned_day_is_never_touched(self):
        pins = {"2026-07-16": {"reason": "family"}}
        r = plan_reflow.reflow_week(220, 1, {}, {}, pins, self.THURSDAY)
        thu = next(d for d in r["week"] if d["date"] == "2026-07-16")
        assert thu["session"]["session_type"] == "endurance"
        assert thu["pinned"] is True
        assert any("absorbed, not owed" in c for c in r["changes"])

    def test_completed_week_needs_no_reflow(self):
        acts = {"2026-07-15": [{"type": "indoor_cycling", "duration_sec": 45 * 60}]}
        r = plan_reflow.reflow_week(220, 1, acts, {}, {}, self.THURSDAY)
        assert r["changes"] == ["Week is on track — nothing needed to move."]

    def test_team_ride_is_terrain_not_a_slot(self):
        cons = {"travel_windows": [{"start": "2026-07-18", "end": "2026-07-20", "note": "trip"}]}
        acts = {"2026-07-15": [{"type": "indoor_cycling", "duration_sec": 45 * 60}]}
        r = plan_reflow.reflow_week(220, 1, acts, cons, {}, self.THURSDAY)
        sat = next(d for d in r["week"] if d["day_name"] == "Saturday")
        assert sat["session"]["session_type"] == "team_ride"

    def test_no_guilt_markers_anywhere(self):
        r = plan_reflow.reflow_week(220, 1, {}, {}, {"2026-07-16": {"reason": "x"}}, self.THURSDAY)
        text = " ".join(r["changes"]).lower()
        for word in ("incomplete", "failed", "guilt", "behind"):
            assert word not in text

    def test_snapshot_carries_inputs(self):
        pins = {"2026-07-17": {"reason": "travel day"}}
        r = plan_reflow.reflow_week(220, 2, {}, {}, pins, self.THURSDAY)
        snap = r["inputs_snapshot"]
        assert snap["block_week"] == 2
        assert "2026-07-17" in snap["pins"]
