"""Shared Firebase Admin SDK app — both auth/firebase_auth.py and
database/firestore_db.py need an initialized app, and firebase_admin raises
if you call initialize_app() twice, so init is centralized here."""
from __future__ import annotations

from typing import Optional

import firebase_admin
from firebase_admin import credentials

from config.settings import settings

_app: Optional[firebase_admin.App] = None


def get_app() -> Optional[firebase_admin.App]:
    global _app
    if _app is not None:
        return _app
    if not settings.firebase_credentials_path:
        return None
    cred = credentials.Certificate(settings.firebase_credentials_path)
    _app = firebase_admin.initialize_app(cred)
    return _app
