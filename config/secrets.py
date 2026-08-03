"""Asymmetric (RSA-OAEP) encryption for secrets that must never be persisted
in plaintext: the Anthropic API key and Garmin email/password.

Threat model: copying/leaking this project's files (the repo, its `data/`
directory, a cloud sync, a git accident) must not expose usable secrets.

- The PRIVATE key lives outside the project entirely, at
  ~/.garmin-trainer-dashboard/keys/private_key.pem, permissioned 0600
  (owner read/write only). It is never copied into the project directory.
- Only ciphertext (RSA-OAEP encrypted, base64-encoded) is stored inside the
  project, at data/secrets.enc.json.

This does NOT protect against compromise of the whole machine/account (an
attacker with full disk/user access could read the private key too) — it
protects specifically against the project's own files leaking in isolation,
which was the stated goal.
"""
from __future__ import annotations

import base64
import json
import os
import stat
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

_KEY_DIR = Path.home() / ".garmin-trainer-dashboard" / "keys"
_PRIVATE_KEY_PATH = _KEY_DIR / "private_key.pem"
_PUBLIC_KEY_PATH = _KEY_DIR / "public_key.pem"
_SECRETS_PATH = Path(__file__).resolve().parent.parent / "data" / "secrets.enc.json"

_OAEP_PADDING = padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
_OWNER_RW = stat.S_IRUSR | stat.S_IWUSR  # 0600


def _ensure_keypair() -> None:
    if _PRIVATE_KEY_PATH.exists() and _PUBLIC_KEY_PATH.exists():
        return
    _KEY_DIR.mkdir(parents=True, exist_ok=True)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)

    _PRIVATE_KEY_PATH.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    os.chmod(_PRIVATE_KEY_PATH, _OWNER_RW)

    _PUBLIC_KEY_PATH.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    os.chmod(_PUBLIC_KEY_PATH, _OWNER_RW)


def _load_private_key():
    _ensure_keypair()
    return serialization.load_pem_private_key(_PRIVATE_KEY_PATH.read_bytes(), password=None)


def _load_public_key():
    _ensure_keypair()
    return serialization.load_pem_public_key(_PUBLIC_KEY_PATH.read_bytes())


def _load_secrets() -> dict[str, str]:
    if not _SECRETS_PATH.exists():
        return {}
    return json.loads(_SECRETS_PATH.read_text())


def _save_secrets(secrets: dict[str, str]) -> None:
    _SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SECRETS_PATH.write_text(json.dumps(secrets, indent=2))
    os.chmod(_SECRETS_PATH, _OWNER_RW)


def encrypt_and_store(key_name: str, plaintext: str) -> None:
    """RSA can only encrypt data smaller than the key size (~446 bytes here),
    which comfortably fits an API key or password — no hybrid scheme needed."""
    ciphertext = _load_public_key().encrypt(plaintext.encode("utf-8"), _OAEP_PADDING)
    secrets = _load_secrets()
    secrets[key_name] = base64.b64encode(ciphertext).decode("ascii")
    _save_secrets(secrets)


def decrypt(key_name: str) -> Optional[str]:
    encoded = _load_secrets().get(key_name)
    if encoded is None:
        return None
    ciphertext = base64.b64decode(encoded)
    return _load_private_key().decrypt(ciphertext, _OAEP_PADDING).decode("utf-8")


def has(key_name: str) -> bool:
    return key_name in _load_secrets()


def delete(key_name: str) -> bool:
    """Revoke a stored secret. Returns whether anything was removed. The
    ciphertext is dropped from disk, so revocation survives restarts."""
    secrets = _load_secrets()
    if key_name not in secrets:
        return False
    del secrets[key_name]
    _save_secrets(secrets)
    return True
