"""Bring-your-own-algorithm: run the athlete's own model code against their
own data, safely.

The athlete supplies an HTTPS endpoint (their LLM, their notebook server,
whatever) plus an API key. The app POSTs their ride history summary, receives
model parameters back, and — critically — **never applies them silently**:
the response is validated, clamped to physiological bounds, diffed against
the current model, and scored by the advisory backtest, all *before* the
athlete clicks apply.

Trust boundary, spelled out: the endpoint is athlete-controlled but still
external code, so its output is treated as hostile until proven boring —

- The key is encrypted at rest (config/secrets, same RSA-OAEP store as the
  Anthropic key), sent only as an Authorization header over HTTPS, and never
  logged, never echoed in errors, never put in a URL.
- The call is sandboxed: 30 s timeout, no redirects (a redirect could re-aim
  the athlete's key at an attacker's host), 256 KB response cap, JSON only.
- Returned params: unknown keys dropped, non-numeric / NaN / infinite values
  rejected, survivors clamped to PARAM_BOUNDS. An empty survivor set fails
  loudly rather than applying nothing quietly.
- Applying writes the params as **locked overrides** attributed to the
  endpoint, so a later auto-recompute can't silently undo what the athlete
  explicitly chose — unlocking hands control back to the fit.
"""
from __future__ import annotations

import math
from typing import Any
from urllib.parse import urlparse

import httpx

from config import secrets
from database import local_store
from services import model_backtest, physiology_model, power_curve

_KEY_NAME = "custom_model_api_key"
_TIMEOUT_SEC = 30
_MAX_RESPONSE_BYTES = 256 * 1024


def configure(endpoint_url: str, api_key: str) -> dict[str, Any]:
    parsed = urlparse(endpoint_url)
    is_local = parsed.hostname in ("localhost", "127.0.0.1")
    if parsed.scheme != "https" and not is_local:
        raise ValueError("Endpoint must be https:// (plain http would expose your API key in transit).")
    if not parsed.hostname:
        raise ValueError("Endpoint URL has no host.")
    secrets.encrypt_and_store(_KEY_NAME, api_key)
    store_cfg = {"endpoint_url": endpoint_url, "configured": True}
    store = local_store._load()
    store["custom_model_config"] = store_cfg
    local_store._save(store)
    return status()


def revoke() -> dict[str, Any]:
    secrets.delete(_KEY_NAME)
    store = local_store._load()
    store.pop("custom_model_config", None)
    local_store._save(store)
    return status()


def status() -> dict[str, Any]:
    cfg = local_store._load().get("custom_model_config") or {}
    return {
        "configured": bool(cfg.get("configured")) and secrets.has(_KEY_NAME),
        "endpoint_url": cfg.get("endpoint_url"),
        "key_stored": secrets.has(_KEY_NAME),  # never the key itself
    }


def _athlete_payload() -> dict[str, Any]:
    """What the athlete's algorithm gets to work with: their merged power
    curve, FTP history, weights, and per-ride curve summaries. Derived
    summaries only — raw GPS tracks stay home."""
    merged = power_curve.merged_curve()
    return {
        "power_curve": {str(d): p["watts"] for d, p in merged.items()},
        "ftp_history": local_store.get_ftp_history(),
        "weight_history": local_store.get_weight_history(limit_days=365),
        "rides": [
            {
                "activity_id": str(r["activity_id"]),
                "date": r.get("date"),
                "curve": {
                    str(d): p["watts"]
                    for d, p in power_curve.ride_curve(r["samples"]).items()
                    if p.get("reliable")
                },
            }
            for r in power_curve.cached_rides()
        ],
        "expected_response": {
            "format": "JSON object",
            "params": {k: {"bounds": v} for k, v in physiology_model.PARAM_BOUNDS.items()},
        },
    }


def validate_and_clamp(raw: Any) -> tuple[dict[str, float], list[str]]:
    """Hostile-input filter. Returns (accepted_params, notes). Raises ValueError
    when nothing survives — a silent no-op apply would be worse than an error."""
    notes: list[str] = []
    if not isinstance(raw, dict):
        raise ValueError(f"Endpoint returned {type(raw).__name__}, expected a JSON object of params.")

    accepted: dict[str, float] = {}
    for name, value in raw.items():
        if name not in physiology_model.PARAM_BOUNDS:
            notes.append(f"'{name}' is not a model parameter — dropped.")
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            notes.append(f"'{name}' is not numeric ({value!r}) — rejected.")
            continue
        value = float(value)
        if math.isnan(value) or math.isinf(value):
            notes.append(f"'{name}' is NaN/inf — rejected.")
            continue
        lo, hi = physiology_model.PARAM_BOUNDS[name]
        clamped = max(lo, min(hi, value))
        if clamped != value:
            notes.append(f"'{name}' = {value} outside physiological bounds [{lo}, {hi}] — clamped to {clamped}.")
        accepted[name] = round(clamped, 3)

    if not accepted:
        raise ValueError("No valid model parameters in the response. " + " ".join(notes))
    return accepted, notes


def propose() -> dict[str, Any]:
    """Call the endpoint, validate, and return proposal + diff + advisory —
    without applying anything."""
    st = status()
    if not st["configured"]:
        raise ValueError("No custom endpoint configured.")
    api_key = secrets.decrypt(_KEY_NAME)

    try:
        resp = httpx.post(
            st["endpoint_url"],
            json=_athlete_payload(),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=_TIMEOUT_SEC,
            follow_redirects=False,  # a redirect could re-aim the key elsewhere
        )
    except httpx.HTTPError as exc:
        # exc gets stringified into API responses — make sure the key can't ride along.
        raise ValueError(f"Endpoint call failed: {type(exc).__name__}: {exc}".replace(api_key, "***")) from exc

    if resp.status_code != 200:
        raise ValueError(f"Endpoint returned HTTP {resp.status_code}.")
    if len(resp.content) > _MAX_RESPONSE_BYTES:
        raise ValueError("Endpoint response exceeds the 256KB cap — rejected.")
    try:
        raw = resp.json()
    except ValueError as exc:
        raise ValueError("Endpoint response is not valid JSON.") from exc

    accepted, notes = validate_and_clamp(raw)
    current = physiology_model.effective_values()
    diff = {
        name: {"current": current.get(name), "proposed": value}
        for name, value in accepted.items()
        if current.get(name) != value
    }
    advisory = model_backtest.evaluate_change({**current, **accepted}, current)
    return {"proposed": accepted, "diff": diff, "validation_notes": notes, "advisory": advisory}


def apply(proposed: dict[str, float]) -> dict[str, Any]:
    """Write the (already validated) proposal as locked overrides and
    recompute. Runs the same validation again — the apply call arrives over
    HTTP and must not trust that its caller was propose()."""
    accepted, _notes = validate_and_clamp(proposed)
    endpoint = status().get("endpoint_url") or "custom algorithm"
    for name, value in accepted.items():
        local_store.set_model_override(name, value, locked=True, reason=f"custom algorithm ({endpoint})")
    return physiology_model.compute()
