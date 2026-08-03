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

    def test_neuromuscular_weakness_maps_to_the_sprint_prescription(self):
        """This used to fall back to `anaerobic` and apologise for it in the
        reason string. workout_types gained a real sprint template precisely so
        the most likely weakness for this rider stopped being the one the app
        couldn't train — so the fallback must be gone, not just quieter."""
        t, reason = dp.decide_type(NEUROMUSCULAR, None, {})
        assert t == "neuromuscular"
        assert "closest match" not in reason.lower()

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


class TestSoftRowCaveats:
    """A weakness that's really a measurement gap has to be labelled as one,
    or the athlete trains a number instead of a limiter."""

    def test_vo2max_row_carries_its_non_maximal_caveat(self):
        assert "not a maximal effort" in dp.soft_row_caveat(VO2MAX_ROW)

    def test_threshold_row_carries_its_stale_ftp_caveat(self):
        assert "not a fresh maximal 20min" in dp.soft_row_caveat(THRESHOLD_ROW)

    def test_measured_rows_carry_no_caveat(self):
        assert dp.soft_row_caveat(NEUROMUSCULAR) is None
        assert dp.soft_row_caveat(ANAEROBIC_CAP) is None
        assert dp.soft_row_caveat(None) is None

    def test_the_caveat_reaches_the_decide_type_reason(self):
        _, reason = dp.decide_type(VO2MAX_ROW, None, {})
        assert "not a maximal effort" in reason


class TestStrengthFocus:
    MONDAY = date(2026, 8, 3)
    TUESDAY = date(2026, 8, 4)
    FRIDAY = date(2026, 8, 7)

    def test_each_weakness_gets_its_own_focus(self):
        focuses = {
            label: dp.suggest_strength_focus(label)["focus"]
            for label in (NEUROMUSCULAR, ANAEROBIC_CAP, VO2MAX_ROW, THRESHOLD_ROW, None)
        }
        assert focuses[NEUROMUSCULAR] == "max_strength"
        assert focuses[ANAEROBIC_CAP] == "heavy_lower"
        assert focuses[VO2MAX_ROW] == "support"
        assert focuses[THRESHOLD_ROW] == "maintenance"
        assert focuses[None] == "general"

    def test_sprint_weakness_prescribes_heavy_low_rep_work(self):
        s = dp.suggest_strength_focus(NEUROMUSCULAR)
        assert "85%" in s["detail"]
        assert "force-limited" in s["reason"]

    def test_vo2max_weakness_stays_submaximal(self):
        """VO2max is trained on the bike — the gym must not compete with it."""
        s = dp.suggest_strength_focus(VO2MAX_ROW)
        assert "85%" not in s["detail"]
        assert "submaximal" in s["detail"]

    def test_every_focus_maps_to_a_real_strength_log_type(self):
        """A planned session has to be loggable without re-picking anything."""
        valid = {"general", "lower_body", "upper_body", "core", "full_body"}
        for label in (NEUROMUSCULAR, ANAEROBIC_CAP, VO2MAX_ROW, THRESHOLD_ROW, None):
            assert dp.suggest_strength_focus(label)["log_type"] in valid

    def test_no_prescription_is_ever_framed_around_losing_weight(self):
        """Standing constraint: this athlete is adding absolute power, not
        cutting. Weight-loss framing contradicts their actual plan."""
        banned = ("lose weight", "weight loss", "leaner", "leanness", "slim", "cut weight", "drop weight")
        for label in (NEUROMUSCULAR, ANAEROBIC_CAP, VO2MAX_ROW, THRESHOLD_ROW, None):
            for cap_date in (self.TUESDAY, self.FRIDAY):
                s = dp.suggest_strength_focus(label, "TRAIN", cap_date, {})
                text = f"{s['title']} {s['detail']} {s['reason']}".lower()
                assert not any(b in text for b in banned), (label, text)


