"""intervals.icu integration — pulls athlete-computed Fitness/Fatigue/Form
(CTL/ATL/TSB) directly, rather than re-deriving TSS/CTL/ATL ourselves from
Garmin data (which would need per-activity normalized-power math we don't
have solid inputs for). This is the app's first non-Garmin data source.

UNVERIFIED AGAINST LIVE DATA: built from intervals.icu's public forum posts
and API docs (no account/API key was available during this build to test
against). Confirmed from public docs: base URL, HTTP Basic Auth scheme
("API_KEY" as username, the real key as password), and the wellness list
endpoint's path + oldest/newest query params. The exact field names for
ctl/atl/form on a wellness record are the well-documented ones from
intervals.icu's community docs, but re-verify the actual response shape
once a real API key is configured — see the raw-passthrough debug function
below, modeled on the same --call pattern used to verify Garmin's MCP tools.
"""
from __future__ import annotations

from datetime import date as date_
from typing import Any, Optional

import httpx

from config.settings import settings

_BASE_URL = "https://intervals.icu/api/v1"


def is_configured() -> bool:
    return bool(settings.intervals_api_key and settings.intervals_athlete_id)


def _auth() -> tuple[str, str]:
    return ("API_KEY", settings.intervals_api_key)


async def get_wellness_range_raw(start: date_, end: date_) -> Any:
    """Raw passthrough — inspect this before trusting normalize_wellness()."""
    if not is_configured():
        raise RuntimeError(
            "intervals.icu isn't configured. Run `python -m scripts.set_secrets` to set your API "
            "key, and set INTERVALS_ATHLETE_ID in .env (find it in your intervals.icu profile URL)."
        )
    url = f"{_BASE_URL}/athlete/{settings.intervals_athlete_id}/wellness"
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(url, params={"oldest": start.isoformat(), "newest": end.isoformat()}, auth=_auth())
        resp.raise_for_status()
        return resp.json()


def normalize_wellness(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for r in raw or []:
        ctl = r.get("ctl")
        atl = r.get("atl")
        form = r.get("form")
        if form is None and ctl is not None and atl is not None:
            form = round(ctl - atl, 1)
        records.append(
            {
                "date": r.get("id") or r.get("date"),
                "ctl": ctl,
                "atl": atl,
                "form": form,
            }
        )
    return records


async def get_wellness_range(start: date_, end: date_) -> list[dict[str, Any]]:
    raw = await get_wellness_range_raw(start, end)
    return normalize_wellness(raw)
