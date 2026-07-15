"""List or restore local_store.json backups.

    python -m scripts.backups                    # list available snapshots
    python -m scripts.backups --restore 2026-07-15

Snapshots are taken automatically before the first write of each day, so
restoring 2026-07-15 gives you the store as it was before anything changed
that day.

A restore also pushes the restored values back up to Firestore. Without that
it would silently do nothing: reads let Firestore's copy win for synced keys
(gear, goals, weights...), so a file-only restore is invisible to the app.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from database import backup, local_store

_STORE_PATH = Path(__file__).resolve().parent.parent / "data" / "local_store.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="List or restore local_store.json backups")
    parser.add_argument("--restore", metavar="YYYY-MM-DD", help="Restore the snapshot from this date")
    args = parser.parse_args()

    if args.restore:
        restored = backup.restore(args.restore, _STORE_PATH)
        synced = local_store.resync_file_to_cloud()
        print(f"Restored {args.restore} -> {restored}")
        print(f"Pushed {len(synced)} synced section(s) back to Firestore: {sorted(synced)}")
        print("Your pre-restore state was saved to local_store.pre-restore.json in the backup dir.")
        print("Restart the backend to pick it up.")
        return

    backups = backup.list_backups()
    if not backups:
        print("No backups yet. One is taken automatically before the first write of each day.")
        return
    print(f"{len(backups)} backup(s):\n")
    for b in backups:
        print(f"  {b['date']}   {b['size_bytes'] / 1024:.0f} KB   {b['path']}")
    print(f"\nRestore with: python -m scripts.backups --restore {backups[0]['date']}")


if __name__ == "__main__":
    main()