class TestStrengthLoadCap:
    TUESDAY = date(2026, 8, 4)
    WEDNESDAY = date(2026, 8, 5)
    FRIDAY = date(2026, 8, 7)

    def test_bad_readiness_drops_to_mobility_only(self):
        for verdict in ("REST", "EASY"):
            cap, why = dp.strength_load_cap(verdict, self.TUESDAY, {})
            assert cap == "mobility"
            assert verdict in why

    def test_mobility_cap_replaces_the_prescription_entirely(self):
        """There is no light version of a 4x3 @ 85% worth doing."""
        s = dp.suggest_strength_focus(NEUROMUSCULAR, "REST", self.TUESDAY, {})
        assert s["focus"] == "mobility"
        assert "85%" not in s["detail"]

    def test_a_hard_bike_day_either_side_drops_to_maintenance(self):
        for offset_day in ("2026-08-03", "2026-08-04", "2026-08-05"):
            week = {offset_day: {"session_type": "intervals", "title": "VO2max"}}
            cap, _ = dp.strength_load_cap("TRAIN", self.TUESDAY, week)
            assert cap == "maintenance", offset_day

    def test_a_hard_bike_day_two_days_away_does_not_cap(self):
        week = {"2026-08-06": {"session_type": "intervals", "title": "VO2max"}}
        cap, _ = dp.strength_load_cap("TRAIN", self.TUESDAY, week)
        assert cap == "full"

    def test_friday_caps_because_of_saturdays_team_ride(self):
        cap, why = dp.strength_load_cap("TRAIN", self.FRIDAY, {})
        assert cap == "maintenance"
        assert "team ride" in why

    def test_maintenance_keeps_the_focus_but_cuts_the_volume(self):
        full = dp.suggest_strength_focus(NEUROMUSCULAR, "TRAIN", self.TUESDAY, {})
        capped = dp.suggest_strength_focus(NEUROMUSCULAR, "TRAIN", self.FRIDAY, {})
        assert capped["focus"] == full["focus"]  # same weakness still targeted
        assert capped["duration_min"] < full["duration_min"]

    def test_readiness_beats_the_other_caps(self):
        """Most restrictive wins — a bad day must not be talked back up into
        heavy lifting by a later rule."""
        cap, _ = dp.strength_load_cap("REST", self.FRIDAY, {})
        assert cap == "mobility"


