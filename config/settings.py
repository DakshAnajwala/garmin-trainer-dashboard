"""Centralized application configuration.

Non-sensitive config loads from environment variables / .env as usual.
Secrets (Anthropic API key, Garmin email/password) are NOT read from .env —
they're decrypted on demand from config/secrets.py's encrypted store. Run
`python -m scripts.set_secrets` once to populate them.
"""
from __future__ import annotations

import shlex

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from config import secrets as _secrets


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Anthropic (services/claude_analyzer.py) ---
    anthropic_model: str = Field(default="claude-sonnet-5", alias="ANTHROPIC_MODEL")

    # --- Firebase (database/firestore_db.py, auth/firebase_auth.py) ---
    firebase_credentials_path: str = Field(default="", alias="FIREBASE_CREDENTIALS_PATH")
    # Single-user app: a valid Firebase token isn't enough on its own — the
    # signed-in Google account's email must match this, or the request is
    # rejected. Stops anyone else who signs in with their own Google account
    # (once this is on the public internet) from seeing your data.
    # Set this to YOUR Google account email in .env. Leaving it empty means any
    # Google account that signs in is accepted — fine for pure local use, but
    # set it before exposing the app to the internet.
    allowed_email: str = Field(default="", alias="ALLOWED_EMAIL")

    # --- Garmin MCP server (garmin_mcp/garmin_client.py) ---
    garmin_mcp_command: str = Field(default="npx", alias="GARMIN_MCP_COMMAND")
    garmin_mcp_args: str = Field(
        default="", alias="GARMIN_MCP_ARGS", description="Space-separated args, e.g. '-y some-garmin-mcp-server'"
    )

    # --- Training goal (referenced by coaching prompts) ---
    # Your goal, in W/kg. Tracking is deliberately dynamic — target watts =
    # target_wkg * today's actual weight — so the target moves with your weight
    # instead of a fixed wattage that silently gets easier as you get heavier.
    target_wkg: float = Field(default=4.0, alias="TARGET_WKG")

    # --- intervals.icu (services/intervals_icu.py) ---
    # Athlete ID isn't sensitive (it's just a numeric account identifier), so it's
    # plain .env config; the API key is encrypted like the other secrets.
    intervals_athlete_id: str = Field(default="", alias="INTERVALS_ATHLETE_ID")

    @property
    def anthropic_api_key(self) -> str:
        return _secrets.decrypt("ANTHROPIC_API_KEY") or ""

    @property
    def intervals_api_key(self) -> str:
        return _secrets.decrypt("INTERVALS_API_KEY") or ""

    @property
    def garmin_email(self) -> str:
        return _secrets.decrypt("GARMIN_EMAIL") or ""

    @property
    def garmin_password(self) -> str:
        return _secrets.decrypt("GARMIN_PASSWORD") or ""

    @property
    def garmin_mcp_args_list(self) -> list[str]:
        return shlex.split(self.garmin_mcp_args) if self.garmin_mcp_args else []

    @property
    def garmin_mcp_env(self) -> dict[str, str]:
        """Extra env vars to forward to the Garmin MCP subprocess (the MCP SDK
        only inherits a safe allowlist by default, so credentials must be passed
        explicitly here rather than relying on our own process environment)."""
        env: dict[str, str] = {}
        if self.garmin_email:
            env["GARMIN_EMAIL"] = self.garmin_email
        if self.garmin_password:
            env["GARMIN_PASSWORD"] = self.garmin_password
        return env


settings = Settings()
