"""Pull today's Garmin data into the local cache, unattended.

Why this exists: everything is fetched lazily when the dashboard is opened,
which leaves real holes. Garmin's lactate-threshold endpoint returns only a
*current* value with no history, so a threshold change on a day you never
opened the app is lost permanently — it can only be detected by diffing
consecutive stored snapshots. The PMC has the same shape of gap. A daily run
closes both, and warms the cache so the app opens instantly.

Run manually:
    python -m scripts.sync

Or on a schedule (macOS/Linux) — 6am daily:
    0 6 * * *  cd /path/to/repo && .venv/bin/python -m scripts.sync >> /tmp/garmin-sync.log 2>&1

Safe to run repeatedly: past days are already cached permanently, and today's
entry is simply refreshed.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date as date_, timedelta

from database import local_store
from garmin_mcp.garmin_client import GarminMCPClient


async def sync_day(client: GarminMCPClient, target: date_, force: bool = False) -> str:
    if not force and local_store.get_snapshot(target, max_age_seconds=None) is not None and target != date_.today():
        return "cached"
    snapshot = await client.get_daily_snapshot(target)
    local_store.save_snapshot(target, snapshot.model_dump(mode="json"))
    return "fetched"


async def run(days: int, force: bool) -> int:
    today = date_.today()
    targets = [today - timedelta(days=offset) for offset in range(days)]

    try:
        async with GarminMCPClient() as client:
            for target in targets:
                try:
                    status = await sync_day(client, target, force)
                    print(f"  {target}: {status}")
                except Exception as exc:
                    # One bad day shouldn't abort the rest — a missing weigh-in
                    # or a gap in Garmin's data is normal, not fatal.
                    print(f"  {target}: failed — {exc}")

            # The activity list is a single cache entry covering all days, so
            # it's refreshed once rather than per-day.
            try:
                items = await client.get_activities(limit=100)
                local_store.save_metric_day(
                    "activities_list_large", today, {"date": today.isoformat(), "items": items}
                )
                print(f"  activities: refreshed ({len(items)})")
            except Exception as exc:
                print(f"  activities: failed — {exc}")
    except Exception as exc:
        print(f"Garmin connection failed: {exc}", file=sys.stderr)
        return 1

    print("Sync complete.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Pull Garmin data into the local cache")
    parser.add_argument("--days", type=int, default=3, help="How many days back to sync (default 3)")
    parser.add_argument("--force", action="store_true", help="Refetch even days already cached")
    args = parser.parse_args()
    print(f"Syncing {args.days} day(s) back from {date_.today()}...")
    raise SystemExit(asyncio.run(run(args.days, args.force)))


if __name__ == "__main__":
    main()