class TestComposeThreeOptions:
    MONDAY = date(2026, 8, 3)
    TUESDAY = date(2026, 8, 4)
    SATURDAY = date(2026, 8, 8)
    SUNDAY = date(2026, 8, 9)
    FTP = 219.0

    def _compose(self, target_date, verdict="TRAIN", week=None, weakest=NEUROMUSCULAR):
        return dp.compose_three_options(weakest, None, week or {}, verdict, target_date, self.FTP)

    def test_always_exactly_three(self):
        for d in (self.MONDAY, self.TUESDAY, self.SATURDAY, self.SUNDAY):
            for verdict in ("REST", "EASY", "TRAIN", "HARD", "UNKNOWN", None):
                assert len(self._compose(d, verdict)) == 3, (d, verdict)

    def test_strength_is_always_one_of_them(self):
        for d in (self.MONDAY, self.TUESDAY, self.SATURDAY, self.SUNDAY):
            kinds = [o.kind for o in self._compose(d)]
            assert "strength" in kinds, d

    def test_strength_is_additive_not_an_alternative(self):
        """It's a different modality — accepting a ride AND a gym session for
        the same day is a legitimate answer, so it must not exclude bike."""
        strength = next(o for o in self._compose(self.TUESDAY) if o.kind == "strength")
        assert "bike" not in strength.exclusive_with

    def test_bike_options_are_alternatives_to_each_other(self):
        for o in self._compose(self.TUESDAY):
            if o.kind == "bike":
                assert "bike" in o.exclusive_with

    # --- Saturday: the non-negotiable team ride ---
    def test_saturday_leads_with_the_team_ride(self):
        opts = self._compose(self.SATURDAY)
        assert opts[0].session_type == "team_ride"

    def test_saturday_never_offers_to_replace_the_team_ride(self):
        """Hard rule from the athlete profile: the coach may advise on managing
        the team ride, never on skipping or swapping it."""
        banned = ("skip", "instead of the team", "replace", "swap out", "cancel")
        for o in self._compose(self.SATURDAY, verdict="REST"):
            text = f"{o.title} {o.detail} {o.reason}".lower()
            assert not any(b in text for b in banned), text

    def test_saturday_offers_no_second_bike_session(self):
        bike = [o for o in self._compose(self.SATURDAY) if o.kind == "bike"]
        assert len(bike) == 1

    # --- Monday: the scheduled rest day ---
    def test_monday_leads_with_rest(self):
        assert self._compose(self.MONDAY)[0].kind == "rest"

    def test_monday_still_offers_the_weakness_session_as_a_move(self):
        opts = self._compose(self.MONDAY)
        bike = next(o for o in opts if o.kind == "bike")
        assert "moving your rest day" in bike.reason

    # --- readiness gate ---
    def test_rest_verdict_leads_with_rest(self):
        assert self._compose(self.TUESDAY, "REST")[0].kind == "rest"

    def test_easy_verdict_leads_with_a_recovery_spin(self):
        first = self._compose(self.TUESDAY, "EASY")[0]
        assert first.title == "Recovery spin"
        assert first.duration_min <= 45

    def test_a_bad_day_parks_the_hard_session_rather_than_hiding_it(self):
        opts = self._compose(self.TUESDAY, "REST")
        parked = next(o for o in opts if "parked, not cancelled" in o.reason)
        assert parked.workout_type == "neuromuscular"

    def test_bad_readiness_downgrades_the_strength_option_too(self):
        strength = next(o for o in self._compose(self.TUESDAY, "REST") if o.kind == "strength")
        assert strength.strength_focus == "mobility"

    # --- normal days ---
    def test_normal_day_leads_with_the_weakness_targeted_session(self):
        opts = self._compose(self.TUESDAY)
        assert opts[0].workout_type == "neuromuscular"

    def test_the_two_bike_options_are_never_the_same_type(self):
        """A 'choice' between two identical sessions isn't a choice."""
        for weakest in (NEUROMUSCULAR, ANAEROBIC_CAP, VO2MAX_ROW, THRESHOLD_ROW, None):
            types = [o.workout_type for o in self._compose(self.TUESDAY, weakest=weakest)
                     if o.kind == "bike" and o.workout_type]
            assert len(types) == len(set(types)), weakest

    def test_sunday_offers_the_profiles_long_ride(self):
        opts = self._compose(self.SUNDAY)
        long_ride = next(o for o in opts if o.session_type == "long_ride")
        assert "45kph" in long_ride.detail

    def test_a_loaded_week_offers_less_not_more(self):
        """Once the week has a hard session, decide_type downgrades the primary
        to endurance — the contrast must not quietly re-add a hard one."""
        week = {"2026-08-06": {"session_type": "intervals", "title": "VO2max"}}
        opts = self._compose(self.TUESDAY, week=week)
        assert all(o.workout_type not in dp._HARD_WORKOUT_TYPES for o in opts if o.kind == "bike")

    # --- payload integrity ---
    def test_structured_options_carry_steps_that_add_up(self):
        for o in self._compose(self.TUESDAY):
            if o.steps:
                assert round(sum(s["duration_sec"] for s in o.steps) / 60) == o.duration_min

    def test_every_option_explains_itself(self):
        """Standing rule: no recommendation without a visible why."""
        for d in (self.MONDAY, self.TUESDAY, self.SATURDAY, self.SUNDAY):
            for o in self._compose(d):
                assert o.reason and o.reason.strip(), (d, o.title)

    def test_works_with_no_ftp_at_all(self):
        """New user, nothing logged — must still return three usable options."""
        opts = dp.compose_three_options(None, None, {}, "TRAIN", self.TUESDAY, None)
        assert len(opts) == 3
        assert all(o.title for o in opts)
