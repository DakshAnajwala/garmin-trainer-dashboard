"""Data export: assembles the athlete's own data for a chosen date range +
category set, as either one JSON file or a ZIP of per-category CSVs (a
single flat CSV can't represent multiple differently-shaped categories at
once, so ZIP is the CSV path's equivalent of JSON's one-object-many-keys).
"""
from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import date as date_
from typing import Any

from database import local_store

CATEGORIES = ["wellness", "activities", "weight", "ftp_history", "strength_sessions", "workouts", "goals"]


def _in_range(d: str, start: str, end: str) -> bool:
    return bool(d) and start <= d <= end


def _collect(category: str, start: str, end: str) -> Any:
    if category == "wellness":
        snapshots = local_store.get_all_snapshots()
        return {d: s for d, s in snapshots.items() if _in_range(d, start, end)}
    if category == "activities":
        return [a for d, acts in _activities_by_date(start, end).items() for a in acts]
    if category == "weight":
        return [{"date": d, "weight_kg": w} for d, w in local_store.get_weight_history(limit_days=100000) if _in_range(d, start, end)]
    if category == "ftp_history":
        return [t for t in local_store.get_ftp_history() if _in_range(t.get("date", ""), start, end)]
    if category == "strength_sessions":
        return [s for s in local_store.get_strength_sessions(limit_days=100000) if _in_range(s.get("date", ""), start, end)]
    if category == "workouts":
        return local_store.list_workouts()  # not date-scoped — it's a library, not a log
    if category == "goals":
        return local_store.list_goals()  # not date-scoped — freestanding targets
    raise ValueError(f"Unknown export category: {category}")


def _activities_by_date(start: str, end: str) -> dict[str, list[dict[str, Any]]]:
    cached = local_store.get_metric_day("activities_list_large", date_.today(), max_age_seconds=900)
    items = (cached or {}).get("items", []) if cached else []
    imported = local_store.list_imported_activities()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in list(items) + list(imported):
        item_date = (item.get("start_time_local") or "")[:10]
        if _in_range(item_date, start, end):
            grouped.setdefault(item_date, []).append(item)
    return grouped


def build_export(categories: list[str], start: str, end: str, fmt: str) -> tuple[bytes, str, str]:
    data = {cat: _collect(cat, start, end) for cat in categories}
    stamp = f"{start}_to_{end}"

    if fmt == "json":
        content = json.dumps(data, indent=2, default=str).encode("utf-8")
        return content, f"training-data-{stamp}.json", "application/json"

    if fmt == "csv":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for cat, rows in data.items():
                zf.writestr(f"{cat}.csv", _to_csv(rows))
        return buf.getvalue(), f"training-data-{stamp}.zip", "application/zip"

    raise ValueError(f"Unknown export format: {fmt}")


def _to_csv(rows: Any) -> str:
    if isinstance(rows, dict):
        rows = [{"date": k, **(v if isinstance(v, dict) else {"value": v})} for k, v in rows.items()]
    if not rows:
        return ""
    out = io.StringIO()
    fieldnames = sorted({key for row in rows for key in row.keys()})
    writer = csv.DictWriter(out, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in row.items()})
    return out.getvalue()
