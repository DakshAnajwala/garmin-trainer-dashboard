"""Rotating local snapshots of local_store.json.

Motivated by a real incident: a gear entry was deleted with no way to recover
it — the project isn't a git repo, gear isn't in the export categories, and
the delete wrote straight through to Firestore, so both copies went at once.

Design: snapshot the file *before* the first write of each day, so a
snapshot always captures the state as it was before that day's changes. That
is exactly the window you need after an accidental delete — you lose at most
one day of edits, never the whole record. Backups live outside the project
(same convention as the RSA keys) so wiping the repo doesn't wipe them.
"""
from __future__ import annotations

import shutil
from datetime import date as date_
from pathlib import Path
from typing import Optional

_BACKUP_DIR = Path.home() / ".garmin-trainer-dashboard" / "backups"
_KEEP_DAYS = 30


def _snapshot_path(for_date: date_) -> Path:
    return _BACKUP_DIR / f"local_store.{for_date.isoformat()}.json"


def snapshot_before_write(source: Path) -> Optional[Path]:
    """Copy the current file aside if today's snapshot doesn't exist yet.
    Called on every save; a no-op after the first write of the day, so it
    costs one stat() rather than a copy on the hot path."""
    if not source.exists():
        return None
    target = _snapshot_path(date_.today())
    if target.exists():
        return None
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    _prune()
    return target


def _prune() -> None:
    snapshots = sorted(_BACKUP_DIR.glob("local_store.*.json"))
    for stale in snapshots[:-_KEEP_DAYS]:
        stale.unlink(missing_ok=True)


def list_backups() -> list[dict[str, object]]:
    out = []
    for path in sorted(_BACKUP_DIR.glob("local_store.*.json"), reverse=True):
        out.append(
            {
                "date": path.stem.split("local_store.")[-1],
                "path": str(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return out


def restore(backup_date: str, destination: Path) -> Path:
    """Restore a snapshot over the live store. Takes its own safety copy of
    the current state first — a restore is itself destructive, and undoing a
    mistaken restore shouldn't need a second incident to learn from."""
    source = _snapshot_path(date_.fromisoformat(backup_date))
    if not source.exists():
        raise FileNotFoundError(f"No backup for {backup_date}. Available: {[b['date'] for b in list_backups()]}")
    if destination.exists():
        shutil.copy2(destination, _BACKUP_DIR / "local_store.pre-restore.json")
    shutil.copy2(source, destination)
    return destination
