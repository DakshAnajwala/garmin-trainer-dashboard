"""The AI enrichment layer on top of the deterministic day-planner.

The one property that matters more than any other: this must NEVER be able to
break the feature. Every failure mode — no key, wrong key, network error,
garbage response — has to fall back to the deterministic type/reason
untouched. These tests exercise every one of those paths without making a
real network call.
"""
from __future__ import annotations

from unittest.mock import patch

from config.settings import Settings

import pytest

from services import ai_day_planner as aidp
from services.workout_types import WORKOUT_TYPES


class TestParseResponse:
    def test_clean_response_parses(self):
        result = aidp._parse_response("vo2max\nYour top-end power is your biggest opportunity right now.")
        assert result == ("vo2max", "Your top-end power is your biggest opportunity right now.")

    def test_type_prefix_label_is_stripped(self):
        result = aidp._parse_response("Type: overgearing\nBuild some torque today.")
        assert result[0] == "overgearing"

    def test_case_insensitive(self):
        result = aidp._parse_response("VO2Max\nreason")
        assert result[0] == "vo2max"

    def test_type_outside_the_catalog_is_rejected_not_guessed(self):
        """A model returning 'sprints' or 'recovery' (not in WORKOUT_TYPES)
        must be treated as a parse failure, never silently accepted."""
        assert aidp._parse_response("sprints\nsome reason") is None

    def test_empty_response_is_a_parse_failure(self):
        assert aidp._parse_response("") is None
        assert aidp._parse_response("   \n  ") is None

    def test_reason_only_no_type_line_fails(self):
        assert aidp._parse_response("Just a sentence with no type keyword at all.") is None

    def test_missing_rationale_still_parses_with_none_reason(self):
        result = aidp._parse_response("endurance")
        assert result == ("endurance", None)

    def test_every_catalog_type_is_a_valid_first_line(self):
        for t in WORKOUT_TYPES:
            assert aidp._parse_response(f"{t}\nreason") == (t, "reason")


class TestEnrichDegradesGracefully:
    """Every branch must return a fully-usable {type, reason, ai_used,
    ai_unavailable_message} dict — never raise, never return a partial result."""

    def test_no_key_configured_falls_back_immediately(self, monkeypatch):
        monkeypatch.setattr(Settings, "anthropic_api_key", property(lambda self: ""))
        r = aidp.enrich("endurance", "no signal yet", "empty week", None, None)
        assert r["ai_used"] is False
        assert r["type"] == "endurance"
        assert r["reason"] == "no signal yet"
        assert aidp.UNAVAILABLE_MESSAGE in r["ai_unavailable_message"]

    def test_placeholder_key_falls_back_immediately(self, monkeypatch):
        monkeypatch.setattr(Settings, "anthropic_api_key", property(lambda self: "sk-ant-placeholder"))
        r = aidp.enrich("vo2max", "reason", "week", None, None)
        assert r["ai_used"] is False
        assert r["type"] == "vo2max"

    def test_authentication_error_degrades_with_the_translated_message(self, monkeypatch):
        monkeypatch.setattr(Settings, "anthropic_api_key", property(lambda self: "sk-wrong-value"))
        with patch.object(aidp.claude_analyzer, "_send", side_effect=RuntimeError("Anthropic rejected the stored API key.")):
            r = aidp.enrich("lactate_threshold", "weakness reason", "week", "Functional Threshold", None)
        assert r["ai_used"] is False
        assert r["type"] == "lactate_threshold"
        assert r["reason"] == "weakness reason"
        assert "rejected" in r["ai_unavailable_message"]

    def test_unexpected_exception_degrades_without_propagating(self, monkeypatch):
        """A network timeout or any other surprise must not bubble up and
        break the coach-plan endpoint — the deterministic pick always wins."""
        monkeypatch.setattr(Settings, "anthropic_api_key", property(lambda self: "sk-real-looking-key"))
        with patch.object(aidp.claude_analyzer, "_send", side_effect=ConnectionError("timed out")):
            r = aidp.enrich("anaerobic", "reason", "week", None, None)
        assert r["ai_used"] is False
        assert r["type"] == "anaerobic"

    def test_garbage_ai_response_falls_back(self, monkeypatch):
        monkeypatch.setattr(Settings, "anthropic_api_key", property(lambda self: "sk-real-looking-key"))
        with patch.object(aidp.claude_analyzer, "_send", return_value="I think you should rest today!"):
            r = aidp.enrich("endurance", "default reason", "week", None, None)
        assert r["ai_used"] is False
        assert r["type"] == "endurance"

    def test_valid_ai_response_is_used(self, monkeypatch):
        monkeypatch.setattr(Settings, "anthropic_api_key", property(lambda self: "sk-real-looking-key"))
        with patch.object(aidp.claude_analyzer, "_send", return_value="vo2max\nYour aerobic ceiling is the limiter right now."):
            r = aidp.enrich("endurance", "default reason", "week", "VO2max", None)
        assert r["ai_used"] is True
        assert r["type"] == "vo2max"
        assert "aerobic ceiling" in r["reason"]
        assert r["ai_unavailable_message"] is None


class TestExplicitTypeIsNeverOverridden:
    """When the athlete asked for a specific type, the AI's job is to explain
    it — not to quietly substitute a different one."""

    def test_ai_cannot_override_an_explicit_request(self, monkeypatch):
        monkeypatch.setattr(Settings, "anthropic_api_key", property(lambda self: "sk-real-looking-key"))
        # Even if the model ignores instructions and returns a different type,
        # the requested type must win.
        with patch.object(aidp.claude_analyzer, "_send", return_value="anaerobic\nsome reason"):
            r = aidp.enrich("overgearing", "det reason", "week", None, requested_type="overgearing")
        assert r["type"] == "overgearing"

    def test_ai_rationale_still_applies_to_an_explicit_request(self, monkeypatch):
        monkeypatch.setattr(Settings, "anthropic_api_key", property(lambda self: "sk-real-looking-key"))
        with patch.object(aidp.claude_analyzer, "_send", return_value="overgearing\nBuild torque for the climb."):
            r = aidp.enrich("overgearing", "det reason", "week", None, requested_type="overgearing")
        assert r["ai_used"] is True
        assert "torque" in r["reason"]
