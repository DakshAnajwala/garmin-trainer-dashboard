"""Firebase ID token verification for FastAPI routes.

Single-user app: beyond "is this a genuinely valid Firebase Auth token," the
caller's email must match settings.allowed_email, so a token from a
different Google account (or a forged/replayed one) still can't get in.
"""
from __future__ import annotations

from fastapi import Header, HTTPException
from firebase_admin import auth as firebase_auth_sdk

from config import firebase_app
from config.settings import settings


async def verify_token(authorization: str = Header(default="")) -> dict:
    app = firebase_app.get_app()
    if app is None:
        # Firebase not configured (local dev before setup, or FIREBASE_CREDENTIALS_PATH
        # unset) — let requests through unauthenticated rather than lock out local dev.
        return {"uid": "local-dev", "email": None}

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ")

    try:
        decoded = firebase_auth_sdk.verify_id_token(token, app=app)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}") from exc

    if settings.allowed_email and decoded.get("email") != settings.allowed_email:
        raise HTTPException(status_code=403, detail="Not authorized for this account")

    return decoded
