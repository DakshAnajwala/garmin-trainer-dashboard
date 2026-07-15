"""Firestore-backed persistence for the small, genuinely-irreplaceable
user-entered data only (weights/ftp_tests/goals/workouts/strength_sessions/
aero_profile/block_week) — see local_store.py's _SYNCED_KEYS.

Deliberately excludes the Garmin-derived caches (snapshots, per-metric
history, activity_details, activity_splits): those are re-fetchable from
Garmin/intervals.icu at any time, so there's no data-loss risk in leaving
them local-disk-only, and it sidesteps Firestore's 1MiB-per-document cap —
a single cached activity's raw sample series alone has been observed at
200-330KB, so syncing those would blow the cap within a handful of activities.
"""
from __future__ import annotations

from typing import Any, Optional

from firebase_admin import firestore

from config import firebase_app

_COLLECTION = "dashboard"
_DOCUMENT = "main"
_client = None


def _client_or_none():
    global _client
    if _client is not None:
        return _client
    app = firebase_app.get_app()
    if app is None:
        return None
    _client = firestore.client(app)
    return _client


def available() -> bool:
    return _client_or_none() is not None


def load_main() -> Optional[dict[str, Any]]:
    client = _client_or_none()
    if client is None:
        return None
    doc = client.collection(_COLLECTION).document(_DOCUMENT).get()
    return doc.to_dict() or {} if doc.exists else {}


def save_main(data: dict[str, Any]) -> None:
    client = _client_or_none()
    if client is None:
        return
    client.collection(_COLLECTION).document(_DOCUMENT).set(data)
