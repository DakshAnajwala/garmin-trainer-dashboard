"""Settings: what's configured, what it powers, what breaks if you revoke it.

The rule this module exists to enforce: **a secret's value never leaves the
encrypted store.** Everything here reports *about* secrets — configured or not,
what they power, what dies without them — and never returns, logs, or echoes
one. Same contract services/custom_model.py already follows for the
bring-your-own-algorithm key.

Two deliberate asymmetries, both about limiting blast radius rather than
convenience:

- **Settable from the UI: Anthropic and intervals.icu only.** Those are the two
  that are broken or absent and currently need a CLI script to fix, which is a
  bad failure mode for a key that expires. Garmin's email/password stay
  CLI-only: accepting a third-party account password through a web form is
  meaningfully more attack surface than accepting an API token, and this app's
  `allowed_email` still defaults to empty (i.e. any Google account that signs
  in is accepted). Until that's fixed, the fewer credential-writing endpoints
  the better.
- **Revocable: all of them.** Revocation only ever removes capability, so it
  can't be used to escalate — and "user-revocable" was an explicit requirement.
"""
from __future__ import annotations

from typing import Any

from config import secrets

#: name -> what it is, what it powers, and what stops working without it. The
#: "breaks" text is shown *before* a revoke is confirmed: revoking Garmin is
#: not the same size of mistake as revoking intervals.icu, and the UI shouldn't
#: pretend otherwise.
SECRETS: dict[str, dict[str, Any]] = {
    "ANTHROPIC_API_KEY": {
        "label": "Anthropic (AI coach)",
        "powers": "Coach chat, per-ride analysis, and the Morning Brief's written summary.",
        "breaks": "The Coach tab and ride analysis stop working. Everything else is unaffected.",
        "settable": True,
        "help": "console.anthropic.com → API keys.",
    },
    "INTERVALS_API_KEY": {
        "label": "intervals.icu",
        "powers": "Fitness/Fatigue/Form (PMC) chart, and the Form signal in the load advisory.",
        "breaks": "The PMC chart empties and the load advisory falls back to Garmin's ACWR alone.",
        "settable": True,
        "help": "intervals.icu → Settings → Developer → API key.",
    },
    "GARMIN_EMAIL": {
        "label": "Garmin account email",
        "powers": "Every Garmin sync: readiness, HRV, sleep, activities, power data.",
        "breaks": "All Garmin data fetching stops. Cached data still displays until it goes stale.",
        "settable": False,
        "help": "Set via `python -m scripts.set_secrets` — deliberately not editable here.",
    },
    "GARMIN_PASSWORD": {
        "label": "Garmin account password",
        "powers": "Every Garmin sync: readiness, HRV, sleep, activities, power data.",
        "breaks": "All Garmin data fetching stops. Cached data still displays until it goes stale.",
        "settable": False,
        "help": "Set via `python -m scripts.set_secrets` — deliberately not editable here.",
    },
}

#: Config that is intentionally NOT exposed, and why. Surfaced in the UI so it
#: reads as a decision rather than an oversight — someone looking for these
#: should find the reason, not a gap.
EXCLUDED_CONFIG = [
    {
        "name": "ALLOWED_EMAIL",
        "reason": (
            "The auth allowlist. Editable from the UI, any signed-in user could grant access to "
            "other accounts — privilege escalation. Stays an environment variable."
        ),
    },
    {
        "name": "GARMIN_MCP_COMMAND / GARMIN_MCP_ARGS",
        "reason": (
            "A shell command the server executes. A text box that edits it is a command-injection "
            "hole. Stays an environment variable."
        ),
    },
]


def secrets_status() -> list[dict[str, Any]]:
    """Which secrets exist — never their values."""
    return [
        {
            "name": name,
            "label": meta["label"],
            "configured": secrets.has(name),
            "powers": meta["powers"],
            "breaks": meta["breaks"],
            "settable": meta["settable"],
            "help": meta["help"],
        }
        for name, meta in SECRETS.items()
    ]


def set_secret(name: str, value: str) -> dict[str, Any]:
    if name not in SECRETS:
        raise ValueError(f"Unknown secret '{name}'.")
    if not SECRETS[name]["settable"]:
        raise ValueError(
            f"{SECRETS[name]['label']} can't be set from the app — use `python -m scripts.set_secrets`. "
            "This is deliberate: it keeps account passwords out of web forms."
        )
    if not value.strip():
        raise ValueError("Empty value. To remove a key, revoke it instead.")
    secrets.encrypt_and_store(name, value.strip())
    return {"name": name, "configured": True}


def revoke_secret(name: str) -> dict[str, Any]:
    """Revocation is allowed for every secret — it only removes capability, so
    it can't be used to gain any."""
    if name not in SECRETS:
        raise ValueError(f"Unknown secret '{name}'.")
    removed = secrets.delete(name)
    return {"name": name, "configured": False, "removed": removed}
