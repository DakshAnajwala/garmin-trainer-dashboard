"""One-time (or rotate-anytime) setup: encrypt your Anthropic API key and
Garmin email/password so only ciphertext is ever persisted on disk.

Run from the project root with the venv active:
    python -m scripts.set_secrets

Input is hidden (getpass) — nothing you type here is echoed to the terminal,
logged, or written to disk in plaintext.
"""
from __future__ import annotations

import getpass

from config.secrets import encrypt_and_store

_SECRETS = [
    ("ANTHROPIC_API_KEY", "Anthropic API key"),
    ("GARMIN_EMAIL", "Garmin account email"),
    ("GARMIN_PASSWORD", "Garmin account password"),
    ("INTERVALS_API_KEY", "intervals.icu API key (from Settings > Developer Settings)"),
]


def main() -> None:
    print("Press Enter on any prompt to skip/leave that secret unchanged.\n")
    for key_name, label in _SECRETS:
        value = getpass.getpass(f"{label} (input hidden): ").strip()
        if not value:
            print(f"  skipped {label}")
            continue
        encrypt_and_store(key_name, value)
        print(f"  encrypted and stored {label}")
    print("\nDone. Plaintext values were never written to disk.")


if __name__ == "__main__":
    main()
