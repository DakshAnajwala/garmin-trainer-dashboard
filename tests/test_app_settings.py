"""Settings — mostly about not leaking secrets.

The contract: a secret's value never leaves the encrypted store. Everything the
Settings tab shows is *about* secrets (configured or not, what they power, what
breaks) and never a value.

The leak test uses a canary rather than the real stored secrets, for two
reasons: a test must not depend on what happens to be in the developer's
keychain, and a real secret can produce a false positive when its stored value
is short or coincidental — which is exactly what happened here. The first run of
this check flagged ANTHROPIC_API_KEY as leaking, and the "leak" turned out to be
that the stored key was literally the intervals.icu athlete ID (7 chars),
appearing legitimately in the payload's intervals section. Wrong value in the
slot, not a leak — but worth catching, so the canary keeps the assertion honest.
"""
from __future__ import annotations

import pytest

from services import app_settings

CANARY = "sk-ant-canary-DO-NOT-LEAK-abc123xyz"


@pytest.fixture
def isolated_secrets(tmp_path, monkeypatch):
    """Point the encrypted store at a temp dir so tests never touch real keys."""
    from config import secrets

    monkeypatch.setattr(secrets, "_KEY_DIR", tmp_path / "keys")
    monkeypatch.setattr(secrets, "_PRIVATE_KEY_PATH", tmp_path / "keys" / "private_key.pem")
    monkeypatch.setattr(secrets, "_PUBLIC_KEY_PATH", tmp_path / "keys" / "public_key.pem")
    monkeypatch.setattr(secrets, "_SECRETS_PATH", tmp_path / "secrets.enc.json")
    return secrets


class TestSecretsNeverLeak:
    def test_status_reports_existence_not_values(self, isolated_secrets):
        app_settings.set_secret("ANTHROPIC_API_KEY", CANARY)
        status = app_settings.secrets_status()
        blob = repr(status)
        assert CANARY not in blob
        entry = next(s for s in status if s["name"] == "ANTHROPIC_API_KEY")
        assert entry["configured"] is True
        assert "value" not in entry and "key" not in entry

    def test_set_returns_no_value(self, isolated_secrets):
        result = app_settings.set_secret("ANTHROPIC_API_KEY", CANARY)
        assert CANARY not in repr(result)
        assert result == {"name": "ANTHROPIC_API_KEY", "configured": True}

    def test_value_round_trips_through_the_encrypted_store(self, isolated_secrets):
        """It must still actually work — a cache that never stores anything
        would pass every leak test."""
        app_settings.set_secret("INTERVALS_API_KEY", CANARY)
        assert isolated_secrets.decrypt("INTERVALS_API_KEY") == CANARY

    def test_ciphertext_on_disk_is_not_the_plaintext(self, isolated_secrets):
        app_settings.set_secret("ANTHROPIC_API_KEY", CANARY)
        assert CANARY not in isolated_secrets._SECRETS_PATH.read_text()


class TestWriteAllowlist:
    def test_garmin_credentials_are_not_settable_from_the_app(self, isolated_secrets):
        """Accepting a third-party account password through a web form is more
        surface than accepting an API token — deliberately CLI-only."""
        for name in ("GARMIN_EMAIL", "GARMIN_PASSWORD"):
            with pytest.raises(ValueError, match="set_secrets"):
                app_settings.set_secret(name, "hunter2")
            assert not isolated_secrets.has(name)

    def test_api_tokens_are_settable(self, isolated_secrets):
        for name in ("ANTHROPIC_API_KEY", "INTERVALS_API_KEY"):
            app_settings.set_secret(name, CANARY)
            assert isolated_secrets.has(name)

    def test_unknown_secret_is_rejected(self, isolated_secrets):
        with pytest.raises(ValueError, match="Unknown"):
            app_settings.set_secret("AWS_ROOT_KEY", "x")

    def test_empty_value_is_rejected_rather_than_silently_clearing(self, isolated_secrets):
        with pytest.raises(ValueError, match="revoke"):
            app_settings.set_secret("ANTHROPIC_API_KEY", "   ")


class TestRevoke:
    def test_every_secret_is_revocable_including_cli_only_ones(self, isolated_secrets):
        """Revocation only removes capability, so it can't escalate — and
        'user-revocable' was an explicit requirement."""
        isolated_secrets.encrypt_and_store("GARMIN_PASSWORD", CANARY)
        assert app_settings.revoke_secret("GARMIN_PASSWORD")["configured"] is False
        assert not isolated_secrets.has("GARMIN_PASSWORD")

    def test_revoking_absent_secret_is_not_an_error(self, isolated_secrets):
        result = app_settings.revoke_secret("ANTHROPIC_API_KEY")
        assert result["configured"] is False
        assert result["removed"] is False

    def test_revoke_rejects_unknown_names(self, isolated_secrets):
        with pytest.raises(ValueError, match="Unknown"):
            app_settings.revoke_secret("NOT_A_SECRET")

    def test_every_secret_declares_what_breaks_before_you_revoke_it(self):
        """Revoking Garmin is not the same size of mistake as revoking
        intervals.icu; the UI must be able to say so."""
        for entry in app_settings.secrets_status():
            assert entry["breaks"].strip()
            assert entry["powers"].strip()


class TestExcludedConfig:
    def test_dangerous_config_is_excluded_with_a_stated_reason(self):
        """Absent-with-a-reason beats absent — someone looking for these should
        find the decision, not a gap."""
        names = " ".join(e["name"] for e in app_settings.EXCLUDED_CONFIG)
        assert "ALLOWED_EMAIL" in names
        assert "GARMIN_MCP_COMMAND" in names
        for entry in app_settings.EXCLUDED_CONFIG:
            assert entry["reason"].strip()

    def test_excluded_config_is_not_settable(self, isolated_secrets):
        for name in ("ALLOWED_EMAIL", "GARMIN_MCP_COMMAND"):
            with pytest.raises(ValueError):
                app_settings.set_secret(name, "x")


class TestIntervalsAthleteId:
    def test_store_wins_over_env_so_the_ui_can_configure_it(self, tmp_path, monkeypatch):
        from database import local_store
        from services import intervals_icu

        monkeypatch.setattr(local_store, "_STORE_PATH", tmp_path / "store.json")
        monkeypatch.setattr(local_store.firestore_db, "available", lambda: False)
        monkeypatch.setattr(local_store.backup, "snapshot_before_write", lambda _p: None)
        monkeypatch.setattr(intervals_icu.settings, "intervals_athlete_id", "from-env")

        assert intervals_icu.athlete_id() == "from-env"
        local_store.set_app_config("intervals_athlete_id", "123456")
        assert intervals_icu.athlete_id() == "123456"
        # clearing falls back to env rather than breaking the connection
        local_store.set_app_config("intervals_athlete_id", "")
        assert intervals_icu.athlete_id() == "from-env"
