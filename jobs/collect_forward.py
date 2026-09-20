"""Forward collection: grow the Tier-1 CS2 dataset + Pinnacle benchmark daily.

Run on a scheduler (e.g. Windows Task Scheduler, once or twice a day). Each run:
  1. refreshes finished Tier-1 matches (idempotent upsert)
  2. ingests per-map results for any new matches (incremental)
  3. pulls Pinnacle closing lines for recently-finished matches, skipping
     fixtures already stored so the OddsPapi free quota lasts

Usage:
    py -m jobs.collect_forward            # last 7 days of odds
    py -m jobs.collect_forward --days 10
"""
from __future__ import annotations

import argparse
import datetime as dt

from cs2edge.db.schema import connect, init_db
from cs2edge.ingest import bo3, oddspapi


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7, help="odds lookback window (days)")
    args = ap.parse_args()

    init_db()
    con = connect()
    try:
        print("matches:", bo3.backfill_matches(con))
        print("games:", bo3.backfill_games(con))
        end = dt.date.today()
        start = end - dt.timedelta(days=args.days)
        print(f"odds {start}..{end}:", oddspapi.ingest_range(con, start, end))
    finally:
        con.close()


if __name__ == "__main__":
    main()
